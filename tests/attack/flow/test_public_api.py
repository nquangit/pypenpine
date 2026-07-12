import penpine
from penpine.attack.flow import (
    CrossUserModule,
    FlowAttackModule,
    FlowAttempt,
    FlowFinding,
    FlowReport,
    FlowRunner,
    FlowVariant,
    SkipStepModule,
    drop_step,
    seed_context,
    swap_actor,
)


def test_reexports_present():
    for obj in (
        FlowRunner,
        FlowAttackModule,
        FlowVariant,
        FlowFinding,
        FlowAttempt,
        FlowReport,
        SkipStepModule,
        CrossUserModule,
        drop_step,
        swap_actor,
        seed_context,
    ):
        assert obj is not None


def test_top_level_flowrunner():
    assert penpine.FlowRunner is FlowRunner
    assert "FlowRunner" in penpine.__all__
