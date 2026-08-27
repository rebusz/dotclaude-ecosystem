# Handoff — napisz plan GUI operatora Conductora

**Written** 2026-08-27 | **From** Cursor (WatchF / CoderPX connectivity session)
**To** agent piszący plan (Claude `/fwf` R2 albo równoważny grill → plan)
**Repo planu** `D:/dotclaude/dotclaude-ecosystem` (trunk `main`)
**To nie jest plan i to nie jest GO na kod.** Kolejny krok: jeden plik planu.
**Idea box** (2 linie, 2026-08-27): `IDEA_BOX.md` — Conductor operator GUI.

## Co operator chce zobaczyć

Jedna powierzchnia, na której widać **bramki, procesy, kolejkę** i stan recovery
Conductora — bez `conductorctl resource-status --json` (dziś ~240 KB historii).

Konkret, który to wywołał (live, 2026-08-27 ~12:37 MT):

```text
python D:/APPS/WatchF/scripts/coderpx.py --probe-models
→ coderpx.result.v1 status=CONDUCTOR_UNAVAILABLE exit_code=4
   detail=host:heavy not admitted: state=QUEUED reason=HOST_RESOURCE_BUSY
```

W tym samym momencie `resource-status` pokazywał `active_units=0`, ale slot był
zablokowany przez `RECOVERY_REQUIRED` (`tsignal-cctv:79584`, `LEASE_EXPIRED`,
`rr_55a2d45ff178`, od 2026-08-27T14:12:17Z) plus 5× `QUEUED` (kolejne CCTV +
`t4-ops-unblock`). Operator musiał pytać, co znaczy „zwolnić host:heavy”.
GUI ma tę klasę sytuacji tłumaczyć sam: kto trzyma, dlaczego, od kiedy, co
kolejkuje, czy to ACTIVE czy recovery fence.

## Plik, który masz napisać

`design/plans/2026-08-27_conductor_operator_gui_r1.md`

Frontmatter jak w `design/plans/2026-07-22_truthdeck_conductor_cross_repo_work_queue_r2.md`
(`title`, `date`, `status: draft-awaiting-go`, `risk`, `repos`, `tags`, `related`).
**Plan-writing authorization:** operator poprosił o ten handoff 2026-08-27
(„napisz handoff do napisania planu”). To uprawnia **napisanie planu**, nie
implementację. Kod dopiero po named GO planu (wzorzec:
`GO CONDUCTOR HOST RESOURCE LEASE R2`).

## Kroki agenta planu (w tej kolejności)

1. Wczytaj ten handoff, `skills/conductor/SKILL.md`, HRL-R2 w planie Conductora
   (`2026-07-22_truthdeck_conductor_cross_repo_work_queue_r2.md`, sekcja host
   resource / admission, zwłaszcza `RECOVERY_REQUIRED` i `HOST_RESOURCE_BUSY`).
2. Zweryfikuj żywe readbacki, nie zgaduj: `conductorctl status --json`,
   `conductorctl resource-status --json`, `conductorctl doctor`. Zmerguj z
   incydentem CoderPX powyżej — jeśli stan się zmienił, zapisz delta w planie.
3. Grilluj otwarte decyzje z sekcji niżej. Nie przesądzaj ich w handoffie.
4. Napisz plan R1/R2: restatement, collision verdict, surfaces, slice’y,
   non-goals, testy, rollback. Potem `/fwf` (CEO + matrix + eng) zanim ktokolwiek
   otworzy PR z kodem.
5. Po wylądowaniu planu: zaktualizuj `IDEA_BOX.md` (zamień wskaźnik handoffu na
   ścieżkę planu). Nie implementuj.

## Collision verdict, którego plan nie może obejść

**AMEND / NEW CHILD PLAN, nie drugi scheduler.** Conductor już jest jedyną
władzą admission `host:heavy`. GUI jest **projekcją** `~/.conductor/conductor.db`
+ istniejących komend `conductorctl`. Nie wolno dodać drugiej bramki, drugiego
lease store, ani „lepszego” release path.

Sąsiad, którego nie wolno wessać: **Ecosystem Control Panel CP-C**
(`~/.claude/ECOSYSTEM_IDEA_BOX.md`, `D:/APPS/_shared/ECOSYSTEM_CONTROL_PANEL.md`)
— to start/stop/health aplikacji. GUI Conductora to lease/kolejka/recovery.
Wspólny tray jest dopuszczalny jako *shell*, nie jako połączenie władz.

## Otwarte decyzje (plan musi je grillować; handoff ich nie zamyka)

1. **Transport.** Conductor MVP jest **port-free** (SQLite writer + inbox rename;
   „no loopback HTTP server, WebSocket, or new port exists in the MVP”). GUI
   webowe wymaga **nowego bandu** w `D:/APPS/_shared/PORTS.md` (żaden app nie
   siedzi w cudzym paśmie 1000) **albo** świadomego braku serwera (lokalny HTML /
   rozszerzenie istniejącego tray / odczyt pliku statusu). Kandydat na band, jeśli
   web: **17100** (następny wolny po Hue Flow 16100) — tylko jeśli grill wybierze
   HTTP. Nie zgaduj portu w kodzie.
