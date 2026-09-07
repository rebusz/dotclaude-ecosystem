# Engineering review v2

## Prompt

Zastosuj wspólny kontrakt. Sprawdź, czy wybrany plan da się wykonać, przetestować
i wdrożyć w jego uzgodnionym zakresie. Przyjmij wynik CEO oraz rozstrzygnięcia
audytów jako wejście, ale nie jako dowód poprawności technicznej. Nie twórz
od nowa wizji produktu ani projektu tylko po to, by wypełnić szablon.

1. **Potwierdź przedmiot i aktualność.** Otwórz wskazany plan i jego rewizję,
   HEAD repo oraz rejestr ustaleń. Nie pytaj ponownie o target, jeśli przekazał
   go workflow. Sprawdź zamknięte uwagi w rzeczywistym tekście. Materiał
   po istotnej zmianie wymaga oceny jej skutków; stary werdykt nie przenosi
   się automatycznie na nowy kontrakt.
2. **Przejdź po mechanizmie.** Zweryfikuj interfejsy, właścicieli zapisu,
   granice zależności i najistotniejszy failure path. Sprawdź idempotencję,
   wyścigi, anulowanie, retry, utratę odpowiedzi, odzyskanie oraz zgodność
   wersji tam, gdzie występują. Dla zarzutu o brak sprawdź definicję i callerów,
   zamiast wnioskować z nazwy. Zwróć uwagę na rzeczywisty koszt lub limit,
   nie hipotetyczny p99 bez pomiaru.
3. **Powiąż wymagania z dowodami.** Każdy istotny warunek ma mieć test lub
   właściwy probe: wejście/stan, realną ścieżkę, oczekiwany wynik i artefakt.
   Uwzględnij błąd/rollback; unikaj mocka omijającego skutek, fixture
   symulującej gotowy restart i testu powtarzającego samą implementację.
   Zachowaj repo-native gates. Dla promptów wymagaj oceny zachowania na
   stałych przypadkach, nie tylko sprawdzenia fraz i długości tekstu.
4. **Uczyń wykonanie jednoznacznym.** Każdy slice otrzymuje właściciela,
   dokładny write-set, zależności, DoD, validation, rollback i recenzenta
   niezależnego od autora zgodnie z obowiązującą polityką. Liczba plików jest
   sygnałem do sprawdzenia sprzężeń, nie automatycznym STOP. Nowe ścieżki
   oznacz jako proponowane. Przeplatających się zapisów nie nazywaj pracą
   równoległą. Przy istniejącym stamp v2 wygeneruj wyłącznie pola i wartości
   obsługiwane przez dispatcher, a następnie wymagaj jego dry-run exit 0.
5. **Sprawdź dostarczenie i resztę ryzyka.** Określ kompatybilność, kolejność
   migracji/instalacji, odwracalność, obserwowalność oraz wymagany smoke.
   Nie wprowadzaj domyślnego shadow/disabled wbrew planowi. Oddziel ukończenie
   kodu od produkcyjnego wdrożenia i bramki real-money. Rozstrzygaj mechaniczne
   poprawki w zakresie samodzielnie; pytaj o rzeczywiste rozszerzenie lub
   brakującą autoryzację, zgodnie z polityką workflow.

Raport: `READY_FOR_IMPLEMENTATION_GATE` albo `REVISE_PLAN`, blokery i
rozstrzygnięcia, tabela slice oraz dowody wykonalności. Dla każdego istotnego
uzupełnienia powiedz, czy zmienia wcześniejszą decyzję CEO/audytu. Jeśli tak,
oddaj kontrolę właścicielowi workflow do ponownej walidacji właściwego etapu;
nie uruchamiaj własnego panelu ani drugiego `/fwf`.

READY_FOR_IMPLEMENTATION_GATE nie jest operator GO i nie zastępuje
post-implementation review. Nie dopisuj mechanicznie pełnego test suite,
E2E, diagramu, nowego alertu i pytania do operatora do każdej małej zmiany.
