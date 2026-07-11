"""Penpine L4d built-in attack modules. No import-time registration."""

from penpine.attack.modules.differential import (
    BOOLEAN_PAYLOAD_PAIRS,
    BOOLEAN_SQLI_MODULE,
    TIME_PAYLOAD_TEMPLATES,
    TIME_SQLI_MODULE,
    BooleanSqliModule,
    DifferentialModule,
    TimeSqliModule,
)
from penpine.attack.modules.redirect import (
    CANARY_HOST,
    REDIRECT_MODULE,
    REDIRECT_PAYLOADS,
    RedirectGenerator,
    RedirectValidator,
)
from penpine.attack.modules.sqli import (
    SQL_ERROR_SIGNATURES,
    SQLI_MODULE,
    SQLI_NUMERIC_PAYLOADS,
    SQLI_PAYLOADS,
    SqliGenerator,
    SqliValidator,
)
from penpine.attack.modules.traversal import (
    TRAVERSAL_MODULE,
    TRAVERSAL_PAYLOADS,
    TRAVERSAL_SIGNATURES,
    TraversalGenerator,
    TraversalValidator,
)
from penpine.attack.modules.xss import (
    XSS_MODULE,
    XSS_PAYLOAD_TEMPLATES,
    XssGenerator,
    XssValidator,
)
from penpine.attack.registry import register

BUILTIN_MODULES = [SQLI_MODULE, XSS_MODULE, TRAVERSAL_MODULE, REDIRECT_MODULE]
DIFFERENTIAL_MODULES = [BOOLEAN_SQLI_MODULE, TIME_SQLI_MODULE]


def register_builtins(*, replace=True) -> None:
    """Register all built-in attack modules into the global registry (idempotent)."""
    for module in (*BUILTIN_MODULES, *DIFFERENTIAL_MODULES):
        register(module, replace=replace)


__all__ = [
    "SqliGenerator",
    "SqliValidator",
    "SQLI_PAYLOADS",
    "SQLI_NUMERIC_PAYLOADS",
    "SQL_ERROR_SIGNATURES",
    "SQLI_MODULE",
    "XssGenerator",
    "XssValidator",
    "XSS_PAYLOAD_TEMPLATES",
    "XSS_MODULE",
    "TraversalGenerator",
    "TraversalValidator",
    "TRAVERSAL_PAYLOADS",
    "TRAVERSAL_SIGNATURES",
    "TRAVERSAL_MODULE",
    "RedirectGenerator",
    "RedirectValidator",
    "REDIRECT_PAYLOADS",
    "CANARY_HOST",
    "REDIRECT_MODULE",
    "BUILTIN_MODULES",
    "register_builtins",
    "DifferentialModule",
    "BooleanSqliModule",
    "TimeSqliModule",
    "BOOLEAN_SQLI_MODULE",
    "TIME_SQLI_MODULE",
    "DIFFERENTIAL_MODULES",
    "BOOLEAN_PAYLOAD_PAIRS",
    "TIME_PAYLOAD_TEMPLATES",
]