2. **Mutacje.** Domyślny kształt, który plan ma obronić albo obalić: **v1
   read-only**. Przyciski `release` / `reconcile` / `authorize` są R2 i nie mogą
   ominąć: `RECOVERY_REQUIRED_RELEASE_REFUSED`, tty-only GO, fail-closed expiry.
3. **Ciężkość odczytu.** Sam viewer **nie** requestuje `host:heavy`. Odczyt
   statusu musi zostać lekką ścieżką (jak dzisiejszy `resource-status`).
4. **Procesy.** Pokazuj `agent_instance`, `purpose`, `process_pid` /
   `process_start_time` **z ledgeru lease**. Skan WMI/CIM całej floty Chrome jest
   nową zdolnością i wymaga osobnego grillu (adapter pytest już tego zabrania).
5. **Historia vs live.** Dziś `resource-status` wylewa setki `RELEASED`. GUI ma
   mieć warstwę **live** (ACTIVE / INHERITED / QUEUED / RECOVERY_REQUIRED /
   QUARANTINED) i osobno historię, nie jeden nieskończony dump.

## Surfaces, które plan musi pokryć

| Surface | Źródło prawdy | Operator ma zobaczyć |
|---|---|---|
| Bramka `host:heavy` | pool: `capacity=1`, `enabled`, `active_units`, `queued`, `recovery_required`, `state_counts` | wolna / zajęta / recovery fence; nie mylić `active_units=0` z „wolna” |
| Holder | request + lease: `request_id`, `lease_id`, `agent_instance`, `purpose`, `attempt_id`, `reason_code`, heartbeat/expiry | kto, po co, od kiedy, TTL |
| Kolejka zasobów | `state=QUEUED` | kolejność (priority, `created_at_utc`, `request_id`), powód `HOST_RESOURCE_BUSY` |
| Recovery | `state=RECOVERY_REQUIRED` | że to **blokuje jak ACTIVE**; że zwykły release jest odmową; że trzeba reconcile po dowodzie |
| WorkItems | `conductorctl status` / store | `total_work_items`, `state_summary` — osobna kolejka od resource queue |
| Leader | `leader_id`, `leader_pid`, `leader_active`, `store_state` | czy coordinator w ogóle żyje |
| CDP / CoderPX (kontekst, nie własność) | read-only hint | np. WatchF `chrome_ppl :9224` down w dniu triggera — GUI Conductora nie zarządza Chrome; może tylko pokazać, że admission nie doszło do lane |

Stany requestu, które UI musi rozróżniać: `ACTIVE`, `INHERITED`, `QUEUED`,
`RECOVERY_REQUIRED`, `RELEASED`, `QUARANTINED`.

## Reuse (nie buduj równoległego API)

- CLI: `scripts/conductorctl.py` — `status`, `resource-status`, `doctor`,
  `resource-reconcile` (mutate, nie v1).
- Store: `scripts/conductor_store.py`, admission `scripts/conductor_resources.py`
  (`HOST_RESOURCE_BUSY` gdy blocker to ACTIVE **lub** RECOVERY_REQUIRED;
  `release()` rzuca `RECOVERY_REQUIRED_RELEASE_REFUSED`).
- Skill operatora: `skills/conductor/SKILL.md`.
- Konsumenci bramki (kontekst, nie implementacja w tym planie): WatchF
  `scripts/coderpx.py`, Tsignal CCTV, pytest adapter, CDP Fleet Manager.

## Non-goals tego planu

- Implementacja GUI.
- Auto-release / auto-retry wygasłych lease.
- Druga władza admission albo omijanie Conductora przez CoderPX/CCTV.
- Start/stop aplikacji (Control Panel).
- Własność Chrome / `chrome_ppl` / Perplexity.
- GO R2/R3 z GUI, MCP, env, inbox.
- Broker / order path / Tsignal runtime.

## Definition of done dla *planu* (nie GUI)

- [ ] Collision verdict zapisany: projekcja Conductora, nie now scheduler.
- [ ] Decyzja transportowa (port-free vs nowy band vs tray) z konsekwencją dla
      `PORTS.md`.
- [ ] v1 surfaces = tabela powyżej; mutacje świadomie in/out.
- [ ] Incydent 2026-08-27 jest acceptance story: operator widzi recovery fence
      CCTV i kolejkę bez czytania JSON.
- [ ] Named GO token do implementacji, osobny od plan-writing.
- [ ] `IDEA_BOX.md` wskazuje plan po wylądowaniu pliku.

## Pułapki

- `HOST_RESOURCE_BUSY` przy `active_units=0` jest poprawny — recovery fence.
- GUI, które samo bierze `host:heavy`, zagłodzi CoderPX/CCTV/pytest.
- `resource-status --json` to zły payload na żywo (pełna historia RELEASED).
- WatchF `design/plans/` auto-commit **nie dotyczy** tego repo; plan ląduje w
  `dotclaude-ecosystem` według tamtejszego cyklu `/fwf` + PR.
- Nie commituj brudnego drzewa WatchF przy tej robocie.
