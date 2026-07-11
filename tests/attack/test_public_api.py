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
