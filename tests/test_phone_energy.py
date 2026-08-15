"""Tests for the EXP-003b analyzer: locked unit rules, exact
integration on synthetic telemetry, baseline netting, protocol-flag
accounting, fit recovery including the decode-time static term, and
the append-only guard."""

import json
from pathlib import Path

import pytest

from armflex.phone_energy import (
    TOKENS_PER_INVOCATION,
    analyze_cells,
    fit_energy_constants,
    integrate_energy_j,
    load_events,
    load_samples,
    power_w,
    run_analysis,
)

V_MV = 4000.0


def _sample(t_ms, i_ua, v_mv=V_MV, status="DISCHARGING"):
    return {"t_ms": t_ms, "i_ua": i_ua, "v_mv": v_mv, "temp_c": 30.0, "status": status}


def _watts_to_ua(watts):
    """Invert the locked unit rule for synthetic discharge samples."""
    return -watts / (V_MV * 1e-9)


def test_power_sign_rule_matches_calibration_paste():
    charging = _sample(0, 1_547_187, 4159.0, "CHARGING")
    assert power_w(charging) < 0  # charging is negative draw
    discharging = _sample(0, _watts_to_ua(4.0))
    assert power_w(discharging) == pytest.approx(4.0)


def test_trapezoid_integration_exact_on_constant_power():
    samples = [_sample(t * 1000, _watts_to_ua(4.0)) for t in range(11)]
    joules, n, charging = integrate_energy_j(samples, 0, 10_000)
    assert joules == pytest.approx(40.0)
    assert n == 11
    assert charging == 0


def test_charging_samples_are_counted_not_hidden():
    samples = [_sample(t * 1000, _watts_to_ua(2.0)) for t in range(5)]
    samples[2] = _sample(2000, +500_000, status="CHARGING")
    _, _, charging = integrate_energy_j(samples, 0, 4000)
    assert charging == 1


def _bench_json(model_size, avg_ts):
    return json.dumps([{"model_size": model_size, "avg_ts": avg_ts}])


def _write_synthetic_session(raw: Path):
    """Baseline 1 W for 0..10 s; three cells at 3, 5, and 7 W with
    distinct bench decode rates so the 3-parameter fit has rank."""
    raw.mkdir(parents=True)
    rows = ["epoch_ms,api_current,api_voltage_mV,api_temp_C,api_status,api_pct,sys_current_now,sys_voltage_now"]

    def add(t0, t1, watts):
        for t in range(t0, t1 + 1):
            rows.append(f"{t * 1000},{_watts_to_ua(watts)},{V_MV},30.0,DISCHARGING,60,,")

    add(0, 10, 1.0)
    add(20, 30, 3.0)
    add(40, 50, 5.0)
    add(60, 70, 7.0)
    (raw / "samples.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    events = [
        "phase,start_ms,end_ms,note",
        "baseline,0,10000,pre",
        "cell_Q4_0_t1,20000,30000,rep1;temp_start=30;temp_end=31",
        "cell_Q4_0_t4,40000,50000,rep1;temp_start=30;temp_end=31",
        "cell_Q8_0_t4,60000,70000,rep1;temp_start=30;temp_end=31",
    ]
    (raw / "events.csv").write_text("\n".join(events) + "\n", encoding="utf-8")
    (raw / "Q4_0_t1_rep1.json").write_text(
        _bench_json(1_066_227_232, 3.0), encoding="utf-8"
    )
    (raw / "Q4_0_t4_rep1.json").write_text(
        _bench_json(1_066_227_232, 10.0), encoding="utf-8"
    )
    (raw / "Q8_0_t4_rep1.json").write_text(
        _bench_json(1_894_532_128, 6.0), encoding="utf-8"
    )


