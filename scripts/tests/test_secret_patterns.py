"""Shared secret vectors, asserted against the one detector and every consumer.

Five detectors used to disagree about what a secret looks like (audit F14).
The defence against that recurring is not a better regex -- it is one set of
vectors that every consumer must agree on, so a gap in any of them fails here.

Every vector is assembled at runtime. A token-shaped literal in this file would
trip GitHub push protection on a public repository, be reported as a leak by
secret scanners, and -- the reason that matters most -- make this repository's
own review-packet gate refuse to publish the pull request that adds it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import secret_patterns as sp  # noqa: E402


def _j(*parts: str) -> str:
    return "".join(parts)


# Shapes that must be caught everywhere, and refused by anything that publishes.
HIGH_CONFIDENCE_VECTORS = {
    "rsa private key": _j("-----BEGIN RSA ", "PRIVATE KEY-----"),
    "openssh private key": _j("-----BEGIN OPENSSH ", "PRIVATE KEY-----"),
    "pgp private key": _j("-----BEGIN PGP ", "PRIVATE KEY BLOCK-----"),
    "pkcs8 private key": _j("-----BEGIN ", "PRIVATE KEY-----"),
    "aws access key": _j("AK", "IA", "Q" * 16),
    "github classic token": _j("gh", "p_", "a1B2" * 9),
    "github fine-grained": _j("github", "_pat_", "A" * 22, "_", "b" * 30),
    "openai project key": _j("sk", "-proj-", "x" * 40),
    "anthropic key": _j("sk", "-ant-api03-", "y" * 40),
    "bare provider key": _j("sk", "-", "z" * 48),
    "google api key": _j("AI", "za", "S" * 35),
    "slack bot token": _j("xo", "xb-", "1234567890-abcdefghij"),
    "jwt": _j("ey", "JhbGciOiJIUzI1NiJ9", ".", "ey", "JzdWIiOiIxMjM0NSJ9", ".", "sig_abcdefgh123"),
    "connection string": _j("postgres://app", ":", "hunter2x", "@db.internal:5432/app"),
}

# Things that look adjacent but are not secrets; a detector that flags these
# trains people to ignore it.
NOT_SECRETS = {
    "hyphenated word": "risk-adjusted-returns-calculation-module",
    "sklearn": "pip install sk-learn",
    "plain url": "https://github.com/rebusz/dotclaude-ecosystem",
    "public key": _j("-----BEGIN ", "PUBLIC KEY-----"),
    "short akia": _j("AK", "IA", "short"),
    "prose": "the token budget is 4k and the password policy is documented",
}

SENSITIVE = [".env", "config/.env.local", ".envrc", "config/prod.env", "id_rsa",
             "keys/id_ed25519", "app.keystore", "certs/server.pem", ".npmrc", ".netrc",
             ".pypirc", "secrets/db.txt", "credentials.txt", "service-account-prod.json",
             "auth.json", "github.token", "cookies.txt", "config\\secrets.yaml"]
NOT_SENSITIVE = ["scripts/secret_patterns.py", "scripts/tests/test_secret_patterns.py",
                 "docs/environment.md", "design/audits/credentials-audit.md", "README.md",
                 "src/keyboard.py", "lib/tokenizer.py", "envoy.yaml"]


@pytest.mark.parametrize("name", sorted(HIGH_CONFIDENCE_VECTORS))
def test_every_high_confidence_vector_is_found(name: str) -> None:
    text = f"context before {HIGH_CONFIDENCE_VECTORS[name]} context after"
    assert sp.find_high_confidence(text), name


@pytest.mark.parametrize("name", sorted(HIGH_CONFIDENCE_VECTORS))
def test_every_high_confidence_vector_is_redacted(name: str) -> None:
    secret = HIGH_CONFIDENCE_VECTORS[name]
    redacted, count = sp.redact_high_confidence(f"x {secret} y")
    assert count >= 1
    # The private-key header is itself the marker; for everything else no
    # recognisable remnant of the secret may survive.
    assert secret not in redacted


@pytest.mark.parametrize("name", sorted(NOT_SECRETS))
def test_adjacent_text_is_not_a_high_confidence_secret(name: str) -> None:
    assert sp.find_high_confidence(NOT_SECRETS[name]) == [], name


def test_the_old_sync_regex_gap_is_closed() -> None:
    """`sk-[A-Za-z0-9_]{16,}` stopped at the first hyphen: sk-proj / sk-ant passed."""
    for key in ("openai project key", "anthropic key"):
        assert "provider API key" in sp.find_high_confidence(HIGH_CONFIDENCE_VECTORS[key])


@pytest.mark.parametrize("path", SENSITIVE)
def test_sensitive_paths(path: str) -> None:
    assert sp.is_sensitive_path(path), path


@pytest.mark.parametrize("path", NOT_SENSITIVE)
def test_ordinary_paths(path: str) -> None:
    assert not sp.is_sensitive_path(path), path


def test_assignments_redact_the_value_and_keep_the_key() -> None:
    text = 'password = "correct-horse-battery" and api_key: abcdef123456'
    redacted, count = sp.redact_assignments(text)
    assert count == 2
    assert "correct-horse-battery" not in redacted and "abcdef123456" not in redacted
    assert "password" in redacted and "api_key" in redacted


def test_assignments_are_not_high_confidence() -> None:
    """They block nothing: `password = getpass()` is legitimate code."""
    assert sp.find_high_confidence("password = getpass.getpass()") == []


# ── Every consumer agrees with the detector ─────────────────────────────────
# One vector set, four consumers. A gap in any of them fails here, which is the
# whole point: the five detectors drifted precisely because nothing tied them.

import implementation_review_packet as packet  # noqa: E402
import sync_ecosystem_context as sync  # noqa: E402
import terminal_evidence  # noqa: E402

_DISTILL = _SCRIPTS.parent / "skills" / "distill-repo" / "scripts"
sys.path.insert(0, str(_DISTILL))
import validate_distilled_library as distill  # noqa: E402


@pytest.mark.parametrize("name", sorted(HIGH_CONFIDENCE_VECTORS))
def test_the_review_packet_refuses_every_vector(name: str) -> None:
    with pytest.raises(packet.PacketError, match="high-confidence secret"):
        packet._reject_secret_text(f"pytest output\n{HIGH_CONFIDENCE_VECTORS[name]}\n")


@pytest.mark.parametrize("path", SENSITIVE)
def test_the_review_packet_refuses_every_sensitive_path(path: str) -> None:
    with pytest.raises(packet.PacketError, match="sensitive path"):
        packet._reject_sensitive_content(f"M\t{path}", "")


@pytest.mark.parametrize("name", sorted(HIGH_CONFIDENCE_VECTORS))
def test_the_context_sync_refuses_every_vector(name: str) -> None:
    """It pushes to GitHub unattended; redact-and-continue is the wrong failure."""
    with pytest.raises(sync.SecretDetected):
        sync.sanitize(f"# memory note\n{HIGH_CONFIDENCE_VECTORS[name]}\n", source="note.md")


def test_the_context_sync_still_redacts_ordinary_detail() -> None:
    cleaned, count = sync.sanitize("see D:/APPS/Tsignal 5.0/scripts and password = hunter2abc")
    assert "hunter2abc" not in cleaned
    assert "D:/APPS" not in cleaned
    assert count >= 2


@pytest.mark.parametrize("name", sorted(HIGH_CONFIDENCE_VECTORS))
def test_terminal_evidence_redacts_every_vector(name: str) -> None:
    secret = HIGH_CONFIDENCE_VECTORS[name]
    assert secret not in terminal_evidence.redact_text(f"$ run\n{secret}\n")


@pytest.mark.parametrize("name", sorted(HIGH_CONFIDENCE_VECTORS))
def test_the_distill_validator_flags_every_vector(name: str) -> None:
    failures = distill._check_text_for_secrets(Path("SKILL.md"), HIGH_CONFIDENCE_VECTORS[name])
    assert failures, name
    # It reports by label; echoing the match would print the secret in CI logs.
    assert all(HIGH_CONFIDENCE_VECTORS[name] not in failure for failure in failures)
