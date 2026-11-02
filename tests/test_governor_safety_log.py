"""Safety-log completeness: 100% of supervisor decisions are logged.

The spec's "100% deterministic safety logging" made concrete: exactly one
record per GovernorCore.step call — healthy, fault, transition, and E_STOP
cycles included — with contiguous sequence numbers and a latency measurement.
"""

from __future__ import annotations

import random
from dataclasses import FrozenInstanceError, replace

import pytest

from aegiscore.core.model import GovMode
from aegiscore.governor import Fault

CYCLE_US = 1_000


def test_every_cycle_produces_exactly_one_record(make_governor, make_state, make_cmd):
    """Mixed healthy/fault schedule: record count == step count, seq contiguous."""
    gov = make_governor(conservative_recovery_cycles=2)
    rng = random.Random(42)
    fault_pool = [None, None, None, *Fault]
    decisions = []
    for i in range(100):
        now = i * CYCLE_US
        fault = rng.choice(fault_pool)
        state = make_state(
            now_us=now,
            v=rng.choice([0.0, 0.5, -0.1, float("nan")]),
            obstacle=rng.choice([None, None, 0.1, 0.4, 3.0]),
        )
        cmd = None if rng.random() < 0.2 else make_cmd(issued_us=now)
        decisions.append(gov.step(state, cmd, now, fault=fault))

    log = gov.safety_log
    assert len(log) == 100  # 100% completeness: no cycle went unlogged
    records = log.records
    assert [r.seq for r in records] == list(range(100))
    for record, decision in zip(records, decisions, strict=True):
        assert record.mode is decision.mode
        assert record.reason == decision.reason
        assert record.margins == decision.margins
        assert record.latency_us >= 0
        if decision.admitted is None:
            assert record.admitted_actuator_id is None
            assert record.admitted_command_type is None
            assert record.admitted_value is None
        else:
            assert record.admitted_actuator_id == decision.admitted.actuator_id
            assert record.admitted_command_type == decision.admitted.command_type
            assert record.admitted_value == decision.admitted.value


def test_log_chains_transitions_across_cycles(make_governor, make_state, make_cmd):
    """Each transition's `from` is the previous cycle's `to` — an unbroken chain."""
    gov = make_governor(network_loss_timeout_us=1_000_000, hold_timeout_us=10_000_000)
    for i in range(8):
        now = i * CYCLE_US
        gov.step(make_state(now_us=now), make_cmd(issued_us=now), now, fault=Fault.UNMODELED)
    prev_mode = None
    for record in gov.safety_log.records:
        if record.transition_to is None:
            assert record.transition_from is None
        else:
            assert record.transition_from is not None
            if prev_mode is not None:
                assert record.transition_from is prev_mode
        prev_mode = record.mode
    assert len(gov.safety_log.transitions()) == 4  # NOMINAL walk to CONTROLLED_STOP


def test_estop_cycles_still_log(make_governor, make_state, make_cmd):
    """Even the terminal state keeps logging every cycle."""
    gov = make_governor()
    gov.step(make_state(now_us=0, brake=0.0), None, 0)
    for i in range(1, 5):
        now = i * CYCLE_US
        gov.step(make_state(now_us=now, brake=0.0), None, now)
    assert len(gov.safety_log) == 5
    assert all(r.mode is GovMode.E_STOP for r in gov.safety_log.records)


def test_records_are_immutable(make_governor, make_state, make_cmd):
    gov = make_governor()
    gov.step(make_state(now_us=0), make_cmd(issued_us=0), 0)
    record = gov.safety_log.records[0]
    with pytest.raises(FrozenInstanceError):
        record.seq = 99  # type: ignore[misc]


def test_step_is_deterministic(make_governor, make_state, make_cmd):
    """Identical input schedules produce identical decision logs (modulo the
    wall-clock latency measurement)."""

    def scenario(gov):
        faults = [None, Fault.SENSOR_LOSS, None, Fault.SPOOFED_COMMAND, None, Fault.UNMODELED]
        for i, fault in enumerate(faults * 3):
            now = i * CYCLE_US
            obstacle = 0.9 if i % 3 == 0 else None
            gov.step(
                make_state(now_us=now, v=0.3, obstacle=obstacle),
                make_cmd(issued_us=now),
                now,
                fault=fault,
            )
        return [replace(r, latency_us=0.0) for r in gov.safety_log.records]

    a = scenario(make_governor(network_loss_timeout_us=1_000_000))
    b = scenario(make_governor(network_loss_timeout_us=1_000_000))
    assert a == b
