"use strict";

const $ = (id) => document.getElementById(id);
const store = {
  get: (k, d) => { try { const v = localStorage.getItem("nao:" + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set: (k, v) => localStorage.setItem("nao:" + k, JSON.stringify(v)),
};

const state = {
  table: null,
  source: null,
  files: [],
  set: store.get("set", null),
  output: store.get("output", "robot"),
  recorded: new Set(),      // "idPrzycisku|zestaw" z nagraniem MP3
  recVersion: null,
  section: store.get("section", null),
  groupBySection: store.get("groups", {}),
  used: new Set(),
  jobItem: new Map(),      // id wypowiedzi -> id przycisku
  status: { status: "disconnected", history: [] },
  lastClick: new Map(),
};

// ------------------------------------------------------------------ API
async function api(path, body, raw) {
  const opts = body === undefined ? {} : {
    method: "POST",
    body: raw ? body : JSON.stringify(body),
    headers: raw ? {} : { "Content-Type": "application/json" },
  };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ ok: false, error: "Błędna odpowiedź serwera" }));
  if (!res.ok || data.ok === false) throw new Error(data.error || res.statusText);
  return data;
}

let toastTimer;
function toast(msg, isErr) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), isErr ? 5000 : 2200);
}

// ------------------------------------------------------------------ tabela
function usedKey() { return "used:" + (state.table?.name || "") + ":" + (state.set || ""); }
function loadUsed() { state.used = new Set(store.get(usedKey(), [])); }
function saveUsed() { store.set(usedKey(), [...state.used]); }

function setTable(table, source) {
  state.table = table;
  if (source !== undefined) state.source = source;
  if (!table) { render(); return; }
  if (!table.sets.includes(state.set)) state.set = table.sets[0];
  const main = table.sections.filter((s) => !s.pinned);
  if (!main.some((s) => s.key === state.section)) state.section = main[0]?.key ?? null;
  loadUsed();
  render();
  refreshRecorded();
}

async function refreshRecorded() {
  try {
    const r = await api("/api/recordings");
    state.recorded = new Set(r.have);
    state.recFolder = r.folder;
    paintLines();
    renderRecInfo();
  } catch { /* serwer niedostępny - poll pokaże błąd */ }
}

function valueKey(item) {
  return state.set in item.values ? state.set : "default" in item.values ? "default" : Object.keys(item.values)[0];
}

function outputFor(item) { return (item && item.output) || state.output; }

function renderOutput() {
  document.querySelectorAll("#outputs button").forEach((b) => b.classList.toggle("on", b.dataset.out === state.output));
  document.body.classList.toggle("out-speaker", state.output === "speaker");
}

function renderRecInfo() {
  const el = $("recInfo"), btn = $("recordBtn");
  const b = state.status.bulk;
  const rr = state.status.pitch?.rendering;
  if (rr && rr.running) { el.innerHTML = `przeliczam MP3 <b>${rr.done}/${rr.total}</b>`; return; }
  if (b && b.running) {
    el.innerHTML = `nagrywam <b>${b.done}/${b.total}</b>`;
    btn.textContent = "✕ Przerwij nagrywanie";
    return;
  }
  btn.textContent = "⏺ Nagraj MP3";
  const t = state.table;
  if (!t) { el.textContent = ""; return; }
  let total = 0, have = 0;
  for (const s of t.sections) for (const g of s.groups) for (const it of g.items) {
    if (!visible(it)) continue;
    total++;
    if (state.recorded.has(it.id + "|" + valueKey(it))) have++;
  }
  const lang = state.status.rec_language ? ` (${state.status.rec_language})` : "";
  el.innerHTML = `MP3${lang}: <b>${have}/${total}</b>`;
  if (b && !b.running && b.errors?.length) el.title = b.errors.join("\n"); else el.title = "";
}

function textFor(item) {
  const v = item.values;
  return v[state.set] ?? v.default ?? Object.values(v)[0] ?? item.label;
}

function visible(item) {
  const v = item.values;
  return state.table.sets.length <= 1 || state.set in v || "default" in v;
}

