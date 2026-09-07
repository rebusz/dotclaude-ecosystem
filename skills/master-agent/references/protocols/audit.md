# AUDIT v2

## Prompt

Zastosuj wspólny kontrakt. Oceń zgodność wskazanego kodu, planu lub procesu z
konkretnymi wymaganiami. Wynikiem ma być lista rozstrzygniętych ustaleń i luk,
nie poprawka ani projekt nowego systemu.

1. **Ustal zakres i kryteria.** Wskaż oceniany obiekt, jego rewizję i źródła
   wymagań. Dla planu sprawdź wizję Why/DoD oraz kolizję z aktywnymi planami.
   Oddziel wymagania od preferencji i propozycji. Jeśli źródła się wykluczają,
   nazwij konflikt i obowiązującą hierarchię; nie oceniaj według wygodnego wariantu.
2. **Zbuduj mapę warunków.** Wybierz warunki istotne dla tego zadania: właściciel
   stanu, wejścia/wyjścia, trwałość, idempotencja, autoryzacja, zgodność wersji,
   odbudowa po przerwaniu, widoczność błędu. Nie skanuj całego repo bez potrzeby.
   Każdy warunek powiąż z miejscem egzekwowania i dowodem albo oznacz jako UNKNOWN.
3. **Prześledź rzeczywistą ścieżkę.** Wejście → walidacja → decyzja → skutek →
   potwierdzenie. Sprawdź normalny przebieg i istotne gałęzie awarii, w tym
   częściowy sukces, duplikat, stary stan lub utratę odpowiedzi, jeśli występują.
   Dowód z pominiętej gałęzi lub nieaktywnej konfiguracji nie potwierdza celu.
4. **Zweryfikuj własne zarzuty.** Zanim zgłosisz brak pola, walidacji lub obsługi,
   sprawdź definicję, konstruktory, wszystkich istotnych zapisujących/czytających
   i warstwę wyżej/niżej. Nie traktuj braku opisu w planie jako dowodu błędu kodu.
   Pokaż kontrprzykład albo warunki wystąpienia. Nie wymyślaj scenariuszy bez
   związku z kontraktem i dostępnymi danymi.
5. **Zwróć raport.** Werdykt zakresowy, krótka tabela warunków, ustalenia P1/P2
   ze wspólnego formatu, niewiadome blokujące dowód i istotne odrzucone alarmy.
   Dla każdej luki podaj najmniejszy probe lub poprawkę planu. Detale i P3
   umieść w artefakcie, gdy przesłaniają główny rezultat.

Możesz potwierdzić znaleziony błąd odczytem lub uprawnionym bezpiecznym probe;
nie uruchamiaj drugiego pełnego workflow wyłącznie dla etykiety DEBUG.
Jeśli potrzebny jest eksperyment diagnostyczny, przekaż mu objaw i dowody.
Sam AUDIT nie upoważnia do zmiany kodu ani runtime. Jeżeli użytkownik zażądał
następnego trybu, przekaż mu wynik i kontynuuj w ustalonej kolejności.

Zakończ `>> AUDIT COMPLETE` wraz z liczbą potwierdzonych P1 i nazwaniem
istotnych luk. Nie pisz „system bezpieczny” na podstawie cząstkowego przeglądu.
