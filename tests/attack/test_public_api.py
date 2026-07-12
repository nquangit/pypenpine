from penpine.attack import (
    ECHO_MODULE,
    AttackConfigError,
    AttackError,
    AttackModule,
    Confidence,
    Finding,
    InjectionPoint,
    Payload,
    PayloadGenerator,
    TestCase,
    Validator,
    clear,
    get,
    list_modules,
    register,
    unregister,
)


def test_public_exports_exist():
    assert all(
        [
            InjectionPoint,
            Payload,
            TestCase,
            Finding,
            Confidence,
            PayloadGenerator,
            Validator,
            AttackModule,
            register,
            get,
            list_modules,
            unregister,
            clear,
            ECHO_MODULE,
            AttackError,
            AttackConfigError,
        ]
    )


def test_runner_results_exported():
    from penpine.attack import Attempt, Report, Runner

    assert all([Runner, Report, Attempt])


def test_attacktype_is_exported():
    import penpine.attack as A
    from penpine.attack.types import AttackType

    assert A.AttackType is AttackType
    assert "AttackType" in A.__all__


def test_attacktype_top_level():
    import penpine
    from penpine.attack.types import AttackType

    assert penpine.AttackType is AttackType
