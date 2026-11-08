"""Governor advisory-consumption suite — spec deliverable 7, governor half.

Invariants under test (AegisCore spec, Nov 2026 OpenVINO design update):

1. Advisory constraints are consumed **as margin inputs only** — severity
   narrows the matching margin; nothing else in the governor changes path.
2. A margin reaching zero descends the FSM to FILTERED with reason
   ``advisory:<kind>`` recorded in the safety log.
3. Stale advisory constraints (``issued_monotonic_ns`` freshness) are treated
   like any stale sensor input: rejected/expired, no ladder movement.
4. Advisory state never bypasses envelope checks, heartbeat lease, or e-stop
   precedence, and never ascends a deeper rung.
5. The advisory layer has **no API to write or modify an actuator command** —
   the governor's sole-writer path is unchanged.
6. Safety-log completeness holds: exactly one record per ``step`` call, with
   advisories fed between cycles.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import aegiscore.governor.governor as governor_module
from aegiscore.advisory import AdvisoryConstraint, AdvisoryKind
from aegiscore.core.model import ChassisProfile, GovMode, Kinematics
from aegiscore.governor import GovernorConfig, GovernorCore
from aegiscore.governor.advisory_input import AdvisoryInputError, normalize_advisory

# time.monotonic_ns base for the advisory clock in these tests.
T0_NS = 1_000_000_000_000
# Default GovernorConfig.advisory_max_age_ns.
MAX_AGE_NS = 100_000_000


def constraint(
    kind: str = AdvisoryKind.PROXIMITY_MARGIN,
    severity: float = 1.0,
    issued_ns: int = T0_NS,
    source_model: str = "openvino/proximity@0123456789abcdef0123456789abcdef01234567",
) -> AdvisoryConstraint:
    return AdvisoryConstraint(
        kind=kind, severity=severity, source_model=source_model, issued_monotonic_ns=issued_ns
    )


def fake_constraint(
    *, kind="proximity_margin", severity=0.5, issued_ns=T0_NS
) -> SimpleNamespace:
    """A structurally-valid-shaped object with arbitrarily invalid field values.

    The real AdvisoryConstraint rejects these in its own __post_init__, so
    governor-side rejection tests need raw fakes that get past construction.
    """
    return SimpleNamespace(
        kind=kind,
        severity=severity,
        source_model="openvino/proximity@0123456789abcdef0123456789abcdef01234567",
        issued_monotonic_ns=issued_ns,
    )


# ------------------------------------------------- sole-writer invariant (neg)


def test_on_advisory_can_never_construct_an_actuator_command(
    monkeypatch, make_governor, make_state, make_cmd
):
    """No sequence of advisory inputs, however hostile, builds a command."""
    constructed = []
    real = governor_module.ActuatorCommand

    def spy(*args, **kwargs):
        constructed.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(governor_module, "ActuatorCommand", spy)

    gov = make_governor()
    # Every kind, at every severity edge, plus malformed objects of every shape
    # an integration bug might produce (an embedded command smuggled as an
    # extra attribute is simply never read).
    smuggler = fake_constraint(severity=0.0)
    smuggler.actuator_command = real("act.drive", "drive_speed", 9.9, 0)
    hostile = [
        constraint(kind=k, severity=s)
        for k in AdvisoryKind
        for s in (0.0, 0.5, 1.0)
    ] + [
        None,
        "proximity_margin",
        42,
        smuggler,
        fake_constraint(severity=2.0),
        fake_constraint(kind="not_a_kind"),
    ]
    for c in hostile:
        gov.on_advisory(c)

    assert constructed == [], "advisory input must never construct an actuator command"

    # Subsequent constructions come only from governor step cycles.
    for _ in range(5):
        gov.step(make_state(), make_cmd(), now_us=0)


def test_advisory_path_leaves_sole_writer_unchanged(make_governor, make_state, make_cmd):
    """Identical cycles fed/unfed high-severity advisories admit the same
    command vocabulary — advisory never alters the sole-writer decision."""
    fed = make_governor()
    unfed = make_governor()
    for cycle in range(6):
        now = cycle * 1_000
        state, cmd = make_state(now_us=now), make_cmd(issued_us=now)
        fed.on_advisory(constraint(severity=1.0))
        a = fed.step(state, cmd, now)
        b = unfed.step(state, cmd, now)
        # Every admitted command in both runs is governor-authored with the
        # profile's own actuator ids and the fixed command vocabulary.
        for decision in (a, b):
            if decision.admitted is not None:
                assert decision.admitted.actuator_id in ("act.drive", "act.blade")
                assert decision.admitted.command_type in ("drive_speed", "blade_on", "blade_off")


# ------------------------------------------------------- zero-margin descent


def test_zero_margin_descends_to_filtered_with_logged_reason(
    make_governor, make_state, make_cmd
):
    gov = make_governor()
    assert gov.on_advisory(constraint(severity=1.0)) is True

    decision = gov.step(make_state(), make_cmd(), now_us=0)

    assert decision.mode is GovMode.FILTERED
    record = gov.safety_log.records[-1]
    assert record.reason == "advisory:proximity_margin"
    assert record.transition_from is GovMode.NOMINAL
    assert record.transition_to is GovMode.FILTERED
    assert any(
        a.to_mode is GovMode.FILTERED and a.reason == "advisory:proximity_margin"
        for a in gov.fsm_audit
    )


def test_sustained_zero_margin_holds_filtered_and_brakes(make_governor, make_state, make_cmd):
    """A sustained zero margin is a sustained condition: the rung is held and
    fault-cycle semantics (zero-velocity output) apply while it lasts."""
    gov = make_governor()
    for cycle in range(4):
        now = cycle * 1_000
        gov.on_advisory(constraint(severity=1.0, issued_ns=T0_NS))
        decision = gov.step(make_state(now_us=now), make_cmd(issued_us=now), now)
        assert decision.mode is GovMode.FILTERED
        assert decision.reason == "advisory:proximity_margin"
        if decision.admitted is not None:
            assert decision.admitted.command_type == "drive_speed"
            assert decision.admitted.value == 0.0


def test_partial_severity_narrows_margin_without_descending(
    make_governor, make_state, make_cmd
):
    gov = make_governor()
    gov.on_advisory(constraint(severity=0.5))

    decision = gov.step(make_state(), make_cmd(target_speed=0.5), now_us=0)

    assert decision.mode is GovMode.NOMINAL
    assert decision.margins["advisory_proximity_margin"] == pytest.approx(0.5)
    assert decision.admitted is not None and decision.admitted.value == pytest.approx(0.5)


def test_min_narrowing_keeps_the_tightest_constraint(make_governor, make_state, make_cmd):
    gov = make_governor()
    gov.on_advisory(constraint(severity=0.8))
    gov.on_advisory(constraint(severity=0.3))  # wider — must not widen the margin

    decision = gov.step(make_state(), make_cmd(), now_us=0)

    assert decision.margins["advisory_proximity_margin"] == pytest.approx(0.2)
    assert decision.mode is GovMode.NOMINAL


# ------------------------------------------------------------------ staleness


def test_stale_advisory_rejected_at_intake(make_governor, make_state, make_cmd):
    gov = make_governor()
    stale = constraint(severity=1.0, issued_ns=T0_NS - MAX_AGE_NS - 1)

    assert gov.on_advisory(stale, now_monotonic_ns=T0_NS) is False

    decision = gov.step(make_state(), make_cmd(), now_us=0, now_monotonic_ns=T0_NS)
    assert decision.mode is GovMode.NOMINAL
    assert decision.reason != "advisory:proximity_margin"
    assert all(not k.startswith("advisory_") for k in decision.margins)


def test_accepted_advisory_expires_when_it_goes_stale(make_governor, make_state, make_cmd):
    gov = make_governor()
    gov.on_advisory(constraint(severity=1.0, issued_ns=T0_NS), now_monotonic_ns=T0_NS)
    assert gov.step(make_state(), make_cmd(), now_us=0, now_monotonic_ns=T0_NS).mode is (
        GovMode.FILTERED
    )

    # Past the freshness window the constraint is treated like any stale
    # sensor input: no effect, and the table's recovery exits apply again.
    fresh_cmd = make_cmd(issued_us=0)
    decision = gov.step(
        make_state(),
        fresh_cmd,
        now_us=1_000,
        now_monotonic_ns=T0_NS + MAX_AGE_NS + 1,
    )

    assert decision.mode is GovMode.NOMINAL
    assert all(not k.startswith("advisory_") for k in decision.margins)


def test_fresh_advisory_within_age_window_is_accepted(make_governor):
    gov = make_governor()
    fresh = constraint(severity=1.0, issued_ns=T0_NS - MAX_AGE_NS)

    assert gov.on_advisory(fresh, now_monotonic_ns=T0_NS) is True


# ------------------------------------- precedence: never bypasses the ladder


def test_advisory_never_bypasses_e_stop_precedence(make_governor, make_state, make_cmd):
    """Zero advisory margin + a proximal e-stop condition -> E_STOP, not FILTERED."""
    gov = make_governor()
    gov.on_advisory(constraint(severity=1.0))

    decision = gov.step(
        make_state(obstacle=0.1), make_cmd(), now_us=0
    )  # obstacle < e_stop_radius_m (0.2)

    assert decision.mode is GovMode.E_STOP
    assert decision.reason == "proximal_e_stop"


def test_advisory_never_bypasses_heartbeat_lease(make_governor, make_state, make_cmd):
    """Zero advisory margin + a stale heartbeat -> HOLD (lease outranks advisory).

    The FSM walks one rung per cycle, so the lease descent passes through
    FILTERED on its way to HOLD — the advisory descent must never preempt it.
    """
    gov = make_governor()
    gov.on_advisory(constraint(severity=1.0))

    decision = None
    for cycle in range(4):
        now = cycle * 1_000
        decision = gov.step(
            make_state(now_us=now, heartbeat_age_us=150_000),
            make_cmd(issued_us=now),
            now,
        )

    assert decision.mode is GovMode.HOLD
    assert decision.reason == "heartbeat_lease_lost"


def test_advisory_never_ascends_a_deeper_rung(make_governor, make_state, make_cmd):
    """Zero advisory margin in CONSERVATIVE: no ascent to FILTERED, and the
    cycle keeps supervising (speed-capped task command, not fault-cycle braking)."""
    gov = make_governor()
    # Degraded-sensor cycles (non-persistent) walk to CONSERVATIVE — the FSM
    # descends one rung per cycle: NOMINAL -> FILTERED -> CONSERVATIVE.
    for cycle in range(2):
        gov.step(
            make_state(now_us=cycle * 1_000, pose={"x": float("nan"), "y": 0.0, "theta": 0.0}),
            None,
            now_us=cycle * 1_000,
        )
    assert gov.mode is GovMode.CONSERVATIVE

    gov.on_advisory(constraint(severity=1.0))
    decision = gov.step(make_state(), make_cmd(target_speed=0.5), now_us=1_000)

    assert decision.mode is GovMode.CONSERVATIVE
    assert decision.reason != "advisory:proximity_margin"
    # Supervision continues under the CONSERVATIVE speed cap — not a stop cycle.
    assert decision.admitted is not None
    assert decision.admitted.value == pytest.approx(0.3 * 1.0)


def test_recovery_is_held_while_an_advisory_margin_is_zero(
    make_governor, make_state, make_cmd
):
    """FILTERED recovery (margins_recovered) must not fire past a zero advisory
    margin — advisory narrows, never widens, the core's own margins."""
    gov = make_governor()
    gov.on_advisory(constraint(severity=1.0, issued_ns=T0_NS))
    gov.step(make_state(), make_cmd(), now_us=0, now_monotonic_ns=T0_NS)
    assert gov.mode is GovMode.FILTERED

    # Healthy, admissible cycles — but the advisory clock never advances, so
    # the zero margin stands and the recovery exit stays shut.
    for cycle in range(1, 6):
        decision = gov.step(
            make_state(now_us=cycle * 1_000),
            make_cmd(issued_us=cycle * 1_000),
            cycle * 1_000,
            now_monotonic_ns=T0_NS,
        )
        assert decision.mode is GovMode.FILTERED

    # Once the constraint expires, the normal recovery path applies.
    decision = gov.step(
        make_state(now_us=6_000),
        make_cmd(issued_us=6_000),
        now_us=6_000,
        now_monotonic_ns=T0_NS + MAX_AGE_NS + 1,
    )
    assert decision.mode is GovMode.NOMINAL


