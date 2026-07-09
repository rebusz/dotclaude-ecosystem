# Operator Playbook — kiedy i jak używać skilli

_Ręcznie kuratorowany manual decyzyjny (2026-07-09). Pełny katalog "co istnieje" →
[SKILLS_INDEX.md](SKILLS_INDEX.md) (auto-generowany). Ten dokument odpowiada na
"KIEDY i JAK", nie "co jest zainstalowane". Aktualizuj przy zmianach nawyków,
nie przy każdej instalacji skilla._

## 0. Mapa mentalna: jedna pętla

Prawie każda praca przechodzi przez tę pętlę — skille są przypisane do faz:

```text
POMYSŁ ──► WYWIAD ──► SPEC/PLAN ──► GATE'Y ──► GO ──► IMPLEMENT ──► REVIEW ──► LAND ──► RETRO
  │          │            │           │                │              │          │
whatnext   grill-me     /spec        /fw          /executor      /code-review  land-on-  /learn
IDEA_BOX   grilling     office-    (ceo→fusion    mode implement  /verify      main       retro
mem-search grill-with-  hours       →eng→GO)      tdd             /simplify    lifecycle  handoff
           docs                     /autoplan
```

Model-invoked skille (diagnosing-bugs, tsu-*, research, tdd...) triggerują się
same z opisu — ich nie musisz pamiętać. Nawyk musisz zbudować tylko dla
**user-invoked**: `grill-me`, `/fw`, `/spec`, `/verify`, `/handoff`, `/whatnext`.

## 1. Tabela nawyków IF→THEN (sedno tego manuala)

| Sytuacja (IF) | Odruch (THEN) | Dlaczego |
|---|---|---|
| Nowy pomysł, jeszcze mgła; nie umiesz napisać 3 zdań spec | **`/grill-me`** | bezlitosny wywiad 1-pytanie-na-raz zanim cokolwiek powstanie |
| Pomysł + istniejący kod/dokumenty do uzgodnienia | `/grill-with-docs` | grill + domain modeling na realnym repo |
| "Co dalej? / priorytety / czy dryfujemy" | `/whatnext` | STEERING BRIEF z north-star + IDEA_BOX; nigdy nie zmyśla backlogu |
| Pomysł doprecyzowany → trzeba go spisać | `/spec` | mgła → wykonywalna specyfikacja w 5 fazach |
| Plan ważny (R2/R3, trading, kontrakty) | **`/fw`** | Twoja paczka: ceo-review → fusion → eng-review → GO gate; FWF=free, FWP=paid |
| Plan mniejszej wagi, chcesz szybki multi-review | `/autoplan` | te same recenzje, auto-decyzje, bez przerywania Ci |
| Chcesz tylko skrytykować plan zewnętrznymi modelami | `/audit` (auditF free / `paid`=auditP) lub `/fusion` | pamiętaj: lane'y CDP wymagają formatu P1/P2/P3 |
| GO padło → implementacja | `/executor` albo `mode implement` | izolowany worktree, testy, commity, minimalne przerywanie |
| Coś nie działa (bug/regresja) | opisz symptom — `diagnosing-bugs` wstanie samo; twardy przypadek: `mode debug deep` | pętla diagnozy z bisekcją zamiast zgadywania |
| Logika tradingowa: "czy to ma sens/edge?" | `mode quant` (v2); głębiej: `mode quant deep` | evidence-first, regime stress, falsyfikacja przez LAB seam |
| Przed commitem nietrywialnej zmiany | `/verify` | przejedź flow end-to-end, nie tylko testy |
| Przed merge | `/code-review` (R2/R3 zawsze; R1 przy dużym diffie); R3: zaproponuj operatorowi `ultra` | gate wg klasy ryzyka — nie do pominięcia |
| Kod działa, chcesz go odchudzić | `/simplify` | reuse/uproszczenia bez polowania na bugi |
| Kontekst sesji pełny / przekazujesz pracę | `/handoff` (kompaktuje rozmowę) lub `/context-save` | kondensat zamiast re-czytania historii |
| "Czy myśmy tego już nie rozwiązali?" | `mem-search` (claude-mem) | 388k tokenów przeszłych sesji jest przeszukiwalne |
| Research: fakty z docs/API, delegowane w tło | `/research` (Matt, NOWY) | background agent, cytowane źródła, plik .md w repo |
| Research: głęboki raport z weryfikacją | `/deep-research` | fan-out + adversarial verify + syntezowany raport |
| Research: co ludzie mówią OSTATNIO | `/last30days` | Reddit/X/HN/YT z last 30 days |
| Pytanie o TSU (arming, custody, depth, porty...) | nic — skille `tsu-*` triggerują się same | 11 destylowanych skilli; nie odbudowuj wiedzy ręcznie |
| Nowe repo / odświeżenie wiedzy repo | `/distill-repo` | builder biblioteki skilli per-repo (ręczny, po epiku/~4 tyg.) |
| Piszesz/poprawiasz skilla | `/writing-great-skills` + `skill-creator` | słownik + failure modes (Negation, Negative Space) |
| Frontend/UI | samo się załaduje (taste stack); live dashboardy: `tsu-dashboard-taste` nadpisuje | anti-slop + zakaz animacji na live danych |
| Zmiana wygląda groźnie (delete/reset/prod) | `/careful` lub `/guard`, `/freeze` na katalog | guardraile zanim coś zniknie |
| Koniec tygodnia / po wysyłce | `/retro`, `/learn` (zapis lekcji) | compounding: lekcje wracają w następnych sesjach |

