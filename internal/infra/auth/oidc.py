"""Generic OIDC authentication and Swagger OpenAPI helpers."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import Request

from internal.infra.auth.settings import OIDCSettings, get_oidc_settings


_HTTP_TIMEOUT_SECONDS = 5.0
_METADATA_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = asyncio.Lock()


class OIDCAuthenticationError(Exception):
    """Raised when an incoming request cannot be authenticated or authorized."""

    def __init__(self, status_code: int, detail: str) -> None:
        """Store the HTTP status code and a readable error detail."""
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Normalized authenticated principal extracted from an OIDC token."""

    subject: str
    username: str | None
    roles: frozenset[str]

    def can_read(self, settings: OIDCSettings) -> bool:
        """Return whether the principal is allowed to consult protected routes."""
        return settings.oidc_user_role_name in self.roles or settings.oidc_admin_role_name in self.roles

    def can_write(self, settings: OIDCSettings) -> bool:
        """Return whether the principal is allowed to mutate or execute actions."""
        return settings.oidc_admin_role_name in self.roles


def clear_oidc_caches() -> None:
    """Clear OIDC settings and remote metadata caches for tests and reloads."""
    _METADATA_CACHE.clear()
    _JWKS_CACHE.clear()
    get_oidc_settings.cache_clear()


def oidc_docs_shell_is_public(request: Request, settings: OIDCSettings | None = None) -> bool:
    """Allow the docs HTML shell to load without a Bearer token in browsers."""
    settings = settings or get_oidc_settings()
    if not settings.oidc_enabled:
        return True
    if request.url.path != "/":
        return False
    accept = request.headers.get("accept", "")
    return "text/html" in accept.lower()


async def authorize_request(
    request: Request,
    *,
    required_role: str,
) -> AuthenticatedPrincipal | None:
    """Authorize one incoming HTTP request when OIDC is enabled."""
    settings = get_oidc_settings()
    if not settings.oidc_enabled:
        return None

    token = _extract_bearer_token(request.headers.get("authorization"))
    if token is None:
        raise OIDCAuthenticationError(status_code=401, detail="missing bearer token")

    claims = await _decode_token(token, settings)
    principal = _principal_from_claims(claims)
    # Expose the validated principal to downstream handlers without reparsing the token.
    request.state.authenticated_principal = principal

    if required_role == "user" and principal.can_read(settings):
        return principal
    if required_role == "admin" and principal.can_write(settings):
        return principal
    raise OIDCAuthenticationError(status_code=403, detail="insufficient role")


def swagger_security_scheme() -> dict[str, Any] | None:
    """Return an OpenAPI security scheme for Swagger when OIDC is enabled."""
    settings = get_oidc_settings()
    if not settings.oidc_enabled:
        return None

    scopes = {scope: scope for scope in settings.oidc_swagger_scopes}
    try:
        metadata = _load_provider_metadata_sync(settings)
    except OIDCAuthenticationError:
        # Discovery can be down while manual Bearer auth still works.
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "OIDC Bearer token. Discovery is currently unavailable.",
        }

    metadata_issuer = metadata.get("issuer")
    authorization_endpoint = _rewrite_provider_endpoint(
        metadata.get("authorization_endpoint"),
        metadata_issuer,
        settings.oidc_issuer_url,
    )
    token_endpoint = _rewrite_provider_endpoint(
        metadata.get("token_endpoint"),
        metadata_issuer,
        settings.oidc_issuer_url,
    )
    if not authorization_endpoint or not token_endpoint:
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "OIDC Bearer token.",
        }

    return {
        "type": "oauth2",
        "flows": {
            "authorizationCode": {
                "authorizationUrl": authorization_endpoint,
                "tokenUrl": token_endpoint,
                "scopes": scopes,
            }
        },
        "description": "OIDC Authorization Code flow. Mutations still require the admin role claim.",
    }


