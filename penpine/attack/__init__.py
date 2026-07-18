"""Penpine L4a attack core & contracts."""

from penpine.attack.analyze import Analysis, analyze
from penpine.attack.example import ECHO_MODULE, EchoGenerator, EchoValidator
from penpine.attack.exceptions import AttackConfigError, AttackError
from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import (
    Confidence,
    Finding,
    InjectionPoint,
    Payload,
    TestCase,
)
from penpine.attack.module import AttackModule
from penpine.attack.modules import BUILTIN_MODULES, register_builtins
from penpine.attack.registry import (
    clear,
    get,
    list_modules,
    register,
    unregister,
)
from penpine.attack.results import Attempt, Report
from penpine.attack.runner import Runner
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator
from penpine.attack.websocket import (
    WebSocketSender,
    run_ws_attack,
    run_ws_attack_sync,
    ws_injection_points,
    ws_message_request,
)

__all__ = [
    "InjectionPoint",
    "Payload",
    "TestCase",
    "Finding",
    "Confidence",
    "AttackType",
    "PayloadGenerator",
    "Validator",
    "AttackModule",
    "register",
    "get",
    "list_modules",
    "unregister",
    "clear",
    "EchoGenerator",
    "EchoValidator",
    "ECHO_MODULE",
    "AttackError",
    "AttackConfigError",
    "analyze",
    "Analysis",
    "Attempt",
    "Report",
    "Runner",
    "register_builtins",
    "BUILTIN_MODULES",
    "WebSocketSender",
    "run_ws_attack",
    "run_ws_attack_sync",
    "ws_injection_points",
    "ws_message_request",
]
