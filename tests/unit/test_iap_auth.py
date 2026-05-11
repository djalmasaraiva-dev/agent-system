"""Tests for IAP JWT verification.

We sign tokens with a generated EC P-256 key, then patch the IAP key cache so
the verifier finds our public PEM by `kid`. This exercises the real PyJWT path
end-to-end without hitting Google's key endpoint.
"""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.identity import iap_auth


@pytest.fixture
def signing_keypair() -> tuple[Any, str]:
    """Generate an EC P-256 key, return (private_key, public_pem)."""
    private = ec.generate_private_key(ec.SECP256R1())
    public_pem = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private, public_pem


@pytest.fixture
def patched_keys(monkeypatch: pytest.MonkeyPatch, signing_keypair):
    _, public_pem = signing_keypair
    monkeypatch.setattr(iap_auth, "_KEY_CACHE", {"test-kid": public_pem})
    monkeypatch.setattr(iap_auth, "_KEY_CACHE_FETCHED_AT", time.time())
    monkeypatch.setattr(iap_auth, "_refresh_keys", lambda *a, **k: None)
    yield


def _sign(private, *, audience: str, kid: str = "test-kid", **claims: Any) -> str:
    payload: dict[str, Any] = {
        "iss": "https://cloud.google.com/iap",
        "aud": audience,
        "sub": "accounts.google.com:118000000000000000001",
        "email": "user@example.com",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
    }
    payload.update(claims)
    return jwt.encode(payload, private, algorithm="ES256", headers={"kid": kid})


def test_verify_iap_token_happy_path(signing_keypair, patched_keys) -> None:
    private, _ = signing_keypair
    aud = "/projects/12345/global/backendServices/678"
    token = _sign(private, audience=aud)
    claims = iap_auth.verify_iap_token(token, expected_audience=aud)
    assert claims["email"] == "user@example.com"
    assert claims["aud"] == aud


def test_verify_iap_token_wrong_audience_rejected(signing_keypair, patched_keys) -> None:
    private, _ = signing_keypair
    token = _sign(private, audience="/projects/12345/global/backendServices/wrong")
    with pytest.raises(jwt.InvalidAudienceError):
        iap_auth.verify_iap_token(
            token, expected_audience="/projects/12345/global/backendServices/right"
        )


def test_verify_iap_token_expired_rejected(signing_keypair, patched_keys) -> None:
    private, _ = signing_keypair
    aud = "/projects/12345/global/backendServices/678"
    token = _sign(private, audience=aud, iat=int(time.time()) - 600, exp=int(time.time()) - 60)
    with pytest.raises(jwt.ExpiredSignatureError):
        iap_auth.verify_iap_token(token, expected_audience=aud)


def test_verify_iap_token_wrong_issuer_rejected(signing_keypair, patched_keys) -> None:
    private, _ = signing_keypair
    aud = "/projects/12345/global/backendServices/678"
    token = _sign(private, audience=aud, iss="https://malicious.example/issuer")
    with pytest.raises(jwt.InvalidIssuerError):
        iap_auth.verify_iap_token(token, expected_audience=aud)


def test_verify_iap_token_unknown_kid_refreshes(monkeypatch, signing_keypair) -> None:
    private, public_pem = signing_keypair
    aud = "/projects/12345/global/backendServices/678"
    token = _sign(private, audience=aud, kid="rotated-kid")

    refresh_calls = {"n": 0}

    def fake_refresh(*_a, **_k) -> None:
        refresh_calls["n"] += 1
        iap_auth._KEY_CACHE["rotated-kid"] = public_pem
        iap_auth._KEY_CACHE_FETCHED_AT = time.time()

    monkeypatch.setattr(iap_auth, "_KEY_CACHE", {})
    monkeypatch.setattr(iap_auth, "_KEY_CACHE_FETCHED_AT", 0.0)
    monkeypatch.setattr(iap_auth, "_refresh_keys", fake_refresh)

    claims = iap_auth.verify_iap_token(token, expected_audience=aud)
    assert claims["aud"] == aud
    assert refresh_calls["n"] >= 1
