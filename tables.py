"""Wczytywanie tabel z kwestiami dialogowymi w (prawie) dowolnym formacie.

Obsługiwane: TSV, CSV (przecinek / średnik / pionowa kreska - wykrywane automatycznie),
TXT, XLSX/XLSM (bez zewnętrznych bibliotek), ODS (bez zewnętrznych bibliotek),
XLS (wymaga `xlrd`), tabele Markdown, tabele HTML, JSON oraz tekst wklejony ze schowka
(np. skopiowany prosto z Excela / Google Sheets / LibreOffice).

Rozpoznawane kolumny (wielkość liter i polskie znaki bez znaczenia):
  set      - zestaw / wariant (np. kontrolna / badawcza)  -> przełącznik w nagłówku
  section  - sekcja / zakładka                             -> zakładki
  group    - grupa / kategoria / temat                     -> podzakładki / nagłówki
  label    - etykieta przycisku
  value    - tekst, który robot ma powiedzieć
  order    - kolejność (opcjonalnie)
  output   - kto mówi: robot / narrator (głośnik PC, nagranie głosu NAO); puste = przełącznik w panelu

Bez nagłówka kolumny są zgadywane po ich liczbie:
  1: tekst | 2: etykieta, tekst | 3: grupa, etykieta, tekst
  4: sekcja, grupa, etykieta, tekst | 5+: zestaw, sekcja, grupa, etykieta, tekst
"""

import csv
import hashlib
import io
import json
import os
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

FIELDS = ("set", "section", "group", "label", "value", "order", "output")

ALIASES = {
    "set": {"set", "zestaw", "wariant", "warunek", "condition", "grupabadawcza", "mode", "tryb", "variant"},
    "section": {"section", "sekcja", "zakladka", "tab", "panel", "etap", "stage", "faza", "part", "czesc"},
    "group": {"group", "grupa", "kategoria", "category", "temat", "topic", "subgroup", "podgrupa", "watek"},
    "label": {"label", "etykieta", "przycisk", "button", "nazwa", "name", "title", "tytul", "skrot", "short"},
    "value": {"value", "text", "tekst", "kwestia", "wypowiedz", "tresc", "say", "utterance", "line",
              "speech", "dialog", "dialogue", "content", "zdanie", "kwestiadialogowa", "mowa"},
    "order": {"order", "kolejnosc", "nr", "lp", "no", "index", "sort", "pozycja"},
    "output": {"output", "wyjscie", "mowca", "speaker", "kto", "glos", "voice", "device", "urzadzenie", "odtwarzanie"},
}

# Wartości kolumny "output": kto wypowiada kwestię.
OUTPUT_ROBOT = {"robot", "agent", "nao", "pepper", "robothumanoidalny"}
OUTPUT_SPEAKER = {"narrator", "glosnik", "speaker", "asystent", "asystentglosowy", "assistant", "pc", "komputer", "mp3"}


def normalize_output(value):
    key = _norm(value)
    if key in OUTPUT_ROBOT:
        return "robot"
    if key in OUTPUT_SPEAKER:
        return "speaker"
    return ""

# Sekcje wyświetlane w stałym panelu bocznym (jak kolumna "right" w oryginale).
PINNED_SECTIONS = {"right", "response", "responses", "prawa", "prawy", "boczne", "boczny", "szybkie",
                   "quick", "zawsze", "stale", "pinned", "side", "reakcje"}

# Ładniejsze nazwy dla sekcji z oryginalnego szablonu WoZ.
SECTION_TITLES = {"start": "Wstęp + zakończenie", "problems": "Dylematy", "problem": "Dylematy",
                  "right": "Szybkie reakcje", "response": "Szybkie reakcje"}

DELIMITED_EXT = {".tsv", ".tab", ".csv", ".txt", ".psv", ".dsv", ""}
SUPPORTED_EXT = sorted(DELIMITED_EXT - {""} | {".xlsx", ".xlsm", ".ods", ".xls", ".md", ".markdown",
                                               ".html", ".htm", ".json"})


class TableError(Exception):
    pass


def _norm(text):
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


# --------------------------------------------------------------------------- czytniki surowe

