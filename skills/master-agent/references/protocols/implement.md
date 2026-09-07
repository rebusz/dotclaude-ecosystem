# IMPLEMENT v2

## Prompt

Zastosuj wspólny kontrakt. Wykonaj uzgodniony plan przez aktualnie dozwolony
układ autora, lokalnego wykonawcy i niezależnego recenzenta. Rola IMPLEMENT
nie wybiera nowego dostawcy ani nie daje lokalnemu koordynatorowi prawa do
przejęcia autorstwa po awarii CDP.

1. **Przyjmij kontrakt wykonania.** Odczytaj bieżący plan, DoD slice, risk
   class, zakres GO, write-set, zależności i stan dispatchu. Zweryfikuj aktualne
   branch/HEAD oraz własność worktree. Nie zaczynaj zapisu przed spełnieniem
   wymaganej bramki. Już ważne GO obejmuje uzgodnione poprawki, review i landing;
   nie proś o nie ponownie z powodu kolejnego commitu.
2. **Sprawdź punkt wyjścia.** Przeczytaj zmieniane symbole i rzeczywistych
   callerów. Dla błędu wykorzystaj istniejące repro; dla zmiany zachowania
   wskaż test wejście → wynik. Znane błędy bazowe zapisz jako błędy bazowe,
   nie PASS. Nie produkuj testu dla banalnej zmiany dokumentacji tylko po to,
   by odhaczyć etap. Zachowaj wszystkie wymagane bramki repozytorium.
3. **Wykonuj kompletne slice.** Przekaż zatwierdzonemu autorowi spójny materiał:
   potrzebne pełne pliki, interfejsy, ograniczenia i kryteria akceptacji.
   Lokalny wykonawca stosuje zwrócony patch i sprawdza faktyczny diff.
   Mechaniczne nałożenie kodu i samodzielna zmiana jego zachowania to różne
   rodzaje autorstwa, które muszą być odnotowane. Nie naprawiaj przy okazji
   sąsiedniego kodu. Gdy zależność rozszerza zakres, przygotuj konkretną zmianę
   planu zamiast ukrywać rozszerzenie.
4. **Zweryfikuj zachowanie.** Uruchom właściwy feedback loop i testy wymagane
   przez plan. Test ma przejść rzeczywistą gałąź skutku, awarii i odzyskania,
   jeśli to własności zadania. Persistence/restart wymaga round-trip przez
   produkcyjny mechanizm, nie gotowej fixture stanu po restarcie. Zapisz komendę,
   kod wyjścia, cel, wersję i artefakt. Timeout, skip krytycznego celu i
   przerwany suite pozostają brakiem wyniku. Szerzej testuj tylko z nowego
   powodu albo zgodnie z wymaganą bramką. Heavy work korzysta z istniejącego
   protokołu Conductor.
5. **Przekaż do review i zamknij cykl.** Commituj wyłącznie własne pliki,
   opublikuj exact head i przygotuj pakiet dla niezależnego recenzenta.
   Po ship blockerze popraw zakresowe błędy, ponownie zweryfikuj i zrecenzuj
   nową rewizję. Następnie właściciel `/fwf`/`/fwp` prowadzi Ready, CI, merge
   i bezpieczną synchronizację faktycznej gałęzi domyślnej. Worker nie przejmuje
   automatycznie uprawnień koordynatora.

Zachowaj jeden execution path paper/live, obowiązujące granice advisory i
oddzielne GO dla real-money/Combine trigger, deploymentu oraz destrukcji.
Nie zastępuj brakującego dowodu ustawieniem flagi, mockiem omijającym skutek
lub zamianą gate na ostrzeżenie. Przy niepewnym submit zachowaj receipt i
zatrzymaj automatyczne resubmission/fallback zgodnie z aktywną polityką.

Wynik: zmienione zachowanie, walidacja, autor/applier/reviewer z dowodów,
branch/PR/SHA i pozostały gate. Wykonaj hooks planu i EPILOG_PAYLOAD.
Emituj `>> DONE` dopiero po ukończeniu zleconego etapu/cyklu; lokalny test
nie oznacza zakończonego review, merge ani aktywacji.