def swagger_oauth_config() -> dict[str, Any] | None:
    """Return Swagger UI OAuth initialization settings when OIDC is enabled."""
    settings = get_oidc_settings()
    if not settings.oidc_enabled or not settings.oidc_swagger_client_id:
        return None
    config: dict[str, Any] = {
        "clientId": settings.oidc_swagger_client_id,
        "usePkceWithAuthorizationCodeGrant": settings.oidc_swagger_use_pkce,
    }
    if settings.oidc_swagger_scopes:
        config["scopes"] = " ".join(settings.oidc_swagger_scopes)
    return config


def _extract_bearer_token(authorization: str | None) -> str | None:
    """Parse a standard Authorization header and return the Bearer token."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise OIDCAuthenticationError(status_code=401, detail="invalid authorization header")
    return token


async def _decode_token(token: str, settings: OIDCSettings) -> dict[str, Any]:
    """Validate a JWT access token against the configured OIDC issuer."""
    metadata = await _load_provider_metadata(settings)
    # Prefer the public issuer when discovery comes from an internal Docker hostname.
    issuer = settings.oidc_issuer_url or metadata.get("issuer")
    jwks_uri = metadata.get("jwks_uri")
    if not issuer or not jwks_uri:
        raise OIDCAuthenticationError(status_code=503, detail="authentication provider unavailable")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise OIDCAuthenticationError(status_code=401, detail="invalid bearer token") from exc

    algorithm = header.get("alg")
    key_id = header.get("kid")
    if not algorithm or algorithm == "none":
        raise OIDCAuthenticationError(status_code=401, detail="invalid bearer token")
    if not key_id:
        raise OIDCAuthenticationError(status_code=401, detail="missing key identifier")

    jwk = await _load_jwk(settings, jwks_uri, key_id)
    try:
        signing_key = jwt.PyJWK.from_dict(jwk, algorithm=algorithm).key
    except jwt.InvalidKeyError as exc:
        raise OIDCAuthenticationError(status_code=401, detail="invalid signing key") from exc

    try:
        claims = jwt.decode(
            token,
            key=signing_key,
            algorithms=[algorithm],
            issuer=issuer,
            # RBAC here is role-based only, so audience is intentionally ignored.
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError as exc:
        raise OIDCAuthenticationError(status_code=401, detail="expired bearer token") from exc
    except jwt.InvalidTokenError as exc:
        raise OIDCAuthenticationError(status_code=401, detail="invalid bearer token") from exc

    if not isinstance(claims, dict):
        raise OIDCAuthenticationError(status_code=401, detail="invalid bearer token")
    return claims


async def _load_provider_metadata(settings: OIDCSettings) -> dict[str, Any]:
    """Load and cache the OIDC discovery document."""
    discovery_url = settings.discovery_url
    if not discovery_url:
        raise OIDCAuthenticationError(status_code=503, detail="authentication provider unavailable")

    async with _CACHE_LOCK:
        # Keep discovery hot across requests to avoid one network hop per token.
        cached = _METADATA_CACHE.get(discovery_url)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]

    payload = await _fetch_json(discovery_url)
    if not isinstance(payload, dict):
        raise OIDCAuthenticationError(status_code=503, detail="authentication provider unavailable")

    async with _CACHE_LOCK:
        _METADATA_CACHE[discovery_url] = (
            time.monotonic() + settings.oidc_jwks_cache_ttl_seconds,
            payload,
        )
    return payload


def _load_provider_metadata_sync(settings: OIDCSettings) -> dict[str, Any]:
    """Synchronously load and cache the OIDC discovery document."""
    discovery_url = settings.discovery_url
    if not discovery_url:
        raise OIDCAuthenticationError(status_code=503, detail="authentication provider unavailable")

    cached = _METADATA_CACHE.get(discovery_url)
    if cached is not None and cached[0] > time.monotonic():
        return cached[1]

    payload = _fetch_json_sync(discovery_url)
    if not isinstance(payload, dict):
        raise OIDCAuthenticationError(status_code=503, detail="authentication provider unavailable")

    _METADATA_CACHE[discovery_url] = (
        time.monotonic() + settings.oidc_jwks_cache_ttl_seconds,
        payload,
    )
    return payload


async def _load_jwk(settings: OIDCSettings, jwks_uri: str, key_id: str) -> dict[str, Any]:
    """Load and cache the JSON Web Key identified by the token header."""
    async with _CACHE_LOCK:
        cached = _JWKS_CACHE.get(jwks_uri)
        if cached is not None and cached[0] > time.monotonic():
            jwks = cached[1]
        else:
            jwks = {}

    if not jwks:
        # Refresh the JWKS only when the cache is cold or expired.
        payload = await _fetch_json(jwks_uri)
        if not isinstance(payload, dict):
            raise OIDCAuthenticationError(status_code=503, detail="authentication provider unavailable")
        async with _CACHE_LOCK:
            _JWKS_CACHE[jwks_uri] = (
                time.monotonic() + settings.oidc_jwks_cache_ttl_seconds,
                payload,
            )
            jwks = payload

    keys = jwks.get("keys")
    if not isinstance(keys, list):
        raise OIDCAuthenticationError(status_code=503, detail="authentication provider unavailable")

    for candidate in keys:
        if isinstance(candidate, dict) and candidate.get("kid") == key_id:
            return candidate
    raise OIDCAuthenticationError(status_code=401, detail="unknown signing key")


async def _fetch_json(url: str) -> Any:
    """Fetch a JSON payload from the configured OIDC provider."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise OIDCAuthenticationError(status_code=503, detail="authentication provider unavailable") from exc

    try:
        return response.json()
    except ValueError as exc:
        raise OIDCAuthenticationError(status_code=503, detail="authentication provider unavailable") from exc


