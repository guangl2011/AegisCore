"""FSM property tests: no descent-skip, no unauthorised re-arm, E_STOP absorbing.

The transition relation is closed: every mode change is either
- a one-rung descent (a sustained fault walks the ladder; never skips),
- an emergency jump to E_STOP (braking loss, proximal e-stop), or
- a table recovery exit (FILTERED->NOMINAL, CONSERVATIVE->NOMINAL,
  HOLD->CONSERVATIVE).
Re-arm is the only other ascent: operator-authorised, from CONTROLLED_STOP
only, landing on CONSERVATIVE. The randomised property test below asserts the
closed relation over randomly generated fault schedules; the unit tests assert
the FSM primitives directly.
"""

from __future__ import annotations

import random

import pytest

from aegiscore.core.model import GovMode
from aegiscore.governor import LADDER, RE_ARM_TARGET, RECOVERY_EDGES, FailoverFSM, Fault

CYCLE_US = 1_000
LATENCY_BUDGET_US = 50_000

ONE_RUNG_DESCENTS = {(LADDER[i], LADDER[i + 1]) for i in range(len(LADDER) - 1)}
STEP_EDGES = ONE_RUNG_DESCENTS | RECOVERY_EDGES  # edges reachable inside step()


# ------------------------------------------------------------ FSM primitives


@pytest.mark.parametrize("start", LADDER)
@pytest.mark.parametrize("target", LADDER)
def test_demand_descend_never_skips_or_ascends(start, target):
    fsm = _at(start)
    after = fsm.demand_descend(target, "test")
    if LADDER.index(target) <= LADDER.index(start):
        assert after is start  # a demand never ascends and never re-applies
    else:
        assert LADDER.index(after) == LADDER.index(start) + 1  # exactly one rung


@pytest.mark.parametrize(
    ("start", "target", "allowed"),
    [
        (GovMode.FILTERED, GovMode.NOMINAL, True),
        (GovMode.CONSERVATIVE, GovMode.NOMINAL, True),
        (GovMode.HOLD, GovMode.CONSERVATIVE, True),
        (GovMode.HOLD, GovMode.NOMINAL, False),  # no direct HOLD -> NOMINAL edge
        (GovMode.CONSERVATIVE, GovMode.FILTERED, False),
        (GovMode.CONTROLLED_STOP, GovMode.CONSERVATIVE, False),  # re-arm only
        (GovMode.E_STOP, GovMode.NOMINAL, False),  # terminal in software
    ],
)
def test_recovery_edges_are_exactly_the_table_exits(start, target, allowed):
    fsm = _at(start)
    assert fsm.try_recover(target, "test") is allowed
    assert fsm.mode is (target if allowed else start)


@pytest.mark.parametrize("start", LADDER)
def test_unauthorised_re_arm_never_moves(start):
    fsm = _at(start)
    assert fsm.re_arm(False) is False
    assert fsm.mode is start


@pytest.mark.parametrize("start", LADDER)
def test_authorised_re_arm_only_from_controlled_stop(start):
    fsm = _at(start)
    moved = fsm.re_arm(True)
    assert moved is (start is GovMode.CONTROLLED_STOP)
    if moved:
        assert fsm.mode is RE_ARM_TARGET  # CONSERVATIVE, not NOMINAL


def _at(mode: GovMode) -> FailoverFSM:
    """A FSM walked down to `mode` via single-rung descents."""
    fsm = FailoverFSM()
    while LADDER.index(fsm.mode) < LADDER.index(mode):
        fsm.demand_descend(mode, "walk")
    return fsm


# ------------------------------------------------------- randomized property


def test_governor_property_no_descent_skip_no_unauthorised_ascent(
    make_governor, make_state, make_cmd
):
    """Over randomised fault schedules, every observed transition is in the
    closed relation, faults never ascend, and E_STOP absorbs."""
    rng = random.Random(20260311)
    fault_pool = [None, None, None, *Fault]

    for _trial in range(50):
        gov = make_governor(
            conservative_recovery_cycles=2,
            sensor_loss_persistent_cycles=3,
        )
        prev = GovMode.NOMINAL
        for cycle in range(50):
            now = cycle * CYCLE_US
            fault = rng.choice(fault_pool)
            state = make_state(
                now_us=now,
                v=rng.choice([0.0, 0.4, 0.7, float("nan")]),
                obstacle=rng.choice([None, None, 0.1, 0.4, 3.0]),
            )
            cmd = make_cmd(issued_us=now) if rng.random() < 0.8 else None
            decision = gov.step(state, cmd, now, fault=fault)
            if decision.mode is not prev:
                edge = (prev, decision.mode)
                assert edge in STEP_EDGES or decision.mode is GovMode.E_STOP, (
                    f"illegal transition {prev} -> {decision.mode} under fault={fault}"
                )
                if fault is not None:
                    # a fault never moves the mode up the ladder
                    assert LADDER.index(decision.mode) >= LADDER.index(prev), (
                        f"fault {fault} ascended {prev} -> {decision.mode}"
                    )
            prev = decision.mode

        modes = [r.mode for r in gov.safety_log.records]
        if GovMode.E_STOP in modes:
            first = modes.index(GovMode.E_STOP)
            assert all(m is GovMode.E_STOP for m in modes[first:])  # absorbing
        for record in gov.safety_log.transitions():
            assert record.latency_us <= LATENCY_BUDGET_US


def test_governor_property_re_arm_leaves_audit_trail(make_governor, make_state, make_cmd):
    """Every transition — including operator re-arm — is in the FSM audit trail
    with its kind, and audit kinds match the closed relation."""
    gov = make_governor(network_loss_timeout_us=1_000_000)
    for i in range(6):
        now = i * CYCLE_US
        gov.step(make_state(now_us=now), make_cmd(issued_us=now), now, fault=Fault.NETWORK_LOSS)
    assert gov.re_arm(False, 6 * CYCLE_US) is False
    assert gov.re_arm(True, 6 * CYCLE_US) is True

    audit = gov.fsm_audit
    assert [(a.from_mode, a.to_mode) for a in audit] == [
        (GovMode.NOMINAL, GovMode.FILTERED),
        (GovMode.FILTERED, GovMode.CONSERVATIVE),
        (GovMode.CONSERVATIVE, GovMode.HOLD),
        (GovMode.HOLD, GovMode.CONTROLLED_STOP),
        (GovMode.CONTROLLED_STOP, RE_ARM_TARGET),
    ]
    assert audit[-1].kind == "re_arm"
    assert all(a.kind in ("descent", "emergency", "recovery", "re_arm") for a in audit)
