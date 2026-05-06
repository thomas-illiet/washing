"""OIDC authentication helpers."""

from internal.infra.auth.oidc import (
    AuthenticatedPrincipal,
    OIDCAuthenticationError,
    authorize_request,
    clear_oidc_caches,
    oidc_docs_shell_is_public,
    swagger_oauth_config,
    swagger_security_scheme,
)
from internal.infra.auth.settings import OIDCSettings, get_oidc_settings

__all__ = [
    "AuthenticatedPrincipal",
    "OIDCAuthenticationError",
    "OIDCSettings",
    "authorize_request",
    "clear_oidc_caches",
    "get_oidc_settings",
    "oidc_docs_shell_is_public",
    "swagger_oauth_config",
    "swagger_security_scheme",
]