function render() {
  const t = state.table;
  $("tableName").textContent = t ? `${t.name} · ${t.count} kwestii` : "brak tabeli";

  // pliki z folderu dialogi/
  const fs = $("fileSelect");
  fs.innerHTML = "";
  const placeholder = new Option(state.files.length ? "— pliki w dialogi/ —" : "(folder dialogi/ pusty)", "");
  fs.add(placeholder);
  for (const f of state.files) fs.add(new Option(f, f, false, f === state.source));
  if (!state.source) fs.value = "";

  // ostrzeżenia
  const w = $("warnings");
  w.hidden = !t?.warnings?.length;
  if (t?.warnings?.length) w.innerHTML = "<ul>" + t.warnings.map((x) => `<li>${esc(x)}</li>`).join("") + "</ul>";

  // zestawy
  const sets = t?.sets || [];
  $("setField").hidden = sets.length <= 1;
  $("sets").innerHTML = "";
  for (const s of sets) {
    const b = document.createElement("button");
    b.textContent = s;
    b.className = s === state.set ? "on" : "";
    b.onclick = () => { state.set = s; store.set("set", s); loadUsed(); render(); };
    $("sets").append(b);
  }

  // zakładki
  const tabs = $("tabs"), groups = $("groups"), grid = $("grid");
  tabs.innerHTML = groups.innerHTML = grid.innerHTML = "";
  const main = t ? t.sections.filter((s) => !s.pinned) : [];
  if (main.length > 1) {
    for (const s of main) {
      const b = document.createElement("button");
      b.className = "tab" + (s.key === state.section ? " on" : "");
      b.textContent = s.title;
      b.onclick = () => { state.section = s.key; store.set("section", s.key); render(); };
      tabs.append(b);
    }
  }

  const sec = main.find((s) => s.key === state.section);
  if (!t) {
    grid.innerHTML = `<div class="empty">Wczytaj tabelę z kwestiami: przycisk „Wczytaj plik…”, „Wklej tabelę…”
      albo przeciągnij plik na okno. Pliki z folderu <code>dialogi/</code> są na liście obok.</div>`;
  } else if (sec) {
    const gs = sec.groups.filter((g) => g.items.some(visible));
    let gi = Math.min(state.groupBySection[sec.key] ?? 0, Math.max(0, gs.length - 1));
    const totalVisible = gs.reduce((n, g) => n + g.items.filter(visible).length, 0);
    if (gs.length > 1 && totalVisible <= 30) {
      // mało kwestii: wszystkie grupy naraz, jedna pod drugą (np. instrukcja -> pytania -> koniec)
      for (const g of gs) {
        if (g.name) grid.insertAdjacentHTML("beforeend", `<div class="group-head">${esc(g.name)}</div>`);
        g.items.filter(visible).forEach((it) => grid.append(lineButton(it)));
      }
    } else if (gs.length > 1) {
      gs.forEach((g, i) => {
        const b = document.createElement("button");
        b.className = "chip" + (i === gi ? " on" : "");
        const done = g.items.filter((it) => visible(it) && state.used.has(it.id)).length;
        const total = g.items.filter(visible).length;
        b.innerHTML = `${esc(g.name || "ogólne")}<span class="count">${done}/${total}</span>`;
        b.onclick = () => { state.groupBySection[sec.key] = i; store.set("groups", state.groupBySection); render(); };
        groups.append(b);
      });
    }
    if (!(gs.length > 1 && totalVisible <= 30)) {
      const g = gs[gi];
      if (g) g.items.filter(visible).forEach((it) => grid.append(lineButton(it)));
      else grid.innerHTML = `<div class="empty">Brak kwestii w tym zestawie.</div>`;
    }
  } else if (!t.sections.some((s) => s.pinned)) {
    grid.innerHTML = `<div class="empty">Brak kwestii.</div>`;
  }

  // panel boczny (sekcje "right" itp.)
  const pinned = $("pinned");
  pinned.innerHTML = "";
  const pins = t ? t.sections.filter((s) => s.pinned) : [];
  for (const s of pins) {
    if (pins.length > 1) pinned.insertAdjacentHTML("beforeend", `<h2>${esc(s.title)}</h2>`);
    for (const g of s.groups) {
      const items = g.items.filter(visible);
      if (!items.length) continue;
      if (g.name) pinned.insertAdjacentHTML("beforeend", `<h3>${esc(g.name.replace(/_/g, " "))}</h3>`);
      const stack = document.createElement("div");
      stack.className = "stack";
      items.forEach((it) => stack.append(lineButton(it)));
      pinned.append(stack);
    }
  }
  paintLines();
  renderRecInfo();
}

