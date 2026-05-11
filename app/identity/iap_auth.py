"""IAP for Agents — verify the X-Goog-IAP-JWT-Assertion header.

Google Identity-Aware Proxy signs every authenticated request with an ES256
JWT. The header name is `X-Goog-IAP-JWT-Assertion`.

Verification rules (Google's documented contract):
  * Algorithm: ES256.
  * Issuer: `https://cloud.google.com/iap`.
  * Audience: must match `IAP_EXPECTED_AUDIENCE`.
       For Cloud Run behind an external HTTPS LB + IAP:
       `/projects/PROJECT_NUMBER/global/backendServices/SERVICE_ID`
  * `exp` and `iat` validated by PyJWT.
  * Public keys: https://www.gstatic.com/iap/verify/public_key (PEM map by `kid`).

The module exposes a FastAPI dependency `verify_iap_jwt` that returns the
verified claims or raises 401/403. Verification is **off** when
`IAP_REQUIRED=false` (local dev) — but a misconfigured deployment with
`IAP_REQUIRED=true` and no audience set will fail closed.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, Request, status

from app.config import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

_IAP_KEYS_URL = "https://www.gstatic.com/iap/verify/public_key"
_IAP_ISSUER = "https://cloud.google.com/iap"
_IAP_HEADER = "x-goog-iap-jwt-assertion"

_KEY_CACHE: dict[str, str] = {}
_KEY_CACHE_FETCHED_AT: float = 0.0
_KEY_CACHE_TTL_SECONDS: float = 60 * 60  # 1 hour


def _refresh_keys(client: httpx.Client | None = None) -> None:
    """Fetch (or refresh) the IAP public-key map. Best-effort with TTL."""
    global _KEY_CACHE, _KEY_CACHE_FETCHED_AT
    own_client = client is None
    c = client or httpx.Client(timeout=5.0)
    try:
        resp = c.get(_IAP_KEYS_URL)
        resp.raise_for_status()
        keys = resp.json()
        if not isinstance(keys, dict):
            raise ValueError("IAP key endpoint returned non-dict payload")
        _KEY_CACHE = {str(k): str(v) for k, v in keys.items()}
        _KEY_CACHE_FETCHED_AT = time.time()
        logger.info("iap.keys_refreshed", count=len(_KEY_CACHE))
    finally:
        if own_client:
            c.close()


def _get_signing_key(kid: str) -> str:
    """Return the PEM for a `kid`, refreshing the cache when stale or missing."""
    now = time.time()
    if (
        not _KEY_CACHE
        or now - _KEY_CACHE_FETCHED_AT > _KEY_CACHE_TTL_SECONDS
        or kid not in _KEY_CACHE
    ):
        _refresh_keys()
    if kid not in _KEY_CACHE:
        raise jwt.PyJWTError(f"Unknown IAP signing key id: {kid}")
    return _KEY_CACHE[kid]


def verify_iap_token(token: str, *, expected_audience: str) -> dict[str, Any]:
    """Verify a single IAP JWT. Raises `jwt.PyJWTError` on any failure."""
    if not token:
        raise jwt.PyJWTError("empty IAP assertion")

    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    alg = header.get("alg")
    if alg != "ES256":
        raise jwt.PyJWTError(f"Unexpected alg {alg!r}; IAP signs with ES256")
    if not kid:
        raise jwt.PyJWTError("IAP JWT missing 'kid' header")

    signing_key = _get_signing_key(kid)
    claims = jwt.decode(
        token,
        signing_key,
        algorithms=["ES256"],
        audience=expected_audience,
        issuer=_IAP_ISSUER,
        options={"require": ["exp", "iat", "sub", "email", "aud"]},
    )
    return claims


async def verify_iap_jwt(request: Request) -> dict[str, Any]:
    """FastAPI dependency that enforces IAP when `IAP_REQUIRED=true`.

    Returns the verified claims (sub, email, hd, ...) so route handlers can
    attribute audit log entries to the calling identity.

    In local dev with `IAP_REQUIRED=false`, returns a stub `{"sub": "local-dev"}`
    so handlers don't need to branch.
    """
    settings = get_settings()
    token = request.headers.get(_IAP_HEADER)

    if not settings.iap_required:
        if token and settings.iap_expected_audience:
            try:
                return verify_iap_token(token, expected_audience=settings.iap_expected_audience)
            except jwt.PyJWTError as exc:
                logger.warning("iap.verify_soft_failed", error=str(exc))
        return {"sub": "local-dev", "email": "local-dev@example.com", "iap_enforced": False}

    if not settings.iap_expected_audience:
        logger.error("iap.misconfigured_no_audience")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="IAP_REQUIRED=true but IAP_EXPECTED_AUDIENCE is empty.",
        )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing IAP assertion header.",
        )

    try:
        claims = verify_iap_token(token, expected_audience=settings.iap_expected_audience)
    except jwt.PyJWTError as exc:
        logger.warning("iap.verify_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid IAP assertion: {exc}",
        ) from exc

    claims["iap_enforced"] = True
    return claims