# ------------------------------------------------- malformed-input rejection


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "proximity_margin",
        42,
        fake_constraint(kind="not_a_kind"),
        fake_constraint(severity=1.5),
        fake_constraint(severity=-0.1),
        fake_constraint(issued_ns=-1),
        fake_constraint(issued_ns=True),
    ],
)
def test_malformed_advisory_rejected_without_state_change(bad, make_governor, make_state, make_cmd):
    gov = make_governor()

    assert gov.on_advisory(bad) is False
    assert gov._advisory_rejected == 1
    decision = gov.step(make_state(), make_cmd(), now_us=0)
    assert decision.mode is GovMode.NOMINAL
    assert all(not k.startswith("advisory_") for k in decision.margins)


def test_normalize_rejects_partially_valid_input():
    """A constraint valid except for one field is rejected whole."""
    good = constraint()
    nan_severity = SimpleNamespace(
        kind=good.kind,
        severity=float("nan"),
        source_model=good.source_model,
        issued_monotonic_ns=good.issued_monotonic_ns,
    )
    with pytest.raises(AdvisoryInputError):
        normalize_advisory(nan_severity)


# ------------------------------------------------- safety-log completeness


def test_safety_log_completeness_holds_with_advisory_cycles(
    make_governor, make_state, make_cmd
):
    """Exactly one record per step call — advisories fed between cycles add none."""
    gov = make_governor()
    steps = 0
    for cycle in range(10):
        now = cycle * 1_000
        if cycle % 2 == 0:
            gov.on_advisory(constraint(severity=1.0 if cycle % 4 == 0 else 0.4, issued_ns=T0_NS))
        gov.step(make_state(now_us=now), make_cmd(issued_us=now), now, now_monotonic_ns=T0_NS)
        steps += 1

    assert len(gov.safety_log) == steps
    assert all(r.seq == i for i, r in enumerate(gov.safety_log.records))
    # Every advisory descent is traceable in the log.
    descents = [r for r in gov.safety_log.records if r.reason == "advisory:proximity_margin"]
    assert descents, "advisory descent must appear in the safety log"


