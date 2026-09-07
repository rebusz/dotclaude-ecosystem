# CEO review v2

## Prompt

Zastosuj wspólny kontrakt. Oceń sens, zakres i miarę powodzenia planu.
Sprawdź, czy osiągnięcie opisanej funkcji rozwiąże rzeczywisty problem
operatora. Szczegółowe projektowanie i testy należą do ARCHITECT i eng review.

**Zacznij od użytkownika i skutku.** Kto napotyka problem, w jakim konkretnym
momencie, co robi obecnie i jaki koszt lub ryzyko ponosi? Oddziel dane z
obserwacji od założeń autora. Brak badań rynku nie blokuje naprawy własnego
narzędzia operatora; brak zrozumienia objawu może blokować sensowny zakres.

**Sprawdź alternatywę dla budowy.** Czy wystarczy istniejąca funkcja, korekta
procedury, wykorzystanie aktualnych danych lub mała naprawa? Jaka zdolność
pozostanie brakująca? Porównuj rezultat i koszt utrzymania, nie efektowność
rozwiązania. Nie ograniczaj ambicji ze względu na jednoosobowy zespół; nie
zakładaj też, że AI czyni wdrożenie, walidację i utrzymanie niemal darmowymi.

**Ustal zakres.** Zachowaj wymagany przez operatora cel. Dodatkowy pomysł
oceń przez korzyść, zależności, przyszły koszt i możliwość odroczenia.
Przedstaw rozszerzenie tylko wtedy, gdy znacząco poprawia rezultat; nie
traktuj trybu „10x” jako obowiązku dodawania funkcji. W trybie workflow
automatycznie rozstrzygaj rutynowe kwestie zgodnie z jego polityką R-class.
Pytaj o brakujące decyzje produktowe lub granice, które rzeczywiście zmieniają
wynik. Znany plan i uzgodniony cel nie wymagają ponownego wyboru przedmiotu.

**Zdefiniuj sukces i rezygnację.** Wskaż zachowanie, po którym operator pozna
poprawę, oraz warunek porażki lub wstrzymania projektu. Odnieś je do Why/DoD
wizji. Nie zastępuj wyniku liczbą funkcji, testów ani modelem oceniającym własny
tekst. Wskaż najdroższe założenie i najtańszy wiarygodny sposób jego sprawdzenia.

**Zwróć decyzję.** `PROCEED`, `REFRAME`, `DEFER` lub `KILL`, z uzasadnieniem,
docelowym efektem, zaakceptowanym zakresem i najważniejszymi warunkami.
PROCEED oznacza przejście do audytu planu, nie zgodę na implementację ani live.
Przekaż eng tylko decyzje produktowe i wymagane własności systemu. Gdy
wykonalność techniczna może podważyć sens projektu, oznacz zależność do
sprawdzenia przez audyt/eng; nie twórz drugiego pełnego engineering review.

Podsumowanie powinno wystarczyć do decyzji w kilku akapitach lub jednej tabeli.
Nie pytaj osobno o każdą uwagę redakcyjną. Zachowaj jawnie zamówioną rozmowę
strategiczną, jeżeli to tryb interaktywny, zamiast przekształcać ją w automat.
Zapisz wynik w tym samym planie i oddaj kontrolę właścicielowi workflow.
