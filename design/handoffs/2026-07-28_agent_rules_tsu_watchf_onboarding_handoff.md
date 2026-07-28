# Handoff: podpięcie TSU i WatchF pod generator agent-rules

Data: 2026-07-28. Risk: R0/R1 (docs + non-live tooling). Rozmiar: ~1-2 h.
Kontekst nadrzędny: model "code vs trigger" wylądował 2026-07-28
(`agent-rules/core.md`, ref `agent-rules/refs/paper-live-parity.md`,
Tsignal PR #758). Globalne overlaye JUŻ pokrywają wszystkie platformy
(`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.clinerules/agent-rules.md`,
`~/.gemini/GEMINI.md`). Ta robota dodaje POZIOM REPO dla TSU i WatchF, żeby ich
pliki instrukcji były generowane z jednego źródła jak Tsignal/TsignalLAB.

## Stan zastany (zweryfikowany 2026-07-28)

- `D:/APPS/TSU`: jest `AGENTS.md` (bez managed-bloku), NIE ma `CLAUDE.md`.
  Trunk: `master`, remote `origin` = github.com/rebusz/TSU. Ma `.claude/skills`
  i od 2026-07-28 `.claude/settings.json` (hooki grafowe, commit `321f7442e`).
- `D:/APPS/WatchF`: są `CLAUDE.md` i `AGENTS.md` (oba bez managed-bloków).
  Trunk: `local/main`, śledzi `origin/local/main` (NIE `main` — nie zgaduj).
  `.claude/` jest w `.gitignore` tego repo.
- Generator: `D:/dotclaude/dotclaude-ecosystem/scripts/sync_agent_rules.py`.
  Tryby: `--check` (domyślny), `--diff`, `--write`, `--init-managed-blocks`,
  `--repo <path>` (allowlista!), `--tier tier1|tier2`.
- Allowlista repo: struktury `REPO_RULESETS` + `TIER1_REPO_SLUGS` /
  `TIER2_REPO_SLUGS` w `sync_agent_rules.py` (okolice linii 260-300).
  TSU i WatchF NIE są allowlistowane — `--repo D:/APPS/TSU` dziś rzuca
  `SyncError: repo is not allowlisted`.
- Wzorzec targetów per repo (funkcja `repo_target_specs`): `CLAUDE.md` =
  `shared.md` + `claude.md`, `AGENTS.md` = `shared.md` + `codex.md`
  (limit 32 KB na AGENTS.md).
- Szablon źródeł: `agent-rules/repos/generic/{shared,claude,codex}.md` oraz
  świeżo przepisany `agent-rules/repos/tsignal-5.0/` jako wzór stylu
  (gotchas > reguły, twarde tylko granice bezpieczeństwa).

## Kroki

1. **Źródła**: utwórz `agent-rules/repos/tsu/{shared.md,claude.md,codex.md}`
   i `agent-rules/repos/watchf/{shared.md,claude.md,codex.md}`.
   - Treść destyluj z ISTNIEJĄCYCH `AGENTS.md`/`CLAUDE.md` obu repo (to jest
     dziś jedyna prawda o ich niezmiennikach) + z ich `IDEA_BOX`/`design/` gdy
     coś jest ewidentnie load-bearing.
   - Styl wg artykułu Thariqa: krótkie "what this is", twarde granice tylko
     tam gdzie load-bearing (TSU: arm-lease/interlock, FUT nigdy na IBKR,
     dead-man cockpit ADR-009; WatchF: advisory-only wobec Tsignal, CDP
     fleet), reszta jako judgment + gotchas + wskaźniki progressive
     disclosure.
   - ZAKAZ reintrodukcji "LLM agents never touch broker API" — obowiązuje
     model code-vs-trigger; jeśli trzeba, linkuj
     `agent-rules/refs/paper-live-parity.md`.
2. **Allowlista**: w `sync_agent_rules.py` dodaj wpisy `RepoRuleSet` dla
   `D:/APPS/TSU` (slug `tsu`) i `D:/APPS/WatchF` (slug `watchf`) oraz slugi do
   `TIER1_REPO_SLUGS`. Odwzoruj istniejący konstruktor 1:1 (spójrz na wpis
   `tsignal-5.0`).
3. **Init + write**:
   `python scripts/sync_agent_rules.py --init-managed-blocks --repo D:/APPS/TSU --repo D:/APPS/WatchF`
   potem `--diff`, przegląd, potem `--write`. Generator robi backupy do
   `%TEMP%/agent-rules-backups/`.
4. **Deduplikacja**: treść, która przeszła do bloku, wywal z części manualnej
   plików docelowych (wzorzec: Tsignal 2026-07-28 — komentarz-wskaźnik
   "edytuj w agent-rules, nie tu" zamiast duplikatu). Sekcje czysto lokalne
   (porty, ścieżki maszynowe) zostają POZA blokiem.
5. **Landing**:
   - `dotclaude-ecosystem`: commit źródła + allowlista, push na `main` (R0/R1,
     direct OK).
   - `TSU`: commit `AGENTS.md` + nowy `CLAUDE.md` na `master`, push.
   - `WatchF`: commit na `local/main`, push (uwaga na brudne drzewo — staguj
     TYLKO te dwa pliki).
6. **Walidacja**: `--check` musi być `clean` dla obu repo;
   `grep -rn "never touch broker" <oba repo>/AGENTS.md <oba>/CLAUDE.md` = 0
   trafień; AGENTS.md < 32 KB.

## Pułapki

- WatchF trunk to `local/main` — `git push` bez refspec działa (tracking jest),
  ale NIE twórz/nie pchaj `main`.
- Oba repo mają brudne drzewa robocze (unrelated pliki operatora) — nigdy
  `git add -A`.
- `sync_agent_rules.py --write` bez `--repo` dotyka też globalnych overlayów —
  to OK (idempotentne), ale nie commituj wtedy przypadkiem cudzych zmian w
  ecosystem-repo; sprawdź `git status` przed commitem.
- TSU nie miało `CLAUDE.md` — `--init-managed-blocks` go utworzy; upewnij się,
  że tytuł pliku (pierwsza linia poza blokiem) jest sensowny.
- Jeśli w przyszłości dojdzie repo `_shared` (apps-shared, trunk `master`),
  ten sam przepis działa — dziś poza zakresem.

## DoD

- `--check` clean dla `tsu-claude`, `tsu-codex`, `watchf-claude`,
  `watchf-codex`.
- Nowy model (parity/trigger) obecny w obu repo w obu plikach; zero śladów
  starej reguły.
- Committed + pushed w trzech repo, SHA w raporcie końcowym.