def test_advisory_margins_logged_for_every_active_kind(make_governor, make_state, make_cmd):
    gov = make_governor()
    gov.on_advisory(constraint(kind=AdvisoryKind.PROXIMITY_MARGIN, severity=0.2))
    gov.on_advisory(constraint(kind=AdvisoryKind.ANOMALY_FLAG, severity=0.7))
    # severity 1.0 leaves zero margin on terrain_risk; the others stay positive.
    gov.on_advisory(constraint(kind=AdvisoryKind.TERRAIN_RISK, severity=1.0))

    decision = gov.step(make_state(), make_cmd(), now_us=0)

    assert decision.margins["advisory_proximity_margin"] == pytest.approx(0.8)
    assert decision.margins["advisory_anomaly_flag"] == pytest.approx(0.3)
    assert decision.margins["advisory_terrain_risk"] == pytest.approx(0.0)
    # The zero margin descends, and the log names its kind.
    assert decision.reason == "advisory:terrain_risk"
    assert decision.mode is GovMode.FILTERED


# ------------------------------------------------- structural decoupling


def test_governor_accepts_any_structurally_valid_constraint():
    """The governor's view is structural: a plain object with the four fields
    is consumed without importing the advisory package."""

    class Fake:
        kind = "terrain_risk"
        severity = 1.0
        source_model = "openvino/terrain@0123456789abcdef0123456789abcdef01234567"
        issued_monotonic_ns = T0_NS

    profile = ChassisProfile(
        model="t",
        kinematics=Kinematics.DIFFERENTIAL,
        max_linear_speed=1.0,
        max_accel=1.0,
        max_wheel_speed=10.0,
        blade_inertia_kg_m2=None,
        actuators={"drive": "d"},
    )
    core = GovernorCore(profile, GovernorConfig())
    assert core.on_advisory(Fake(), now_monotonic_ns=T0_NS) is True
    assert core._advisory_margins["terrain_risk"] == 0.0