## 2. Jak używać pakietu grill (nowo zainstalowany, v1.1.0)

Trzy warianty, jeden silnik (`grilling`):

- **`/grill-me`** — czysty wywiad o plan/design. Mechanika: pyta o JEDNĄ rzecz
  na raz i czeka; fakty sprawdza sam w repo, ale **decyzje są Twoje** — każdą
  wykłada z własną rekomendacją; nie zacznie implementować, dopóki nie
  potwierdzisz shared understanding. Kiedy: zanim powstanie plan/spec; gdy
  czujesz "wiem czego chcę, ale nie umiem tego wysłowić".
- **`/grill-with-docs`** — jak wyżej + kotwiczy pytania w istniejących
  dokumentach/kodzie i buduje domain model. Kiedy: feature w istniejącym
  systemie, gdzie diabeł tkwi w obecnych kontraktach.
- **`grilling`** — model-invoked silnik; wstaje też sam na frazy typu
  "przemagluj mnie / stress-test this plan". Nie wołasz go bezpośrednio.

**Gdzie grill siedzi w Twojej pętli:** grill-me → (opcjonalnie /spec) → /fw.
Grill NIE zastępuje gate'ów /fw — on sprawia, że plan wchodzący w /fw jest
Twoim planem, a nie pierwszym strzałem modelu.

**Nawyk-kotwica (jedno zdanie):** *"Nowy plan bez odbytego grilla = smell".*
Jeśli piszesz `nowy plan` / `tworzymy plan` i nie było grilla — powiedz
"grill me first". Fizyczna kotwica istnieje też po stronie agenta: reguła
w CLAUDE.md (patrz §5).

## 3. Ściągawka: paczka /fw i tryby master-agent

- **`/fw`** = ceo-review → fusion → apply → eng-review → GO gate.
  `fw` (FWF) = autonomiczny + darmowa fuzja; `fw paid` (FWP) = interaktywny +
  płatna; `fw close` = pętla po implementacji. Implement GO tylko po eng-review
  i wypowiedziane wprost (nie klik w AskUserQuestion).
- **`mode <MODE> task <opis>`**: OPERATOR (routing), ARCHITECT (projekt),
  IMPLEMENT (buduj), DEBUG [deep], AUDIT (zgodność/diff), QUANT [deep]
  (trading). Szablony wyjścia: POSTMORTEM / TEST / CONTRACT / INTEGRATE.
  Chaining działa: `mode audit debug task ...`. Polskie triggery działają.
- **`/code-review`**: low/medium = mało, pewne findings; high→max = szerzej;
  `ultra` = wieloagentowy w chmurze, **odpala operator** (billowane), R3.

## 4. Rozstrzygnięcia bliźniaków (co wybrać, gdy dwa robią podobnie)

| Para | Wybór |
|---|---|
| `grill-me` vs `/office-hours` | grill = ostry wywiad o TWÓJ plan; office-hours = eksploracja YC-style gdy nie wiesz jeszcze CO budować |
| `/spec` vs `to-spec`/`to-tickets` (Matt) | używamy `/spec` (gstack); Mattowych nie instalowaliśmy — dublowały pipeline |
| `/research` vs `/deep-research` | research = tanie, w tle, fakty z primary sources; deep-research = raport z adversarial verify |
| `/audit` vs `/fusion` | audit = krytyka dokumentu per-lane; fusion = panel odpowiada na pytanie/problem |
| `/investigate` vs `diagnosing-bugs` vs `mode debug` | opisz bug naturalnie → diagnosing-bugs; investigate = gstackowy odpowiednik; mode debug deep = pełne śledztwo z protokołem |
| `/handoff` vs `/context-save` | handoff = dokument dla INNEGO agenta; context-save = checkpoint dla siebie |
| `/qa` vs `/verify` | qa = systematyczny przegląd appki (browser); verify = dowód że TA zmiana działa end-to-end |
| `codex` vs Claude | bulk/mechaniczne V0-V3 → Cursor/Composer/codex; złożone → Claude (track-routing-by-v-scale) |

## 5. Mechaniczne wsparcie nawyku (żeby nie polegać na pamięci)

1. **Reguła w globalnym CLAUDE.md** (sekcja Plan Lifecycle): przy triggerach
   `nowy plan` / `tworzymy plan` / `mode architect` agent ma zapytać
   "grill first?" jeśli w sesji nie było grilla. (Dodana 2026-07-09 — patrz
   commit tego dokumentu; jeśli jej nie ma, dodaj jedno zdanie do overlay.)
2. **`/plan-tune`** obserwuje Twoje odpowiedzi na AskUserQuestion i uczy się,
   które pytania auto-decydować — zostaw włączone.
3. **Skill routing w repo CLAUDE.md** (gstack to oferuje) — jeśli w jakimś repo
   agent nie podpowiada skilli, dodaj sekcję "## Skill routing".
4. Ten playbook jest linkowany z SKILLS_INDEX; po dodaniu ważnego skilla dopisz
   wiersz do tabeli IF→THEN — inaczej umrze jak każdy manual.

## 6. Czego celowo NIE używamy

- `code-review` Matta — kolizja z naszym `/code-review` (load-bearing gate).
- `implement`, `to-spec`, `to-tickets`, `wayfinder` (Matt) — dublują
  /spec + /executor + plan lifecycle; z wayfindera bierzemy tylko pomysły.
- Legacy gstack modes (SHIP/QA/CSO/... jako "mode X") — żyją w
  `master-agent/refs/gstack-archive.md`, wołaj przez slash-komendy zamiast mode.
