# NAO WoZ – panel mowy w przeglądarce

Wersja przeglądarkowa `pepper-WoZ-UI-demo`, tylko do mówienia. Kliknięcie przycisku od razu wysyła kwestię do robota.
Nie ma tu pola do zatwierdzania ani Entera.

## Start

```bash
./start.sh                    # otwiera http://localhost:8080 (sam tworzy .venv z paramiko)
./start.sh --demo             # symulowany robot, do testów bez NAO
```

**Połącz** wysyła przez SSH (nao/nao) plik `robot/nao_speech_service.py` do katalogu domowego robota i go uruchamia.
Robot łączy się wtedy zwrotnie z PC na port TCP **54331** (zapora musi go przepuszczać).
Środowisko Pythona na robocie jest ustawione tak samo jak w pepper-WoZ-UI-demo.
Jeśli zaznaczysz „ręcznie”, panel tylko czeka, a ty uruchamiasz skrypt na robocie sam (komenda pojawi się w pasku statusu).
Log usługi na robocie: `/tmp/nao_speech.log`.

Przydatne opcje: `--bind 0.0.0.0` (panel dostępny z innych komputerów w sieci), `--table plik.xlsx`,
`--remote-python python --no-remote-env` (wbudowany Python na starszym NAOqi), `--ssh-user/--ssh-password`.

## Obsługa

- klik w kwestię: wybrane wyjście (🤖 **Robot** albo 🔊 **Głośnik**) od razu odtwarza przypisany plik audio z folderu `nagrania/`, a przycisk zostaje oznaczony na żółto jako użyty. Kolejne kliknięcia trafiają do kolejki.
- **STOP** albo **Esc**: przerywa odtwarzanie i czyści kolejkę.
- przełączniki w panelu: wyjście (robot/głośnik), zestaw (np. uprzejmy/rozkazujący), głośność robota, „gesty” (gestykulacja NAO w trakcie odtwarzania pliku audio przez `ALAnimationPlayer`).
- syntezator TTS robota jest całkowicie wyłączony — zarówno z głośnika komputera, jak i z głośnika NAO odtwarzane są wyłącznie dostarczone nagrania audio.

## Gdzie wrzucać nagrania (`nagrania/`)

Dostarczone pliki (obsługiwane formaty: **`.wav`, `.mp3`, `.mp4`, `.m4a`, `.ogg`, `.flac`, `.aac`, `.webm`, `.wma`**, w tym podwójne rozszerzenia typu **`.m4a.mp4`**) wrzuć do folderu **`nagrania/`** (bezpośrednio albo do podfolderów `nagrania/uprzejmy/` i `nagrania/rozkazujący/`).

### Numeracja plików (od 1 do 18):
Każdy przycisk w panelu ma swój numer **`#1` .. `#18`** (widoczny w prawym górnym rogu przycisku).
Rozpoznawane są wszystkie poniższe konwencje nazewnictwa (wielkość liter i polskie znaki bez znaczenia):
- **Z nazwą zestawu i numerem** (mogą leżeć bezpośrednio w `nagrania/` albo w `nagrania/uprzejmy/` i `nagrania/rozkazujący/`):
  - `Uprzejmy1.m4a.mp4` .. `Uprzejmy18.m4a.mp4` (lub `.mp4`, `.m4a`, `.wav`, `.mp3`)
  - `Rozkazujacy1.m4a.mp4` .. `Rozkazujacy18.m4a.mp4` (lub `Rozkazujący1...`, `rozkazujacy_1...`)
- **Same numery w podfolderach zestawów**:
  - `nagrania/uprzejmy/1.mp4` .. `18.mp4` (lub `01.mp4` .. `18.mp4`)
  - `nagrania/rozkazujący/1.mp4` .. `18.mp4`
- **Po etykiecie przycisku** (np. `Powitanie.wav`) albo przez przeciągnięcie pliku myszką bezpośrednio na przycisk w przeglądarce.

