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

- klik w kwestię: robot mówi od razu, a przycisk zostaje oznaczony na żółto jako użyty. Kolejne kliknięcia trafiają do kolejki.
- **STOP** albo **Esc**: przerywa mowę i czyści kolejkę.
- przełączniki w panelu: wyjście (robot/głośnik), zestaw (np. uprzejmy/rozkazujący), język TTS, głośność, „gesty” (ALAnimatedSpeech albo zwykły TTS).
- pole „Własna kwestia” wysyła wpisany tekst tylko przyciskiem. Kliknięcie wpisu w historii wstawia go do tego pola.

## Robot albo głośnik (narrator)

Przełącznik **Wyjście** w nagłówku decyduje, kto mówi:

- **🤖 Robot**: NAO mówi sam, jak dotąd. To warunki 1–2 („robot humanoidalny”).
- **🔊 Głośnik**: ten sam głos NAO, ale z głośnika komputera. To warunki 3–4 („asystent głosowy”).
  Robot syntetyzuje kwestię do pliku (`ALTextToSpeech.sayToFile`), PC konwertuje ją do MP3 (ffmpeg),
  zapisuje w `nagrania/<Język>/` i odtwarza (ffplay/mpv).

**⏺ Nagraj MP3** nagrywa głosem NAO wszystkie kwestie z tabeli (pomija te, które już są; Shift+klik nagrywa wszystko od nowa).
Licznik „MP3 (Polish): 17/17” pokazuje, ile kwestii z bieżącego zestawu ma nagranie, a ♪ na przycisku oznacza, że to nagranie istnieje.
Po nagraniu wyjście „Głośnik” działa także **bez podłączonego robota**.
Kwestia bez nagrania nagra się sama przy pierwszym kliknięciu, ale tylko gdy robot jest połączony (trwa to chwilę).
Nagrania są przypisane do języka TTS. Zmiana języka lub głosu oznacza nowe nagrania.
Tryb `--demo` zapisuje swoje nagrania w osobnym folderze `nagrania_demo/`.

**Wysokość głosu (suwak „Wysokość”):** `sayToFile` zapisuje głos bez podwyższenia, które NAO nakłada przy mówieniu
(`pitchShift`, na tym robocie 1.15). Domyślnie panel używa wartości zgłoszonej przez robota („jak robot”).
Suwakiem ustawiasz ją ręcznie, a ↺ wraca do ustawienia robota. Zmiana działa od razu przy odtwarzaniu, bo czyste nagrania leżą
w `nagrania/<Język>/zrodla/`, a pliki MP3 przeliczają się w tle (bez robota).

Kolumna `output` (aliasy: wyjście, mówca, speaker) w tabeli może na stałe przypisać kwestię:
`robot` / `agent` albo `narrator` / `głośnik` / `asystent`. Pusta kolumna oznacza, że decyduje przełącznik w panelu.

> Jeśli `sayToFile` na danym NAOqi zwraca surowe PCM bez nagłówka WAV, panel zakłada 22050 Hz mono.
> Gdy nagranie brzmi za szybko lub za wolno, uruchom serwer z `--raw-rate 16000` (albo inną wartością).

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