function lineButton(item) {
  const b = document.createElement("button");
  b.className = "line";
  b.dataset.id = item.id;
  const text = textFor(item);
  b.title = text;
  b.dataset.rec = item.id + "|" + valueKey(item);
  const fixed = item.output === "speaker" ? `<span class="badge" title="zawsze z głośnika (narrator)">🔊</span>`
    : item.output === "robot" ? `<span class="badge" title="zawsze przez robota">🤖</span>` : "";
  b.innerHTML = `<span class="badges">${fixed}<span class="badge mp3" title="jest nagranie MP3">♪</span></span>` +
    `<span class="lbl">${esc(item.label)}</span>` +
    (text.trim() !== item.label.trim() ? `<span class="txt">${esc(text)}</span>` : "");
  b.onclick = () => speakItem(item);
  return b;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ------------------------------------------------------------------ mowa
async function say(text, label, output) {
  const r = await api("/api/say", { text, label, output: output || state.output, animated: $("animated").checked });
  return r.id;
}

async function speakItem(item) {
  const now = Date.now();
  if (now - (state.lastClick.get(item.id) || 0) < 800) return; // ochrona przed podwójnym kliknięciem
  state.lastClick.set(item.id, now);
  try {
    const id = await say(textFor(item), item.label, outputFor(item));
    state.jobItem.set(id, item.id);
    state.used.add(item.id);
    saveUsed();
    paintLines();
  } catch (e) {
    toast(e.message, true);
  }
}

function paintLines() {
  const byItem = new Map();
  for (const h of state.status.history || []) {
    const itemId = state.jobItem.get(h.id);
    if (itemId && ["speaking", "queued", "recording"].includes(h.status)) byItem.set(itemId, h.status);
  }
  document.querySelectorAll(".line").forEach((el) => {
    const st = byItem.get(el.dataset.id);
    el.classList.toggle("used", state.used.has(el.dataset.id));
    el.classList.toggle("speaking", st === "speaking");
    el.classList.toggle("queued", st === "queued");
    el.classList.toggle("recording", st === "recording");
    const hasMp3 = state.recorded.has(el.dataset.rec);
    el.classList.toggle("has-mp3", hasMp3);
    const badge = el.querySelector(".badge.mp3");
    if (badge) badge.hidden = !hasMp3;
  });
}

// ------------------------------------------------------------------ status robota
function renderStatus(s) {
  state.status = s;
  const st = s.status;
  $("dot").className = "dot " + st;
  document.body.classList.toggle("offline", st !== "connected");
  const cb = $("connectBtn");
  cb.textContent = st === "connected" ? "Rozłącz" : st === "connecting" ? "Anuluj" : "Połącz";
  cb.className = "btn" + (st === "disconnected" ? " primary" : "");

  const line = $("statusLine");
  line.textContent = s.error ? "⚠ " + s.error : st === "connected" ? "" : s.message || (s.demo ? "Tryb DEMO — robot symulowany." : "");
  line.className = "status-line" + (s.error ? " err" : "");

  const online = st === "connected";
  const lang = $("lang");
  lang.disabled = !online || !s.languages.length;
  const sig = s.languages.join("|");
  if (lang.dataset.sig !== sig) {
    lang.dataset.sig = sig;
    lang.innerHTML = "";
    if (!s.languages.length) lang.add(new Option("—", ""));
    for (const l of s.languages) lang.add(new Option(l, l));
  }
  if (document.activeElement !== lang && s.language) lang.value = s.language;

  const vol = $("vol");
  vol.disabled = !online || s.volume == null;
  if (!vol.matches(":active") && s.volume != null) { vol.value = s.volume; $("volVal").textContent = s.volume; }

  renderPitch(s.pitch, s.live_pitch);

  const now = $("now");
  now.classList.toggle("active", !!s.speaking);
  now.classList.toggle("spk", s.speaking?.output === "speaker");
  const rec = s.history.find((h) => h.status === "recording");
  $("nowText").textContent = s.speaking ? s.speaking.text : rec ? "nagrywam głos NAO: " + rec.text : "—";
  document.querySelector(".now-tag").textContent =
    s.speaking ? (s.speaking.output === "speaker" ? "głośnik" : "robot") : rec ? "nagrywa" : "mówi";
  const q = s.history.filter((h) => h.status === "queued").length;
  $("queueInfo").textContent = q ? `w kolejce: ${q}` : "";
  if (s.rec_version !== state.recVersion || s.rec_language !== state.recLanguage) {
    state.recVersion = s.rec_version; state.recLanguage = s.rec_language;
    refreshRecorded();
  }
  renderRecInfo();

  const hist = $("history");
  const sigH = s.history.map((h) => h.id + h.status).join(",");
  if (!state.seenErrors) state.seenErrors = new Set(s.history.filter((h) => h.status === "error").map((h) => h.id));
  for (const h of s.history) {
    if (h.status === "error" && !state.seenErrors.has(h.id)) { state.seenErrors.add(h.id); if (h.error) toast(h.error, true); }
  }
  if (hist.dataset.sig !== sigH) {
    hist.dataset.sig = sigH;
    hist.innerHTML = "";
    for (const h of [...s.history].reverse()) {
      const li = document.createElement("li");
      li.className = h.status;
      const icon = h.output === "speaker" ? "🔊" : "🤖";
      li.innerHTML = `<span class="t">${h.t}</span><span class="x" title="${esc(h.error || "Kliknij, by wstawić do pola tekstowego")}"><span class="o">${icon}</span>${esc(h.text)}</span>`;
      li.querySelector(".x").onclick = () => { $("freeText").value = h.text; $("freeText").focus(); };
      hist.append(li);
    }
  }
  paintLines();
}

function renderPitch(p, live) {
  if (!p) return;
  const el = $("pitch");
  el.min = p.min; el.max = p.max;
  const busy = el.matches(":active") || document.activeElement === el;
  if (!busy) { el.value = p.value; showPitch(p.value, p); }
  $("pitchReset").disabled = !p.manual;
  $("pitchField").title = (live ? "" : "UWAGA: odtwarzacz nie zmienia wysokości na żywo - działa po przeliczeniu MP3. ") +
    `Wysokość głosu na głośniku. Robot mówi z pitchShift ${p.robot}.`;
}

function showPitch(v, p) {
  const tag = p && !p.manual ? " <small>(jak robot)</small>" : "";
  $("pitchVal").innerHTML = (+v).toFixed(2) + "×" + tag;
}

async function poll() {
  try {
    renderStatus(await api("/api/status"));
  } catch {
    $("statusLine").textContent = "⚠ Brak połączenia z serwerem panelu (server.py).";
    $("statusLine").className = "status-line err";
    $("dot").className = "dot";
  }
  setTimeout(poll, 400);
}

// ------------------------------------------------------------------ wczytywanie tabel
async function refreshTable() {
  const d = await api("/api/dialogues");
  state.files = d.files;
  setTable(d.table, d.source);
}

async function uploadFile(file) {
  try {
    const d = await api("/api/dialogues/upload?name=" + encodeURIComponent(file.name), file, true);
    setTable(d.table, null);
    toast(`Wczytano „${file.name}”: ${d.table.count} kwestii`);
  } catch (e) { toast(e.message, true); }
}

async function loadServerFile(name) {
  if (!name) return;
  try {
    const d = await api("/api/dialogues/file", { name });
    setTable(d.table, d.source);
    toast(`Wczytano „${name}”: ${d.table.count} kwestii`);
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------------ zdarzenia
function bind() {
  $("host").value = store.get("host", "nao.local");
  $("manual").checked = store.get("manual", false);
  $("animated").checked = store.get("animated", true);
  $("host").onchange = () => store.set("host", $("host").value.trim());
  $("manual").onchange = () => store.set("manual", $("manual").checked);
  $("animated").onchange = () => store.set("animated", $("animated").checked);

  document.querySelectorAll("#outputs button").forEach((b) => {
    b.onclick = () => { state.output = b.dataset.out; store.set("output", state.output); renderOutput(); };
  });
  renderOutput();

  $("recordBtn").onclick = async (e) => {
    try {
      if (state.status.bulk?.running) { await api("/api/record_all/cancel", {}); return; }
      const force = e.shiftKey;
      if (force && !confirm("Nagrać od nowa WSZYSTKIE kwestie (nadpisze istniejące MP3)?")) return;
      await api("/api/record_all", { force });
      toast("Nagrywanie głosem NAO… pliki trafiają do folderu nagrania/");
    } catch (err) { toast(err.message, true); }
  };

  $("connectBtn").onclick = async () => {
    try {
      if (state.status.status === "disconnected") {
        await api("/api/connect", { host: $("host").value.trim(), manual: $("manual").checked });
      } else {
        await api("/api/disconnect", {});
      }
    } catch (e) { toast(e.message, true); }
  };

  const stop = async () => { try { await api("/api/stop", {}); } catch (e) { toast(e.message, true); } };
  $("stopBtn").onclick = stop;
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("pasteDialog").open) { e.preventDefault(); stop(); }
  });

  $("lang").onchange = async (e) => {
    try { await api("/api/language", { value: e.target.value }); } catch (err) { toast(err.message, true); }
  };
  $("vol").oninput = (e) => ($("volVal").textContent = e.target.value);
  $("vol").onchange = async (e) => {
    try { await api("/api/volume", { value: +e.target.value }); } catch (err) { toast(err.message, true); }
  };

  $("pitch").oninput = (e) => showPitch(e.target.value, { manual: true });
  $("pitch").onchange = async (e) => {
    try { await api("/api/pitch", { value: +e.target.value }); } catch (err) { toast(err.message, true); }
    e.target.blur();
  };
  $("pitchReset").onclick = async () => {
    try { await api("/api/pitch", { value: null }); } catch (err) { toast(err.message, true); }
  };

  $("freeSay").onclick = async () => {
    const text = $("freeText").value.trim();
    if (!text) return;
    try { await say(text, ""); $("freeText").value = ""; } catch (e) { toast(e.message, true); }
  };

  $("fileSelect").onchange = (e) => loadServerFile(e.target.value);
  $("reloadBtn").onclick = async () => {
    if (state.source) return loadServerFile(state.source);
    try { await refreshTable(); toast("Odświeżono listę plików"); } catch (e) { toast(e.message, true); }
  };
  $("fileInput").onchange = (e) => { if (e.target.files[0]) uploadFile(e.target.files[0]); e.target.value = ""; };

  $("pasteBtn").onclick = () => { $("pasteText").value = ""; $("pasteDialog").showModal(); $("pasteText").focus(); };
  $("pasteText").addEventListener("keydown", (e) => {
    if (e.key === "Tab") { // pozwól wpisać tabulator ręcznie
      e.preventDefault();
      const ta = e.target, p = ta.selectionStart;
      ta.value = ta.value.slice(0, p) + "\t" + ta.value.slice(ta.selectionEnd);
      ta.selectionStart = ta.selectionEnd = p + 1;
    }
  });
  $("pasteText").addEventListener("paste", (e) => {
    // Arkusze wklejają też HTML - zachowaj go, jeśli zwykły tekst nie ma tabulatorów (np. tabela ze strony WWW).
    const html = e.clipboardData.getData("text/html");
    const plain = e.clipboardData.getData("text/plain");
    if (html && /<table/i.test(html) && !plain.includes("\t")) { e.preventDefault(); e.target.value = html; }
  });
  $("pasteDialog").addEventListener("close", async () => {
    if ($("pasteDialog").returnValue !== "ok") return;
    const text = $("pasteText").value;
    if (!text.trim()) return;
    try {
      const d = await api("/api/dialogues/paste", { text });
      setTable(d.table, null);
      toast(`Wczytano wklejoną tabelę: ${d.table.count} kwestii`);
    } catch (e) { toast(e.message, true); }
  });

  $("resetUsedBtn").onclick = () => {
    if (!state.used.size || !confirm("Usunąć oznaczenia użytych kwestii dla tego zestawu?")) return;
    state.used.clear(); saveUsed(); render();
  };

  // przeciągnij i upuść
  let depth = 0;
  window.addEventListener("dragenter", (e) => { if (e.dataTransfer.types.includes("Files")) { depth++; $("drop").hidden = false; } });
  window.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; $("drop").hidden = true; } });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => {
    e.preventDefault(); depth = 0; $("drop").hidden = true;
    const f = e.dataTransfer.files[0];
    if (f) uploadFile(f);
  });
}

bind();
refreshTable().catch((e) => toast(e.message, true));
poll();
