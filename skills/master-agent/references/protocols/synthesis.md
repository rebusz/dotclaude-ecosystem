# Synteza audytów v2

## Prompt

Zastosuj wspólny kontrakt. Rozstrzygnij ustalenia panelu na podstawie dowodów,
aktualnego zakresu i wymagań. Nie oceniasz, który model brzmi najbardziej
przekonująco. Twoja synteza nie zastępuje niezależnego review, jeżeli jesteś
autorem planu lub zmiany.

1. **Zweryfikuj wejścia.** Odczytaj manifest prób, odebraną rewizję planu,
   oczekiwane i faktycznie potwierdzone modele/transporty, kompletność odpowiedzi
   oraz błędy. Oddziel model panelisty od agregującej go lane. Nie licz pięciu
   odpowiedzi PPL jako pięciu niezależnych lane ani jednej odpowiedzi jako
   pełnego rosteru. Sposób liczenia i wymagane kanały bierzesz z polityki
   właściciela workflow. `synthesizer=gpt` oznacza pochodzenie syntezy, nie
   dowodzi wykluczenia modeli GPT z panelu.
2. **Znormalizuj i połącz duplikaty.** Ten sam mechanizm, warunek i skutek
   tworzą jedno ustalenie ze wszystkimi referencjami. Podobne sformułowanie
   nie wystarcza do połączenia różnych awarii. Liczbę popierających modeli
   zapisz jako informację, nigdy jako automatyczny wzrost pewności.
3. **Rozstrzygnij treść.** Dla każdej istotnej uwagi sprawdź wymaganie, źródło,
   scenariusz oraz kontrargument. Wybierz `ACCEPT`, `REJECT`, `DEFER` lub
   `NEEDS_EVIDENCE`, z przyczyną. Dwie zgodne halucynacje pozostają błędem.
   Jedna poprawna uwaga może blokować plan. UNKNOWN nie zamienia się w REJECT
   tylko dlatego, że żaden inny model tego nie zauważył. Własne nowe ustalenie
   oznacz jako pochodzące od synthesizera, bez przypisywania mu zewnętrznego review.
4. **Rozwiąż sprzeczności.** Pokaż, które założenie dzieli odpowiedzi i jaki
   fakt je rozstrzyga. Jeżeli faktu nie ma, zachowaj niewiadomą z probe i wpływem
   na następny etap. Nie twórz kompromisowej architektury łączącej wzajemnie
   sprzeczne propozycje. Nie rozszerzaj zakresu pod pozorem przyjmowania konsensusu.
5. **Wprowadź uzasadnione poprawki planu.** Właściciel etapu stosuje ACCEPT
   w granicach autoryzacji, zapisując ID ustalenia, zmienioną sekcję i nową
   rewizję. Dla zmian istotnych założeń określ, które wcześniejsze dowody
   przestały być aktualne. Zachowaj standing GO dla niezmienionego zakresu;
   aktualność dowodu i uprawnienie operatora to różne rzeczy.

Wynik: pokrycie panelu i błędy, rejestr decyzji o ustaleniach, rozstrzygnięte
sprzeczności, poprawki planu oraz niewiadome blokujące przejście. Ocenę jakości
treści oddziel od clearance etapu: `COLLECTION_COMPLETE/PARTIAL/FAILED`,
`CONTENT_READY/REVISE/INSUFFICIENT_CONTEXT` oraz status wymaganej bramki.
Etykiety są opisowe; nie deklaruj, że runtime już je zapisuje.

Nie wyznaczaj własnego quorum ani nie uznawaj exit 0 za clearance. Jeśli
obowiązująca polityka wymaganych reviewerów jest nieokreślona lub niespełniona,
zgłoś brak bramki i zatrzymaj zależne przejście. Częściowe odpowiedzi nadal
służą poprawie planu. Niepewny submit nie jest zgodą na ponowny dispatch.
