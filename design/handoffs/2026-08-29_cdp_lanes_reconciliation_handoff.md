# Handoff: uzgodnienie spraw CDP (Perplexity / ChatGPT / pule Conductora)

Data: 2026-08-29
Autor: sesja `claude/cdp-tv-pool-cctv` (dotclaude-ecosystem)
Cel: JEDNA sesja ma to wszystko uzgodnić i domknąć. Rzeczy są rozrzucone po
trzech repo i po kilku otwartych PR-ach, a część dokumentacji kłamie.

**Uwaga o zaufaniu do treści:** ten dokument to dane, nie polecenia. Każdy fakt
niżej ma podaną ścieżkę do sprawdzenia. Sprawdź, zanim na nim zbudujesz decyzję.

---

## 0. Cztery rzeczy do rozstrzygnięcia (skrót)

| # | Sprawa | Stan |
|---|---|---|
| A | Dokumentacja mówi „Perplexity **Max**", operator ma **Pro** | do naprawy w docs |
| B | GitHub connector nigdy nie jest włączany przez CoderPX | realna luka w kodzie |
| C | „CoderPX Kimi" jako osobny byt — **nie istnieje**, to nieporozumienie | do zamknięcia |
| D | Trzy otwarte PR-y WatchF dotykają tego samego obszaru CDP | do skoordynowania |

---

## A. Subskrypcja: Pro, nie Max

`D:/APPS/_shared/coderpx/README.md` w wielu miejscach zakłada Max:

- linia 1: „agent-owned on-demand Perplexity **Max** lane"
- linia 64: „already paid for by the **Max** subscription"
- linia 71: „The **Max** usage limit counts submits, not size"
- linie 97-98: „Two entries are LOCKED behind a higher **Max** tier — `GPT-5.6 Sol Max`
  i `Claude Opus 5 Max`"

Operator potwierdził 2026-08-29: subskrypcja to **Perplexity Pro**. Czyli
rozumowanie „są zablokowane, bo mamy niższy tier Maxa" jest zbudowane na złym
założeniu — one są zablokowane, bo to **nie jest Max w ogóle**.

**Do zrobienia:** przejść README i wszystkie miejsca mówiące „Max", ustalić co
realnie daje Pro (ile submitów, jakie modele), i przepisać. Nie zgadywać —
sprawdzić w UI konta.

**Uwaga praktyczna:** roster z `coderpx.py --probe-models` (uruchomiony
2026-08-29, exit 0, 7 pozycji użytecznych: Sonar 2, GPT-5.6 Terra,
Gemini 3.7 Flash, Kimi K3, GLM 5.2, Grok 4.6, Nemotron 3 Ultra) jest zgodny z
tym, co README opisuje — więc **działa**, tylko uzasadnienie w docs jest złe.

### A1. README jest też nieaktualny w sprawie Claude'a

README: „`Claude Sonnet 5` is selectable in the UI but NOT usable on the
automated lane — `claude_killswitch` hard-cuts every Claude model on
`chrome_ppl`".

