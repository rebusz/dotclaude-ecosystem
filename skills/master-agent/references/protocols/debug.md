# DEBUG / diagnoze / investigate v2

## Prompt

Zastosuj wspólny kontrakt. Wyjaśnij zgłoszony objaw przez rozróżniające dowody.
Domyślnie dostarcz diagnozę i plan naprawy; poprawkę wykonuj tylko w zakresie
autoryzowanego zadania i właściwego etapu implementacji.

1. **Ustal objaw i kontekst wykonania.** Oczekiwane versus zaobserwowane
   zachowanie, czas, wersja procesu, konfiguracja, wejście i ostatni znany dobry
   stan. Zacznij od istniejącego logu/trace i instrukcji modułu. Nie zakładaj,
   że HEAD checkoutu jest wersją działającego procesu. Powtarzalny objaw
   operatora traktuj jako obserwację do wyjaśnienia, nie jako błąd użytkownika.
2. **Zbuduj pętlę informacji zwrotnej.** Wybierz minimalny test, replay,
   kontrolowany probe lub obserwację, która pokazuje dokładnie ten objaw.
   Zapisz wejście, oczekiwany rezultat i rzeczywisty wynik. Dla problemu
   przerywanego ustal warunek obserwacji oraz ograniczenie próby; brak błędu w
   jednej próbie nie dowodzi naprawy. Kontynuuj możliwe odczyty, nawet jeśli
   brak środowiska uniemożliwia pełną reprodukcję.
3. **Rozróżnij przyczyny.** Po poznaniu kontekstu postaw tyle falsyfikowalnych
   hipotez, ile uzasadniają dane. Dla każdej: jeśli H jest prawdą, probe P pokaże
   X; jeśli nie, pokaże Y. Wybierz probe, który rozdziela najbardziej
   prawdopodobne wyjaśnienia. Nie zmieniaj kilku rzeczy naraz. Tymczasową
   instrumentację umieszczaj przy granicy, gdzie informacja się rozchodzi.
4. **Zamknij łańcuch przyczynowy.** Pokaż wejście → warunek → wadliwy stan →
   objaw, wraz z dowodami i kontrpróbą. Sprawdź config/runtime drift,
   współbieżność, częściowy zapis i granice integracji tylko, gdy pasują do
   ścieżki. Bisect wykorzystaj, jeśli masz znany dobry/zły stan i wiarygodny
   oracle. Nie zgaduj introducing commit, gdy brakuje historii.
5. **Przygotuj naprawę i potwierdzenie.** Proponuj zmianę usuwającą przyczynę
   oraz test oryginalnego objawu i istotnej gałęzi awarii. Nie osłabiaj asercji
   ani produkcyjnego fail-closed, aby uzyskać zielony wynik. Po autoryzowanej
   naprawie powtórz oryginalną pętlę i wymagane testy. Usuń instrumentację
   tymczasową albo uzasadnij jej pozostawienie.

Prowadź krótki rejestr hipoteza → probe → wynik → decyzja. Jeśli kolejne próby
nie rozróżniają hipotez, zmień metodę i nazwij brak informacji. Nie powtarzaj
tej samej próby bez nowego powodu. Zatrzymaj zależną pracę, gdy wymaga dostępu,
autoryzacji lub danych, których nie masz; licznik trzech nieudanych hipotez
sam w sobie nie stanowi obowiązku pytania operatora.

Raportuj przyczynę jako `CONFIRMED`, `SUPPORTED` albo `UNKNOWN`. Przy SUPPORTED
naprawa pozostaje hipotezą, dopóki wynik rozróżniającego sprawdzenia nie
potwierdzi mechanizmu. Awaryjne ograniczenie skutków opisz jako containment,
nie jako dowód usunięcia przyczyny. Zakończ `>> DEBUG COMPLETE` z dowodem,
pozostałą luką oraz statusem naprawy. Sam wynik diagnostyki nie oznacza DONE
implementacji.
