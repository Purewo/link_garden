"""Unit tests for ``app.core.security``.

Covers the round-trip happy path for passwords and JWTs plus the load-bearing
security invariants:

* bcrypt verifies its own output and rejects mismatches.
* bcrypt's 72-byte truncation behaviour is consistent between hash and
  verify so a long password's verification never raises.
* :func:`encode_jwt` / :func:`decode_jwt` round-trip claims and attach
  ``iat`` + ``exp`` automatically.
* :func:`decode_jwt` rejects expired tokens, tampered signatures, the
  ``alg=none`` confusion attack, and any non-HS256 algorithm even when the
  payload looks otherwise valid.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

# Set required env BEFORE importing the security module — pydantic-settings
# validates ``JWT_SECRET`` at construction time.
os.environ.setdefault(
    "JWT_SECRET",
    "test-secret-do-not-use-in-prod-1234567890ab",
)
os.environ.setdefault("LG_ADMIN_PASSWORD", "abcdefgh")

import jwt as pyjwt  # noqa: E402
import pytest  # noqa: E402

from app.core.errors import Unauthorized  # noqa: E402
from app.core.security import (  # noqa: E402
    decode_jwt,
    encode_jwt,
    hash_password,
    verify_password,
)


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #


def test_hash_and_verify_round_trip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$2"), "expected a bcrypt hash prefix"
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_rejects_wrong_password() -> None:
    hashed = hash_password("right one")
    assert verify_password("wrong one", hashed) is False


def test_verify_handles_malformed_hash_without_raising() -> None:
    # A garbage hash must not bubble a ValueError out of bcrypt.
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_hash_is_salted() -> None:
    a = hash_password("same input")
    b = hash_password("same input")
    assert a != b, "bcrypt must include random salt"
    assert verify_password("same input", a)
    assert verify_password("same input", b)


def test_long_password_is_truncated_consistently() -> None:
    # Beyond bcrypt's 72-byte limit; hash + verify must agree on the cutoff.
    long_pw = "x" * 200
    hashed = hash_password(long_pw)
    # The first 72 bytes determine the hash; padding past that must still
    # verify (consistent truncation), and a different 72-byte prefix must not.
    assert verify_password(long_pw + "more padding", hashed) is True
    assert verify_password("y" * 200, hashed) is False


# --------------------------------------------------------------------------- #
# JWT encode / decode
# --------------------------------------------------------------------------- #


def test_encode_decode_round_trip() -> None:
    token = encode_jwt({"sub": "user-1", "role": "admin"})
    claims = decode_jwt(token)

    assert claims["sub"] == "user-1"
    assert claims["role"] == "admin"
    assert "iat" in claims and "exp" in claims
    assert claims["exp"] > claims["iat"]


def test_encode_attaches_iat_and_exp() -> None:
    before = int(time.time())
    token = encode_jwt({"sub": "u"}, ttl_seconds=60)
    claims = decode_jwt(token)
    after = int(time.time())

    assert before <= claims["iat"] <= after
    assert 55 <= (claims["exp"] - claims["iat"]) <= 65


def test_decode_rejects_expired_token() -> None:
    # ttl_seconds is honoured; we forge an explicit past-expiry claim instead
    # so we don't have to sleep.
    past = int((datetime.now(UTC) - timedelta(seconds=120)).timestamp())
    token = encode_jwt({"sub": "u", "iat": past - 60, "exp": past})

    with pytest.raises(Unauthorized) as excinfo:
        decode_jwt(token)
    assert excinfo.value.code == "unauthenticated"


def test_decode_rejects_tampered_signature() -> None:
    token = encode_jwt({"sub": "u"})
    # Flip the last char of the signature segment.
    head, payload, sig = token.split(".")
    tampered_sig = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    tampered = f"{head}.{payload}.{tampered_sig}"

    with pytest.raises(Unauthorized):
        decode_jwt(tampered)


def test_decode_rejects_alg_none_attack() -> None:
    """Unsigned tokens (``alg=none``) must never be accepted."""

    # Forge a token signed with ``alg=none`` (no signature). pyjwt refuses to
    # produce one without an explicit empty key, so we hand-craft.
    forged = pyjwt.encode({"sub": "u", "iat": 1, "exp": 9_999_999_999}, key="", algorithm="none")

    with pytest.raises(Unauthorized):
        decode_jwt(forged)


def test_decode_rejects_other_algorithms() -> None:
    """A valid token signed with HS512 must be rejected by the HS256-pinned decoder."""

    other = pyjwt.encode(
        {"sub": "u", "iat": 1, "exp": 9_999_999_999},
        key=os.environ["JWT_SECRET"],
        algorithm="HS512",
    )

    with pytest.raises(Unauthorized):
        decode_jwt(other)


def test_decode_requires_exp_claim() -> None:
    """A signed-but-eternal token (no ``exp``) must be rejected.

    The decoder is configured with ``options={'require': ['exp', 'iat']}``;
    omitting either claim raises :class:`Unauthorized`.
    """

    bare = pyjwt.encode(
        {"sub": "u", "iat": 1},
        key=os.environ["JWT_SECRET"],
        algorithm="HS256",
    )

    with pytest.raises(Unauthorized):
        decode_jwt(bare)