| Nr (`#`) | Przycisk w panelu | Zestaw `uprzejmy` (przykład) | Zestaw `rozkazujący` (przykład) |
|---|---|---|---|
| **#1** | Powitanie | `Uprzejmy1.m4a.mp4` (lub `1.mp4`) | `Rozkazujacy1.m4a.mp4` (lub `1.mp4`) |
| **#2** | Zasady | `Uprzejmy2.m4a.mp4` | `Rozkazujacy2.m4a.mp4` |
| **#3** | Wybierz kartę | `Uprzejmy3.m4a.mp4` | `Rozkazujacy3.m4a.mp4` |
| **#4** | Osiem pytań – zasady | `Uprzejmy4.m4a.mp4` | `Rozkazujacy4.m4a.mp4` |
| **#5** | Zaczynamy | `Uprzejmy5.m4a.mp4` | `Rozkazujacy5.m4a.mp4` |
| **#6** | 1. Owoc? | `Uprzejmy6.m4a.mp4` | `Rozkazujacy6.m4a.mp4` |
| **#7** | 2. Skórka? | `Uprzejmy7.m4a.mp4` | `Rozkazujacy7.m4a.mp4` |
| **#8** | 3. Rośnie na drzewie? | `Uprzejmy8.m4a.mp4` | `Rozkazujacy8.m4a.mp4` |
| **#9** | 4. Żółty kolor? | `Uprzejmy9.m4a.mp4` | `Rozkazujacy9.m4a.mp4` |
| **#10** | 5. Zmieści się w dłoni? | `Uprzejmy10.m4a.mp4` | `Rozkazujacy10.m4a.mp4` |
| **#11** | 6. Wycisnąć sok? | `Uprzejmy11.m4a.mp4` | `Rozkazujacy11.m4a.mp4` |
| **#12** | 7. Większe od piłki? | `Uprzejmy12.m4a.mp4` | `Rozkazujacy12.m4a.mp4` |
| **#13** | 8. Pomarańcza? | `Uprzejmy13.m4a.mp4` | `Rozkazujacy13.m4a.mp4` |
| **#14** | Koniec gry | `Uprzejmy14.m4a.mp4` | `Rozkazujacy14.m4a.mp4` |
| **#15** | Po odpowiedzi | `Uprzejmy15.m4a.mp4` | `Rozkazujacy15.m4a.mp4` |
| **#16** | S1 · brak odpowiedzi | `Uprzejmy16.m4a.mp4` | `Rozkazujacy16.m4a.mp4` |
| **#17** | S2 · nie „tak”/„nie” | `Uprzejmy17.m4a.mp4` | `Rozkazujacy17.m4a.mp4` |
| **#18** | S3 · pytanie poza grą | `Uprzejmy18.m4a.mp4` | `Rozkazujacy18.m4a.mp4` |

> **Wskaźniki w panelu:**
> - Licznik `Nagrania (nagrania/uprzejmy/): 18/18` na pasku tabeli pokazuje, ile kwestii z wybranego zestawu ma dopasowany plik audio.
> - Zielona nutka **♪** na przycisku oznacza, że plik nagrania został znaleziony (najechanie myszką pokazuje ścieżkę pliku).
> - Czerwony znak **⚠** i przerywana ramka oznaczają brak pliku audio dla tej kwestii.
> - Dla wyjścia **🤖 Robot** pliki inne niż `.wav` (np. `.mp3`) są przed wysłaniem automatycznie konwertowane przez `ffmpeg` do formatu WAV (16-bit PCM, 22050 Hz) i zapamiętywane w `nagrania/.robot_wav/`.

## Tabele z kwestiami

`dialogi/transfer_stylu_faza1.tsv` zawiera kwestie AGENTA z procedury „Transfer stylu komunikacyjnego” (Faza 1),
w zestawach **uprzejmy** i **rozkazujący**: instrukcję, 8 pytań i zakończenie. W panelu bocznym są reakcje
„po odpowiedzi” oraz sytuacje niestandardowe S1–S3. Kwestii B1 i B3 tu nie ma, bo wypowiadają je ludzie.
Panel pamięta ostatnio wczytaną tabelę z folderu `dialogi/`.



Pliki z folderu `dialogi/` są na liście w panelu. Inną tabelę możesz wczytać na trzy sposoby: „Wczytaj plik…”,
przeciągając plik na okno albo przez „Wklej tabelę…” (komórki skopiowane prosto z Excela, LibreOffice lub Google Sheets).

Obsługiwane formaty: **TSV, CSV (`,` `;` `|`), TXT, XLSX, ODS, XLS** (wymaga `xlrd`), **Markdown, HTML, JSON**.
W skoroszytach z kilkoma arkuszami każdy arkusz bez kolumny `section` staje się osobną zakładką.

Kolumny (nagłówki po polsku lub angielsku, wielkość liter bez znaczenia):

| kolumna | aliasy                           | znaczenie                                                          |
|---------|----------------------------------|--------------------------------------------------------------------|
| set     | zestaw, wariant, warunek         | przełącznik zestawów w nagłówku                                    |
| section | sekcja, zakładka, etap           | zakładki; `right` / `szybkie` / `boczne` trafia do panelu bocznego |
| group   | grupa, kategoria, temat          | podzakładki (w panelu bocznym: nagłówki)                           |
| label   | etykieta, przycisk, nazwa        | napis na przycisku                                                 |
| value   | tekst, kwestia, wypowiedź, treść | to, co robot mówi                                                  |
| order   | kolejność, nr, lp                | opcjonalna kolejność                                               |

Bez nagłówka kolumny są przypisywane po ich liczbie: 1 = tekst, 2 = etykieta + tekst, 3 = grupa + etykieta + tekst,
4 = sekcja + grupa + etykieta + tekst, 5 = zestaw + sekcja + grupa + etykieta + tekst.
Szablon TSV z pepper-WoZ działa bez zmian (`dialogi/badanie_dylematy.tsv`).