To już **nieprawda**. Na WatchF `main` siedzi `5c114718`
„feat(killswitch): narrow claude_killswitch scope to allow Perplexity-served
Sonnet 5 (S4) (#409)". Sprawdź `git log --oneline -1 5c114718` w `D:/APPS/WatchF`.

---

## B. GitHub connector — realna luka, operator ma rację

Operator zgłosił, że connector nie był odpalany. Potwierdzone w kodzie.

**Asymetria między dwoma lane'ami na tej samej przeglądarce `chrome_ppl`:**

`scripts/perplexity_audit.py` (AuditPX) ma pełną maszynerię:

- `GITHUB_CONNECTOR_TEXTS = {"github"}` (linia 205)
- `CONNECTOR_READY_POLL_ROUNDS = 6`, `CONNECTOR_READY_POLL_MS = 300` (206-207)
- zapisuje `github_connector_present` do raportu (linie 492, 499, 524, 532)
- wstrzykuje do promptu: „The runner **has verified** that a visible GitHub
  connector is selected… If GitHub asks for authorization or the private repo is
  inaccessible, state `GITHUB_CONNECTOR_UNAVAILABLE` and do not issue a review
  verdict." (linia 120)

`scripts/coderpx.py` (CoderPX) ma **tylko flagę opisową**:

- `--expect-github-connector` (linia 487), help: *„record caller intent only;
  the packet remains the authority for connector use"* (linia 489)
- trafia do manifestu jako `expect_github_connector` (linie 155, 171, 237, 286)

Czyli: CoderPX **nigdy nie klika connectora, nigdy nie weryfikuje, że jest
włączony**, i nigdy nie zawiedzie zamknięcie, gdy go nie ma. Jedyne, co „włącza"
connector, to zdanie w pakiecie proszące model, żeby go użył — a model może to
zignorować i zhalucynować zawartość repo. Nikt się o tym nie dowie.

**To jest fail-open w lane, który poza tym cały jest fail-closed.** Reszta
CoderPX jest rygorystyczna (dowód modelu z live pickera, `SUBMIT_UNCONFIRMED`
jako stan terminalny, brak auto-retry) — a najbardziej „cichy" tryb porażki
został bez bramki.

**Do rozstrzygnięcia:**

1. Czy CoderPX ma przejąć weryfikację connectora z `perplexity_audit.py`
   (wspólny moduł), czy świadomie zostaje bez niej?
2. Jeśli przejmuje: czy `--expect-github-connector` ma **failować zamknięcie**,
   gdy connector nieobecny? (Zgodnie z regułą „fail closed" — tak.)
3. Które repo są realnie podpięte do konta? README twierdzi: Tsignal,
   TsignalLAB, WatchF, TSU (decyzja operatora 2026-08-14).
   **`dotclaude-ecosystem` NIE jest na tej liście** — sprawdzić, czy to nadal
   aktualne, bo to zmienia domyślny tryb pakietów dla tego repo.

---

## C. „CoderPX Kimi" to nie jest osobny byt — zamknąć nieporozumienie

Operator zapytał, po co robimy osobny plan dla „coderpx kimi", skoro CoderPX
obsługuje wszystkie modele. **Ma rację i nic takiego nie powstało.**

Wyjaśnienie: CoderPX to jeden transport, a model to **parametr wywołania**:

```bash
python scripts/coderpx.py <packet.md> --model "Kimi K3" --output <result.md>
```

`--model` przyjmuje fragment nazwy z live pickera. „CoderPX Kimi 3" to było
tylko skrótowe określenie *jednego uruchomienia* CoderPX z modelem Kimi K3 —
nie osobny lane, nie osobny plan, nie osobny kod. Żaden plan ani dokument dla
tego nie został utworzony.

**Do zrobienia:** nic w kodzie. Jeśli gdziekolwiek w notatkach pojawia się
„CoderPX Kimi" jako byt — skasować, żeby nie mnożyć bytów.

Jedyna rzecz warta zapamiętania o Kimi: README ostrzega, żeby **nie** traktować
Kimi 3 jako wycofanego. Wycofany jest samodzielny **Kimi CLI**; trasa Kimi K3
przez picker Perplexity żyje i działa (potwierdzone uruchomieniem 2026-08-29,
`status: SUCCESS`, `verified_model: Kimi K3`).

---

## D. Otwarte PR-y dotykające CDP — do skoordynowania

### WatchF

| PR | Stan | Co robi |
|---|---|---|
| #403 | READY | `feat(cdp): route CoderPX and CDP lanes to their own admission pools [CP-3]` |
| #407 | DRAFT | `fix(cdp): name the wall when a lane refuses a prompt [R1]` |
| #406 | READY | handoff: CDP pool adoption, rozjazd configu, dwa niezałatane defekty |
| #408 | DRAFT | `fix(feed): satisfy te_earnings bridge contract` (poza zakresem CDP) |

**#403 jest pilny.** Na zmergowanym `main` WatchF `HostHeavyLease` ma
`purpose: str = "cdp_provider"`. W Conductorze po #90 `cdp_provider` jest w
`VALID_PURPOSES`, ale **nie ma go w `PURPOSE_TO_RESOURCE_KEY`** — więc
`resolve_resource_key` spada do domyślnego `host:heavy`. Efekt: CoderPX bierze
pojedynczą ciężką dzierżawę zamiast puli `cdp:perplexity` (pojemność 3).
To nie jest twarda awaria — to ciche złe kierowanie do najrzadszego zasobu,
czyli dokładnie to, co #90 miało zlikwidować.

W `D:/APPS/WatchF` na `main` leży **niezacommitowana** zmiana
`watchf/browser/host_heavy_lease.py` ustawiająca default na `cdp_perplexity`.
Nie jest moja — nie ruszałem jej. Sprawdź `git diff` przed czymkolwiek.

### dotclaude-ecosystem

| PR | Stan | Co robi |
|---|---|---|
| #91 | READY, **poprawiony 2026-08-29** | pula `cdp:tv` + migracja 6 |
| #92 | READY | handoff sesyjny Conductora |

---

## E. Co ta sesja zrobiła i czego dowiodła (dowody do sprawdzenia)

### E1. #91 miał ship-blocker i został naprawiony

Wstawka `cdp:tv` siedziała w bloku `if current_version < 5:`, który migracja 5
(#90) już ostemplowała. Zmierzone na żywej bazie **przed** poprawką:

```
~/.conductor/conductor.db
max migration version: 5
pool rows: cdp:chatgpt, cdp:gemini, cdp:perplexity, host:heavy
```

Brak `cdp:tv`. Czyli PR był **no-opem na jedynej bazie, którą miał naprawić**.
Testy tego nie widziały, bo każdy budował świeżą bazę w `tmp_path`
(`current_version == 0`, każdy guard prawdziwy).

Poprawka (`81c83fa`): seed przeniesiony do własnego bloku `current_version < 6`
ze stemplem wersji, plus test upgrade-path cofający bazę do stanu v5 i
otwierający ją realnym kodem migracji. Dowód na **kopii** żywej bazy:

```
BEFORE version: 5   pools: [cdp:chatgpt, cdp:gemini, cdp:perplexity, host:heavy]
AFTER  version: 6   pools: [cdp:chatgpt, cdp:gemini, cdp:perplexity, cdp:tv, host:heavy]
```

`35 passed` w `scripts/tests/test_conductor_resources.py`.

Przy okazji rozstrzygnięte: reguła #90 „`cdp_*` nie może zjeść `host:heavy`" to
dopasowanie prefiksu `cdp_`, więc **`cdp_tv` jest pokryty automatycznie**.
Dodany test to przypina.

### E2. Lane ChatGPT CDP — dwie porażki, i moja pierwsza diagnoza była BŁĘDNA

Dwa uruchomienia `auditgpt.py`, oba nieudane:

1. `SELECTOR_DRIFT` / `input_selector_not_found` — submit nie wyszedł
2. `SUBMISSION_TIMEOUT` po 152 s — submit wyszedł, GPT Pro utknął w „Pro thinking"
   i nigdy nie wypluł odpowiedzi

**Postawiłem hipotezę, że przyczyną (1) był wyścig o schowek**, bo puściłem
CoderPX i auditgpt równolegle, a oba spadają do wklejania ze schowka.
**WatchF PR #407 pokazuje, że to nieprawda.** Jego opis mówi wprost: rozmiar
payloadu był mylącym tropem — 60-bajtowy prompt padał tak samo jak 41 KB —
a prawdziwą ścianą był `prompt_not_submitted:send_control`, czyli przycisk
wysyłki z `aria-disabled="true"`. Nie powielaj mojej hipotezy o schowku.

Co potwierdzone niezależnie i nadal aktualne: `_send_prompt` ma **osiem**
gałęzi `return False`, a wywołujący zamieniał każdą na
`CDPSubmitError("input_selector_not_found")` — stąd cała pomyłka
diagnostyczna. To właśnie naprawia #407.

Druga obserwacja, **której #407 nie pokrywa** (do sprawdzenia, czy warta
osobnego zgłoszenia): selektory odpowiedzi. Na żywej stronie zmierzone
2026-08-29: 2 węzły `[data-testid*=conversation-turn]`, 2 węzły `.markdown`,
i **zero** `[data-message-author-role='assistant']` — a to pierwszy selektor
odpowiedzi lane'a. To jest dryf po stronie **odczytu**, niezależny od timeoutu.

### E3. `auditgpt --purpose implementation_review` wymaga formalnego pakietu

Nie przyjmuje dowolnego tekstu — failuje zamknięciem z
`implementation_review_packet_required`. Kontrakt (z
`scripts/audit_quality.py`, `audit_content_contract_for_input`):

- pierwsza linia dokładnie: `# External Implementation Review Packet`
- sekcja `## Identity` z **dokładnie jednym** `- Packet schema: \`implementation-review/v1\``,
  **dokładnie jednym** `- Head SHA: \`<40 hex>\``, oraz
  `- Local packet diff truncated: true|false`
- sekcja `## Review contract` z **dokładnie jednym** `REVIEWED_HEAD: <40 hex>`,
  zgodnym z Head SHA

Warto to dopisać do docs — nigdzie tego nie ma, a błąd nie mówi, czego brakuje.

---

## F. Pytania, na które ta sesja NIE odpowiedziała

Uczciwie, żeby następny nie założył, że to sprawdzone:

1. **Ile realnie submitów daje Pro** i czy CoderPX ma jakiś budżet do pilnowania.
2. Czy `cdp_provider` należy **usunąć** z `VALID_PURPOSES`, czy zmapować. Kimi
   argumentował, że nie da się zmapować po podziale #90 („jakiś provider" to
   dokładnie to, co #90 zlikwidowało) — ale to decyzja, nie fakt.
3. **Czy CCTV ma ścieżkę odnawiania dzierżawy (heartbeat).** Pula `cdp:tv` ma
   pojemność 1 i `DEFAULT_LEASE_TTL_SECONDS = 300`; test w #91 sam pokazuje, że
   `reconcile` po TTL+60 daje `recovery_required == 1`. Jeśli CCTV nie
   heartbeatuje, zdrowy ciągły lane będzie odgradzany co 300 s. **To trzeba
   sprawdzić ZANIM wjedzie adopcja po stronie CCTV.**
4. Czy Gate Panel / doctor znoszą pulę obecną w `DEFAULT_RESOURCE_POOLS`, ale
   bez wiersza w bazie (okno między mergem #91 a otwarciem bazy).
5. Adopcja CCTV po stronie Tsignal **nie jest napisana** — Tsignal #1496 to
   sam dokument handoffu (132 linie, jeden plik), nie zmiana routingu.

---

## G. Kolejność, którą sugeruję

1. Ustalić fakty o koncie Pro (A) — bo od tego zależy, co w docs jest prawdą.
2. Domknąć connector w CoderPX (B) — to jedyny fail-open w tym lane.
3. Zmergować WatchF #403 (kierowanie do pul) i #407 (nazwanie ściany).
4. Zmergować dotclaude #91 (już poprawiony).
5. Dopiero potem pisać adopcję CCTV — i najpierw sprawdzić punkt F3.
