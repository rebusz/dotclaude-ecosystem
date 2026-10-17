#!/usr/bin/env python3
"""One definition of what a secret looks like, for every detector in the repo.

Before this module there were five independent detectors -- in
sync_ecosystem_context, terminal_evidence, curator_claims,
implementation_review_packet and the distill-repo validator -- each with a
different pattern set and different gaps (audit 2026-09-09, F14). Measured:

  * the review-packet gate, the one documented as failing closed before code
    leaves the box, missed every modern LLM key, `github_pat_` tokens, `.envrc`,
    `id_rsa`, keystores, JWTs and connection strings;
  * the context sync, which pushes to GitHub unattended, matched `sk-` only up
    to the next hyphen -- so `sk-proj-...` and `sk-ant-...` sailed through.

Every fix to one detector left four others wrong. Now there is one.

Two confidence classes, deliberately kept apart:

  HIGH_CONFIDENCE  token shapes with near-zero false positives. Consumers that
                   publish (the review packet, the context sync) FAIL CLOSED on
                   these: refuse, do not redact-and-continue.
  ASSIGNMENT       `password = ...`-style key/value pairs. Common in legitimate
                   code (`password = getpass()`), so these are redacted in
                   evidence and transcripts but never block a code diff.

Pure and dependency-free: imported from hooks and from standalone skills.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

HIGH_CONFIDENCE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key block",
     re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    # `sk-`, `sk-proj-`, `sk-ant-api03-`: hyphens belong INSIDE the class. The
    # context sync's old `sk-[A-Za-z0-9_]{16,}` stopped at the first hyphen.
    ("provider API key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("JSON web token",
     re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("credentials in URL",
     re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@\"'<>]+:[^/\s@\"'<>]{3,}@")),
)

ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key|auth[_-]?token|authorization|bearer|"
    r"password|passwd|secret|token)\b(\s*[\"']?\s*[:=]\s*[\"']?)([^\s\"',;&]{6,})"
)

SENSITIVE_PATHS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:^|/)\.env(?:rc)?(?:\.[^/]*)?$", re.IGNORECASE),        # .env, .env.local, .envrc
    re.compile(r"\.env$", re.IGNORECASE),                                  # config/prod.env
    re.compile(r"\.(?:pem|key|p12|pfx|keystore|jks|ppk)$", re.IGNORECASE),
    re.compile(r"(?:^|/)id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?$", re.IGNORECASE),
    re.compile(r"(?:^|/)\.(?:npmrc|netrc|pypirc|git-credentials)$", re.IGNORECASE),
    re.compile(r"(?:^|/)(?:credentials?|secrets?)(?:[._-][^/]*)?\.(?:json|ya?ml|toml|txt|ini|cfg)$",
               re.IGNORECASE),
    re.compile(r"(?:^|/)secrets?/", re.IGNORECASE),
    re.compile(r"(?:^|/)(?:auth|service[-_]?account[^/]*)\.json$", re.IGNORECASE),
    re.compile(r"\.token$", re.IGNORECASE),
    re.compile(r"(?:^|/)cookies?\.(?:txt|json|sqlite)$", re.IGNORECASE),
)


def find_high_confidence(text: str) -> list[str]:
    """Labels of every high-confidence secret shape present in `text`."""
    return [label for label, pattern in HIGH_CONFIDENCE if pattern.search(text)]


def is_sensitive_path(path: str) -> bool:
    """True for files that should never leave the box, whatever they contain."""
    normalized = str(PurePosixPath(str(path).replace("\\", "/")))
    return any(pattern.search(normalized) for pattern in SENSITIVE_PATHS)


def redact_high_confidence(text: str, replacement: str = "[REDACTED]") -> tuple[str, int]:
    """Replace every high-confidence secret shape; return (text, replacements)."""
    total = 0
    for _label, pattern in HIGH_CONFIDENCE:
        text, count = pattern.subn(replacement, text)
        total += count
    return text, total


def redact_assignments(text: str) -> tuple[str, int]:
    """Replace the VALUE of `key = value` credential assignments, keep the key."""
    return ASSIGNMENT.subn(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


def redact(text: str) -> tuple[str, int]:
    """Both classes. For evidence, transcripts and logs -- never for gating."""
    text, high = redact_high_confidence(text)
    text, assigned = redact_assignments(text)
    return text, high + assigned
