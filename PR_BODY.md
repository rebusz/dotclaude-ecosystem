Conductor worker launches can leave Python/pytest descendants alive after a lane
ends, and slot counts alone do not prevent RAM exhaustion. This draft integrates
durable process ownership, Windows Job containment, pytest deadlines and RAM
reservations into the existing Conductor store/resource boundary. A default
read-only reaper report keeps all unidentified, protected or ambiguous processes.

Risk: R2. Source-only work; no installation, scheduled task, process termination,
ready/merge or production change. Root launch registration is durable; descendant
sampling is not an exhaustive birth-event log. Claude/Kimi version probes and the
GUI Python recovery helper now use the registered launcher. Direct Git helpers
remain outside the Python/pytest/agent process registry scope.

Validation: 34 stdlib reaper tests passed in the earlier run; Ruff and compileall
pass on the current source. Full local pytest did not start: the corrected
Conductor request failed before child creation with `session lookup failed`, and
current RAM admission reports 12.5125 GiB available, 7 GiB reserved, 4.5125 GiB
headroom vs a 6 GiB floor. See root RECEIPT.md. The refreshed real-process
dry-run read the full process table and registry: 603 KEEP, 0 WOULD_KILL,
39.155097 GiB RSS total; all 56 Python/pytest-name processes were KEEP. No process
was signaled. RSS sums are not guaranteed physical memory savings. Review/CI
gates are not claimed complete.

This body is prepared locally. Root RECEIPT.md records whether the branch/PR was
actually published; this file alone is not a publication receipt.
