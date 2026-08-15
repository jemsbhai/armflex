"""Tests for the EXP-003a fitting machinery: exact recovery on
synthetic data, structural output against the real committed
artifacts, and the append-only guard."""

import json
from pathlib import Path

import pytest

from armflex.calibrate import (
    MODEL_BYTES,
    fit_per_quant,
    fit_per_thread,
    linfit,
    load_times,
    run_fit,
)

REPO = Path(__file__).resolve().parents[1]
EXP002 = REPO / "experiments" / "exp_002_axion_sweep"


def test_linfit_recovers_exact_line():
    slope, intercept, r2 = linfit([1.0, 2.0, 3.0], [5.0, 7.0, 9.0])
    assert slope == pytest.approx(2.0)
    assert intercept == pytest.approx(3.0)
    assert r2 == pytest.approx(1.0)


def test_linfit_rejects_degenerate_input():
    with pytest.raises(ValueError):
        linfit([1.0], [2.0])
    with pytest.raises(ValueError):
        linfit([2.0, 2.0], [1.0, 3.0])


def test_fit_per_thread_recovers_synthetic_bandwidth():
    bw = 150e9  # bytes/s
    intercept = 0.002  # 2 ms compute floor
    times = {
        q: {8: MODEL_BYTES[q] / bw + intercept} for q in MODEL_BYTES
    }
    fitted = fit_per_thread(times)["t8"]
    assert fitted["effective_gbs"] == pytest.approx(150.0, rel=1e-6)
    assert fitted["intercept_ms"] == pytest.approx(2.0, rel=1e-6)
    assert fitted["r2"] == pytest.approx(1.0)


def test_fit_per_quant_recovers_synthetic_scaling():
    floor = 0.007
    parallel = 0.040
    times = {"Q4_0": {t: floor + parallel / t for t in (1, 2, 4, 8)}}
    fitted = fit_per_quant(times)["Q4_0"]
    assert fitted["floor_A_ms"] == pytest.approx(7.0, rel=1e-6)
    assert fitted["parallel_B_ms"] == pytest.approx(40.0, rel=1e-6)
    assert fitted["r2"] == pytest.approx(1.0)


@pytest.mark.skipif(not EXP002.is_file() and not EXP002.is_dir(), reason="artifacts absent")
def test_run_fit_against_committed_artifacts(tmp_path):
    out_dir = tmp_path / "exp_003_time_fit"
    payload = run_fit(EXP002, out_dir)
    assert set(payload["per_thread"]) == {"t1", "t2", "t4", "t8", "t16"}
    assert set(payload["per_quant"]) == {"Q4_0", "Q4_K_M", "Q8_0"}
    # structural sanity only; scientific ranges belong to the logbook
    t8 = payload["per_thread"]["t8"]
    assert t8["effective_gbs"] is None or 10.0 < t8["effective_gbs"] < 2000.0
    assert (out_dir / "fit.json").is_file()
    assert (out_dir / "fit.md").is_file()
    text = (out_dir / "fit.md").read_text(encoding="utf-8")
    assert "Per thread level" in text and "Per quant" in text


def test_run_fit_refuses_existing_directory(tmp_path):
    times_dir = tmp_path / "exp"
    times_dir.mkdir()
    (times_dir / "results.json").write_text(json.dumps({}), encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    with pytest.raises(ValueError, match="append-only"):
        run_fit(times_dir, out_dir)


def test_load_times_inverts_throughput(tmp_path):
    entry = {
        "k": {
            "condition": {"quant": "Q4_0", "threads": 8, "model_name": "m",
                          "gguf_path": "p"},
            "summary": {"gen_tok_s": {"mean": 100.0}},
        }
    }
    (tmp_path / "results.json").write_text(json.dumps(entry), encoding="utf-8")
    times = load_times(tmp_path)
    assert times["Q4_0"][8] == pytest.approx(0.01)
