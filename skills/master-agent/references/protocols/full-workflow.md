# /fwf i /fwp — jeden workflow v2

## Prompt

Prowadź jeden pełny cykl dla wskazanego planu. `/fwf` wybiera istniejący koszyk
OpenRouter free, `/fwp` paid. Pozostały panel i obowiązujące trasy autorstwa
pozostają bez zmian. Samo wspomnienie komendy podczas analizy jej tekstu nie
jest uruchomieniem workflow.

**Przyjęcie.** Przyjmij jeden plan zgodnie z publiczną składnią komendy.
Uruchom wymagany plan-context pre-step, sprawdź aktualne repo/HEAD/worktree,
Why/DoD, kolizje planów i risk class. Odczytaj istniejącą zgodę oraz zapis
poprzednich etapów. Nie zeruj prób, receiptu ani decyzji po wznowieniu.
R0 obsłuż dokumentacyjną ścieżką; R1–R3 prowadź przez etapy poniżej.

**1. CEO.** Uruchom rolę [CEO review](ceo-review.md) na tym planie. Rozstrzygaj
pytania według istniejącej polityki R-class; R3 kieruje do operatora materialne
decyzje produktowe/ryzyka. KILL/DEFER kończy zależny cykl. REFRAME aktualizuje
plan, a dopiero ustalony zakres przechodzi dalej.

**2. Audyt i synteza.** Przygotuj zamrożony pakiet planu, aktualnych kontraktów
i dowodów oraz manifest dostępności. Przekaż role [audytu CDP](cdp-plan-audit.md)
i [syntezy](synthesis.md) przez **obecny** jedyny runner `audit/fuse.py`.
Codex przekazuje `--synthesizer gpt`, Claude `--synthesizer claude`; to zapis
pochodzenia, nie selektor panelu. Podstawowa komenda nadal ma postać:

```text
D:/APPS/WatchF/.venv/Scripts/python.exe D:/APPS/_shared/audit/fuse.py --mode free --synthesizer gpt "@<plan>"
```

W `/fwp` zmienia się `free` na `paid`. Nie dopisuj nieobsługiwanych flag.
Wdrożony renderer ma dołączyć kontrakt i rolę v2; dopóki go nie ma, powyższa
komenda używa aktualnych promptów v1. Nie twierdź, że samo istnienie tego pliku
zmieniło runtime.

Zachowaj ChatGPT CDP Sol/Pro z potwierdzonym pre-submit fallback,
Antigravity Gemini 3.7 Flash z istniejącym fallback Gemini CDP oraz pięć
obecnych modeli Perplexity: GLM 5.3, Kimi 3, Grok 4.6, Sonnet 5, GPT Terra.
Zweryfikuj wartości w aktualnym źródle rosteru; ten zapis dokumentuje
zamierzone zachowanie z 2026-09-07, nie uprawnia do samodzielnej zmiany modeli.
CLI wykluczone przez aktualną politykę nie wracają jako nowa lane.

Użyj Conductor i zatwierdzonych adapterów. Wysyłaj tylko materiał dozwolony
dla danego odbiorcy po wymaganym secret preflight. Dostęp connectora potwierdź
dla konkretnego repo i rewizji. Nie obcinaj kontraktów; brak pełnego materiału
oznacz przed werdyktem. Rejestruj każdy oczekiwany model, próbę, błąd oraz
faktyczny wynik. Częściowa kolekcja służy analizie, ale clearance wynika z
obowiązującej polityki reviewerów, nie z exit 0 ani własnego progu quorum.
Jeśli brak jawnej polityki dopuszczalnej degradacji, rozstrzygnij ją w planie
przed wdrożeniem; nie twórz wyjątku w trakcie nieudanego runu.

Przeprowadź syntezę, sprawdź ACCEPT i popraw plan w zakresie. Niepewny submit
jest terminalny dla automatycznego retry/resubmission/fallback. Pewna odmowa
przed submit może użyć tylko fallbacku dopuszczonego aktywną polityką.

**3. Eng.** Uruchom [eng review](eng-review.md). Przygotuj aktualne, obsługiwane
stampy i dry-run dispatchu. Zapisz zależności, dokładne pliki, testy i
niezależne review. Wymagany dry-run musi zakończyć się 0 na planie przeznaczonym
do wykonania. Zmiana celu/ryzyka wraca do CEO; zmiana istotnego kontraktu lub
założenia unieważnia zależny audyt i wraca do etapu 2 w tym samym workflow.
Wtedy ponownie obowiązuje pełna skonfigurowana polityka panelu; nie wprowadzaj
samowolnego „delta-only reviewer”. Korekta redakcyjna z udokumentowanym brakiem
zmiany znaczenia nie wymaga udawania nowej decyzji produktowej.

**4. Implementacja.** R1 kontynuuje bez nowego GO. R2/R3 wymaga jednej ważnej
zgody na znany zakres. Zgoda obejmuje zakresowe poprawki, review, CI i landing;
osobne granice trigger/deploy/destrukcji pozostają. Wykonaj rolę
[IMPLEMENT](implement.md) przez zatwierdzone przypisania. Astra planuje
i rozstrzyga, CDP tworzą istotny kod i niezależne review, lokalny Codex
przekazuje pliki, stosuje zmiany, testuje i prowadzi Git zgodnie z obecną
polityką pracy. Awaria CDP nie daje automatycznie zgody na autorstwo Astry.
Tylko ciężkie pytesty używają `host:heavy`. CDP korzysta z niezależnych pul
`cdp:*` i nie czeka na lease pytestów ani recovery `host:heavy`. Przeglądarka
i Playwright nie są heavy. Zachowaj ownership i zwalniaj każdą pulę po jej pracy.

**5. Exact-head review.** Po lokalnej walidacji przygotuj commit, push,
draft PR i canonical packet. Rola [review](implementation-review.md) działa
na zatwierdzonej niezależnej lane/modelu. Weryfikuj full SHA, źródło,
kompletność oraz poświadczenia. NO_REVIEW, nieaktualny head i brak wymaganej
lane nie są PASS. Napraw zakresowe blokery, zweryfikuj i zrecenzuj nowy head.
Nie dodawaj drugiego pełnego lokalnego review udającego niezależność.

**6. Dostarczenie.** Właściciel workflow wykonuje Ready raz, wymagane CI,
squash merge i bezpieczny fast-forward faktycznej gałęzi domyślnej. Zachowaj
cudze zmiany. Uruchom post-hook planu. Raport zawiera zachowanie, ważne
dowody, authorship/applier/reviewer, PR/SHA, stan instalacji/runtime i pozostały
gate. Zatrzymaj się tylko na rzeczywistym blokującym warunku; nie po samym
napisaniu kodu.

## Projekt przekazywania stanu

Każdy etap przekazuje dalej istniejący task/plan, referencję materiału,
decyzje, ustalenia, ważność dowodów i status autoryzacji. To wymaganie projektu,
nie nowy plik receipt ani zmiana schema w tym R0. Nie dopisuj pól do
produkcyjnego parsera przez samo wykonanie instrukcji tekstowej.

Nie dodawać osobnego full workflow, nowego executor CLI, obowiązkowego
ARCHITECT/QUANT/TDD do każdej zmiany ani niezależnego cyklu `/autoplan` wewnątrz
`/fwf`. Pomocnicze role zwracają wynik do właściciela aktualnego etapu.