def _decode(data):
    for enc in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _read_markdown(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c) and any(cells):
            continue  # wiersz |---|---|
        rows.append(cells)
    return rows


class _HTMLTables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self._row, self._cell, self._depth = [], None, None, 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            self.tables.append([])
        elif tag == "tr" and self._depth:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.tables[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._depth:
            self._depth -= 1

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _read_html(text):
    parser = _HTMLTables()
    parser.feed(text)
    return [("Tabela %d" % (i + 1), t) for i, t in enumerate(parser.tables) if t]


def _read_delimited(text, ext=""):
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    if ext in (".tsv", ".tab"):
        delim = "\t"
    else:
        sample = "\n".join(lines[:20])
        counts = {d: sample.count(d) for d in ("\t", ";", ",", "|")}
        if counts["\t"]:
            delim = "\t"  # tekst skopiowany z arkusza zawsze używa tabulatora
        else:
            try:
                delim = csv.Sniffer().sniff(sample, delimiters=";,|").delimiter
            except csv.Error:
                delim = max(counts, key=counts.get) if max(counts.values()) else "\t"
    return list(csv.reader(io.StringIO(text), delimiter=delim))


def _read_json(text):
    data = json.loads(text)
    if isinstance(data, dict):
        # {"arkusz": [...], ...} albo {"rows": [...]}
        data = data.get("rows") or data.get("items") or data
        if isinstance(data, dict):
            return [(name, _json_rows(rows)) for name, rows in data.items() if isinstance(rows, list)]
    return [("", _json_rows(data))]


def _json_rows(items):
    if not items:
        return []
    if all(isinstance(i, dict) for i in items):
        header = []
        for item in items:
            for key in item:
                if key not in header:
                    header.append(key)
        return [header] + [[item.get(k, "") for k in header] for item in items]
    if all(isinstance(i, str) for i in items):
        return [[i] for i in items]
    return [list(i) if isinstance(i, (list, tuple)) else [i] for i in items]


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _col_index(ref):
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters:
        return None
    n = 0
    for ch in letters.group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _read_xlsx(data):
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise TableError("Plik nie wygląda na poprawny XLSX.")
    names = set(zf.namelist())

    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(zf.read("xl/sharedStrings.xml")):
            parts = []
            for child in si:  # <t> albo <r><t> (pomijamy <rPh> - fonetykę)
                if _local(child.tag) == "t":
                    parts.append(child.text or "")
                elif _local(child.tag) == "r":
                    parts.extend(t.text or "" for t in child if _local(t.tag) == "t")
            shared.append("".join(parts))

    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for rel in ET.fromstring(zf.read("xl/_rels/workbook.xml.rels")):
            target = rel.get("Target", "")
            target = target.lstrip("/") if target.startswith("/") else "xl/" + target
            rels[rel.get("Id")] = os.path.normpath(target).replace("\\", "/")

    sheets = []
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    for el in wb.iter():
        if _local(el.tag) == "sheet":
            rid = next((v for k, v in el.attrib.items() if _local(k) == "id"), None)
            path = rels.get(rid)
            if path in names:
                sheets.append((el.get("name", ""), path))
    if not sheets:
        sheets = [(n.rsplit("/", 1)[-1], n) for n in sorted(names) if n.startswith("xl/worksheets/sheet")]

    result = []
    for name, path in sheets:
        rows = []
        for row in ET.fromstring(zf.read(path)).iter():
            if _local(row.tag) != "row":
                continue
            values = {}
            for pos, c in enumerate(el for el in row if _local(el.tag) == "c"):
                idx = _col_index(c.get("r"))
                idx = pos if idx is None else idx
                kind = c.get("t", "n")
                text = ""
                if kind == "inlineStr":
                    text = "".join(t.text or "" for t in c.iter() if _local(t.tag) == "t")
                else:
                    v = next((el.text for el in c if _local(el.tag) == "v"), None)
                    if v is not None:
                        if kind == "s":
                            text = shared[int(v)] if v.isdigit() and int(v) < len(shared) else ""
                        elif kind == "b":
                            text = "PRAWDA" if v == "1" else "FAŁSZ"
                        elif kind == "n":
                            try:
                                text = _cell(float(v))
                            except ValueError:
                                text = v
                        else:
                            text = v
                values[idx] = text
            if values:
                width = max(values) + 1
                rows.append([values.get(i, "") for i in range(width)])
        result.append((name, rows))
    return result


def _read_ods(data):
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        root = ET.fromstring(zf.read("content.xml"))
    except (zipfile.BadZipFile, KeyError):
        raise TableError("Plik nie wygląda na poprawny ODS.")

    def flatten(node, parts):
        tag = _local(node.tag)
        if tag == "s":
            parts.append(" " * int(attr(node, "c", 1)))
        elif tag == "line-break":
            parts.append("\n")
        elif tag == "tab":
            parts.append("\t")
        elif tag != "annotation":
            parts.append(node.text or "")
            for child in node:
                flatten(child, parts)
                parts.append(child.tail or "")

    def cell_text(cell):
        paras = []
        for p in cell:
            if _local(p.tag) == "p":
                parts = []
                flatten(p, parts)
                paras.append("".join(parts))
        return "\n".join(paras)

    def attr(el, name, default=None):
        return next((v for k, v in el.attrib.items() if _local(k) == name), default)

    result = []
    for table in root.iter():
        if _local(table.tag) != "table":
            continue
        rows = []
        for row in table.iter():
            if _local(row.tag) != "table-row":
                continue
            cells = []
            for cell in row:
                if _local(cell.tag) not in ("table-cell", "covered-table-cell"):
                    continue
                text = cell_text(cell)
                repeat = int(attr(cell, "number-columns-repeated", 1))
                cells.extend([text] * (min(repeat, 64) if text else repeat if repeat < 64 else 1))
            while cells and not cells[-1]:
                cells.pop()
            if cells:
                repeat = int(attr(row, "number-rows-repeated", 1))
                rows.extend([cells] * min(repeat, 1000))
        result.append((attr(table, "name", ""), rows))
    return result


def _read_xls(data):
    try:
        import xlrd  # type: ignore
    except ImportError:
        raise TableError("Stary format .xls wymaga biblioteki xlrd (pip install xlrd) "
                         "- albo zapisz plik jako .xlsx / .ods / .tsv.")
    book = xlrd.open_workbook(file_contents=data)
    return [(s.name, [[_cell(v) for v in s.row_values(r)] for r in range(s.nrows)]) for s in book.sheets()]


def read_raw(data, filename=""):
    """Zwraca listę (nazwa_arkusza, wiersze)."""
    ext = os.path.splitext(filename.lower())[1]
    if ext in (".xlsx", ".xlsm") or (data[:2] == b"PK" and b"xl/" in data[:2000]):
        return _read_xlsx(data)
    if ext == ".ods" or (data[:2] == b"PK" and b"opendocument.spreadsheet" in data[:200]):
        return _read_ods(data)
    if ext == ".xls" or data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return _read_xls(data)

    text = _decode(data) if isinstance(data, bytes) else data
    stripped = text.lstrip()
    if ext == ".json" or (stripped[:1] in "[{" and ext not in DELIMITED_EXT - {""}):
        try:
            return _read_json(text)
        except ValueError:
            if ext == ".json":
                raise TableError("Niepoprawny JSON.")
    if ext in (".html", ".htm") or re.search(r"<table[\s>]", text[:5000], re.I):
        tables = _read_html(text)
        if tables:
            return tables
    if ext in (".md", ".markdown") or stripped.startswith("|"):
        rows = _read_markdown(text)
        if rows:
            return [("", rows)]
    return [("", _read_delimited(text, ext))]


# --------------------------------------------------------------------------- interpretacja

def _detect_header(row):
    mapping = {}
    for idx, cell in enumerate(row):
        key = _norm(cell)
        for field, aliases in ALIASES.items():
            if key in aliases and field not in mapping:
                mapping[field] = idx
                break
    if "value" in mapping or "label" in mapping:
        return mapping
    return None


def _guess_columns(rows):
    width = max((len(r) for r in rows), default=0)
    order = {1: ("value",), 2: ("label", "value"), 3: ("group", "label", "value"),
             4: ("section", "group", "label", "value")}.get(width, ("set", "section", "group", "label", "value"))
    return {field: idx for idx, field in enumerate(order)}


def _clean_rows(rows):
    out = []
    for r in rows:
        cells = [_cell(c) for c in r]
        while cells and not cells[-1]:
            cells.pop()
        if any(cells):
            out.append(cells)
    return out


def build_dialogues(sheets, name="tabela"):
    warnings = []
    entries = []  # (set, section, group, label, value, order, seq, output)
    nonempty = [(sheet, _clean_rows(rows)) for sheet, rows in sheets]
    nonempty = [(s, r) for s, r in nonempty if r]
    if not nonempty:
        raise TableError("Tabela jest pusta.")
    multi = len(nonempty) > 1

    seq = 0
    for sheet_name, rows in nonempty:
        mapping = _detect_header(rows[0])
        if mapping:
            rows = rows[1:]
            if "value" not in mapping:
                mapping["value"] = mapping["label"]
        else:
            mapping = _guess_columns(rows)
            if len(nonempty) == 1 or sheet_name == nonempty[0][0]:
                warnings.append("Brak rozpoznanego nagłówka - kolumny zgadnięte po ich liczbie (%s)."
                                % ", ".join(f for f in FIELDS if f in mapping))

        def get(row, field):
            idx = mapping.get(field)
            return row[idx] if idx is not None and idx < len(row) else ""

        for row in rows:
            value, label = get(row, "value"), get(row, "label")
            if not value and not label:
                continue
            section = get(row, "section") or (sheet_name if multi and sheet_name else "")
            try:
                order = float(get(row, "order").replace(",", ".")) if get(row, "order") else None
            except ValueError:
                order = None
            seq += 1
            entries.append((get(row, "set").lower() or "default", section or "Kwestie",
                            get(row, "group"), label or value, value or label, order, seq,
                            normalize_output(get(row, "output"))))

    if not entries:
        raise TableError("Nie znaleziono żadnych kwestii w tabeli.")

    sections, items_by_key = {}, {}
    for set_name, section, group, label, value, order, s, output in entries:
        sec = sections.get(section)
        if sec is None:
            sec = sections[section] = {
                "key": section,
                "title": SECTION_TITLES.get(section.lower(), section),
                "pinned": _norm(section) in PINNED_SECTIONS,
                "groups": {},
                "seq": s,
            }
        grp = sec["groups"].setdefault(group, {"name": group, "items": [], "seq": s})
        key = (section, group, label)
        item = items_by_key.get(key)
        if item is None:
            item = items_by_key[key] = {
                "id": hashlib.sha1("\x1f".join(key).encode("utf-8")).hexdigest()[:12],
                "label": label, "values": {}, "order": order, "seq": s, "output": output,
            }
            grp["items"].append(item)
        else:
            if item["order"] is None:
                item["order"] = order
            item["output"] = item["output"] or output
        if set_name in item["values"] and item["values"][set_name] != value:
            warnings.append("Powtórzona etykieta „%s” (%s / %s) - użyto pierwszej wersji." % (label, section, group or "-"))
            continue
        item["values"][set_name] = value

    def sort_key(x):
        return (x["order"] if x["order"] is not None else float("inf"), x["seq"])

    out_sections = []
    for sec in sorted(sections.values(), key=lambda x: x["seq"]):
        groups = []
        for grp in sorted(sec["groups"].values(), key=lambda x: x["seq"]):
            items = sorted(grp["items"], key=sort_key)
            for it in items:
                it.pop("seq", None)
                it.pop("order", None)
            groups.append({"name": grp["name"], "items": items})
        out_sections.append({"key": sec["key"], "title": sec["title"], "pinned": sec["pinned"], "groups": groups})

    sets = list(dict.fromkeys(e[0] for e in entries))  # kolejność jak w pliku
    if "default" in sets and len(sets) > 1:
        sets.remove("default")  # "default" to wartości wspólne dla każdego zestawu

    return {"name": name, "sets": sets, "sections": out_sections,
            "count": len(items_by_key), "warnings": warnings[:20]}


def load_table(data, filename="wklejone"):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return build_dialogues(read_raw(data, filename), name=os.path.basename(filename))