def _fetch_json_sync(url: str) -> Any:
    """Synchronously fetch a JSON payload for OpenAPI generation."""
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise OIDCAuthenticationError(status_code=503, detail="authentication provider unavailable") from exc

    try:
        return response.json()
    except ValueError as exc:
        raise OIDCAuthenticationError(status_code=503, detail="authentication provider unavailable") from exc


def _principal_from_claims(claims: dict[str, Any]) -> AuthenticatedPrincipal:
    """Normalize the validated claims payload to one principal object."""
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise OIDCAuthenticationError(status_code=401, detail="invalid bearer token")

    username = claims.get("preferred_username")
    if not isinstance(username, str):
        username = claims.get("email")
    if not isinstance(username, str):
        username = None

    roles = _extract_roles(claims, get_oidc_settings().oidc_role_claim_paths)
    return AuthenticatedPrincipal(subject=subject, username=username, roles=frozenset(roles))


def _extract_roles(claims: dict[str, Any], paths: list[str]) -> set[str]:
    """Extract role names from one or more configurable claim paths."""
    roles: set[str] = set()
    for path in paths:
        for value in _extract_path_values(claims, path.split(".")):
            if isinstance(value, str) and value:
                roles.add(value)
            elif isinstance(value, list):
                roles.update(item for item in value if isinstance(item, str) and item)
    return roles


def _extract_path_values(value: Any, segments: list[str]) -> list[Any]:
    """Walk a dotted path with optional '*' wildcards across dictionaries."""
    if not segments:
        return [value]
    if value is None:
        return []

    head, *tail = segments
    if head == "*":
        # Wildcards let one path match maps like resource_access.*.roles.
        children: list[Any]
        if isinstance(value, dict):
            children = list(value.values())
        elif isinstance(value, list):
            children = list(value)
        else:
            return []
        values: list[Any] = []
        for child in children:
            values.extend(_extract_path_values(child, tail))
        return values

    if isinstance(value, dict) and head in value:
        return _extract_path_values(value[head], tail)
    return []


def _rewrite_provider_endpoint(
    endpoint: Any,
    metadata_issuer: Any,
    public_issuer: str | None,
) -> str | None:
    """Rewrite discovery endpoints from the internal issuer to the public issuer."""
    if not isinstance(endpoint, str):
        return None
    if not isinstance(metadata_issuer, str) or not public_issuer:
        return endpoint
    if endpoint.startswith(metadata_issuer.rstrip("/")):
        # Browsers must see the public URL even if discovery was loaded from an internal host.
        return f"{public_issuer.rstrip('/')}{endpoint[len(metadata_issuer.rstrip('/')):]}"
    return endpoint