def test_baseline_netting_tokens_and_bench_time(tmp_path):
    _write_synthetic_session(tmp_path / "raw")
    samples = load_samples(tmp_path / "raw" / "samples.csv")
    events = load_events(tmp_path / "raw" / "events.csv")
    analysis = analyze_cells(samples, events, tmp_path / "raw")
    assert analysis["baseline_power_w"] == pytest.approx(1.0)
    cell = analysis["cells"]["Q4_0_t1"]
    # gross 3 W x 10 s = 30 J, net 20 J, over the invocation's tokens
    assert cell["j_per_token_mean"] == pytest.approx(20.0 / TOKENS_PER_INVOCATION)
    assert cell["n"] == 1
    assert cell["threads"] == 1
    assert cell["flags"] == []
    assert cell["s_per_token_bench"] == pytest.approx(1.0 / 3.0)
    assert analysis["cells"]["Q8_0_t4"]["bytes_per_token"] > cell["bytes_per_token"]


def _cell(macs, byts, s_tok, e_mac, e_byte, static_w):
    return {
        "macs_per_token": macs,
        "bytes_per_token": byts,
        "s_per_token_bench": s_tok,
        "j_per_token_mean": e_mac * macs + e_byte * byts + static_w * s_tok,
    }


def test_two_param_fit_recovers_when_static_is_zero():
    cells = {
        "a": _cell(1e9, 1e9, 0.0, 2e-12, 50e-12, 0.0),
        "b": _cell(2e9, 1e9, 0.0, 2e-12, 50e-12, 0.0),
        "c": _cell(1e9, 2e9, 0.0, 2e-12, 50e-12, 0.0),
    }
    fit = fit_energy_constants(cells)
    assert fit["two_param"]["e_mac_pj"] == pytest.approx(2.0, rel=1e-6)
    assert fit["two_param"]["e_byte_pj"] == pytest.approx(50.0, rel=1e-6)
    assert fit["two_param"]["ss_res"] == pytest.approx(0.0, abs=1e-18)
    # all-zero time column: the 3-parameter model must decline, not blow up
    assert fit["three_param"] == {"skipped": "no decode-time data in bench JSON"}


def test_three_param_fit_recovers_static_power():
    e_mac, e_byte, static_w = 2e-12, 50e-12, 0.5
    cells = {
        "a": _cell(1e9, 1e9, 0.30, e_mac, e_byte, static_w),
        "b": _cell(1e9, 1e9, 0.10, e_mac, e_byte, static_w),
        "c": _cell(1e9, 2e9, 0.15, e_mac, e_byte, static_w),
        "d": _cell(2e9, 2e9, 0.08, e_mac, e_byte, static_w),
    }
    fit = fit_energy_constants(cells)
    assert fit["three_param"]["e_mac_pj"] == pytest.approx(2.0, rel=1e-6)
    assert fit["three_param"]["e_byte_pj"] == pytest.approx(50.0, rel=1e-6)
    assert fit["three_param"]["static_w"] == pytest.approx(0.5, rel=1e-6)
    assert fit["three_param"]["ss_res"] == pytest.approx(0.0, abs=1e-15)
    assert fit["two_param"]["ss_res"] > 0.0


def test_fit_rejects_underdetermined_input():
    with pytest.raises(ValueError):
        fit_energy_constants(
            {"only": {"macs_per_token": 1.0, "bytes_per_token": 1.0,
                      "j_per_token_mean": 1.0}}
        )


def test_run_analysis_end_to_end_and_append_only(tmp_path):
    raw = tmp_path / "raw"
    _write_synthetic_session(raw)
    out = tmp_path / "out"
    analysis = run_analysis(raw, out)
    assert (out / "analysis.json").is_file()
    assert set(analysis["cells"]) == {"Q4_0_t1", "Q4_0_t4", "Q8_0_t4"}
    assert "e_mac_pj" in analysis["fit"]["two_param"]
    assert "static_w" in analysis["fit"]["three_param"]
    with pytest.raises(ValueError, match="append-only"):
        run_analysis(raw, out)


def test_event_notes_survive_embedded_separators(tmp_path):
    path = tmp_path / "events.csv"
    path.write_text(
        "phase,start_ms,end_ms,note\ncell_Q4_0_t1,0,1000,rep1;a=1,b=2\n",
        encoding="utf-8",
    )
    events = load_events(path)
    assert events[0]["note"] == "rep1;a=1,b=2"
