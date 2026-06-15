"""Penpine L4d built-in attack modules. No import-time registration."""
from penpine.attack.modules.sqli import (
    SqliGenerator, SqliValidator, SQLI_PAYLOADS, SQLI_NUMERIC_PAYLOADS,
    SQL_ERROR_SIGNATURES, SQLI_MODULE,
)
from penpine.attack.modules.xss import (
    XssGenerator, XssValidator, XSS_PAYLOAD_TEMPLATES, XSS_MODULE,
)
from penpine.attack.modules.traversal import (
    TraversalGenerator, TraversalValidator, TRAVERSAL_PAYLOADS,
    TRAVERSAL_SIGNATURES, TRAVERSAL_MODULE,
)
from penpine.attack.modules.redirect import (
    RedirectGenerator, RedirectValidator, REDIRECT_PAYLOADS, CANARY_HOST, REDIRECT_MODULE,
)
from penpine.attack.registry import register

BUILTIN_MODULES = [SQLI_MODULE, XSS_MODULE, TRAVERSAL_MODULE, REDIRECT_MODULE]


def register_builtins(*, replace=True) -> None:
    """Register all built-in attack modules into the global registry (idempotent)."""
    for module in BUILTIN_MODULES:
        register(module, replace=replace)


__all__ = [
    "SqliGenerator", "SqliValidator", "SQLI_PAYLOADS", "SQLI_NUMERIC_PAYLOADS",
    "SQL_ERROR_SIGNATURES", "SQLI_MODULE",
    "XssGenerator", "XssValidator", "XSS_PAYLOAD_TEMPLATES", "XSS_MODULE",
    "TraversalGenerator", "TraversalValidator", "TRAVERSAL_PAYLOADS",
    "TRAVERSAL_SIGNATURES", "TRAVERSAL_MODULE",
    "RedirectGenerator", "RedirectValidator", "REDIRECT_PAYLOADS", "CANARY_HOST",
    "REDIRECT_MODULE",
    "BUILTIN_MODULES", "register_builtins",
]
