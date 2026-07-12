import penpine
from penpine.flow import (
    Flow,
    FlowContext,
    FlowError,
    FlowResult,
    Recovery,
    Step,
    StepError,
    StepOutcome,
    StepResult,
)


def test_flow_package_reexports():
    assert all(
        obj is not None
        for obj in (
            Flow,
            FlowContext,
            Step,
            Recovery,
            StepOutcome,
            StepResult,
            FlowResult,
            FlowError,
            StepError,
        )
    )


def test_top_level_exports():
    assert penpine.Flow is Flow
    assert penpine.Step is Step
    assert "Flow" in penpine.__all__
    assert "Step" in penpine.__all__
