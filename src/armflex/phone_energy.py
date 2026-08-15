"""EXP-003b analysis: battery telemetry to joules per token, with fit.

Unit rules, locked against the device calibration paste (Pixel 8 Pro,
Android 16, termux-api, 2026-08-14, while PLUGGED_AC):
- api_current is MICROAMPS, sign positive while charging (observed
  +1,547,187 uA on AC). Discharge is therefore negative, and battery
  power draw in watts is P = -(I_uA * V_mV) * 1e-9.
- api_voltage_mV is millivolts; api_temp_C is Celsius.
- charge_counter is microamp-hours; its delta times mean voltage gives
  an independent energy estimate used as a cross-check (not yet wired;
  the sampler records enough to add it in analysis revisions).
- The sysfs columns are permission-denied on this device and ignored.

Method (pre-registered, LOGBOOK EXP-003b, amended before execution):
trapezoid-integrate power over each cell window from events.csv,
subtract the idle baseline power times duration, divide by generated
tokens (512 per invocation, llama-bench -n 512 -r 1). Fit per-byte and
per-MAC energies across cells by least squares; the 3-parameter model
adds static power times decode time (s/token from the bench JSON
avg_ts), which is identifiable because threads vary decode time at
fixed bytes. Known limitation, documented: the window includes model
load; -n 512 bounds that contamination to a few percent.
Interpretation belongs to the logbook, not this module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .toml_model import QWEN25_1_5B

TOKENS_PER_INVOCATION = 512
# Average decode context in a -p 0 -n 512 run is about 256 tokens.
_AVG_CTX = 256


def load_samples(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(",")
        row = dict(zip(header, parts))
        try:
            rows.append(
                {
                    "t_ms": int(row["epoch_ms"]),
                    "i_ua": float(row["api_current"]) if row["api_current"] else None,
                    "v_mv": float(row["api_voltage_mV"]) if row["api_voltage_mV"] else None,
                    "temp_c": float(row["api_temp_C"]) if row["api_temp_C"] else None,
                    "status": row.get("api_status", ""),
                }
            )
        except (KeyError, ValueError):
            continue
    return rows


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines[1:]:
        if not line.strip():
            continue
        phase, start_ms, end_ms, note = line.split(",", 3)
        events.append(
            {
                "phase": phase,
                "start_ms": int(start_ms),
                "end_ms": int(end_ms),
                "note": note,
            }
        )
    return events


def power_w(sample: dict[str, Any]) -> float | None:
    """Battery draw in watts; positive means discharging."""
    if sample["i_ua"] is None or sample["v_mv"] is None:
        return None
    return -(sample["i_ua"] * sample["v_mv"]) * 1e-9


def integrate_energy_j(
    samples: list[dict[str, Any]], start_ms: int, end_ms: int
) -> tuple[float, int, int]:
    """Trapezoid integral of power over the window.

    Returns (joules, n_samples, n_charging_samples). Charging samples
    inside a measurement window indicate a protocol violation and are
    counted, never hidden.
    """
    window = [
        s
        for s in samples
        if start_ms <= s["t_ms"] <= end_ms and power_w(s) is not None
    ]
    charging = sum(1 for s in window if (s["i_ua"] or 0) > 0)
    if len(window) < 2:
        return 0.0, len(window), charging
    joules = 0.0
    for a, b in zip(window, window[1:]):
        dt = (b["t_ms"] - a["t_ms"]) / 1000.0
        joules += dt * (power_w(a) + power_w(b)) / 2.0
    return joules, len(window), charging


def baseline_power_w(samples, events) -> float:
    total_j = 0.0
    total_s = 0.0
    for event in events:
        if event["phase"] != "baseline":
            continue
        joules, n, _ = integrate_energy_j(samples, event["start_ms"], event["end_ms"])
        if n >= 2:
            total_j += joules
            total_s += (event["end_ms"] - event["start_ms"]) / 1000.0
    if total_s <= 0:
        raise ValueError("no usable baseline windows in events.csv")
    return total_j / total_s


def per_token_workload(model_size_bytes: int) -> dict[str, float]:
    spec = QWEN25_1_5B
    macs = float(
        spec.weight_macs_per_token
        + spec.lm_head_macs
        + 2 * spec.n_layers * spec.d_model * _AVG_CTX
    )
    bytes_per_token = float(model_size_bytes + spec.kv_bytes_per_token() * _AVG_CTX)
    return {"macs": macs, "bytes": bytes_per_token}


def analyze_cells(samples, events, bench_dir: Path) -> dict[str, Any]:
    base_w = baseline_power_w(samples, events)
    accum: dict[str, Any] = {}
    for event in events:
        if not event["phase"].startswith("cell_"):
            continue
        key = event["phase"][len("cell_"):]
        joules, _n, charging = integrate_energy_j(
            samples, event["start_ms"], event["end_ms"]
        )
        duration_s = (event["end_ms"] - event["start_ms"]) / 1000.0
        rep = accum.setdefault(
            key,
            {"net_j": [], "duration_s": [], "flags": [], "model_size": 0,
             "s_per_token": 0.0},
        )
        rep["net_j"].append(joules - base_w * duration_s)
        rep["duration_s"].append(duration_s)
        if charging:
            rep["flags"].append(f"{charging} charging samples in a window")
        quant, threads = key.rsplit("_t", 1)
        if not rep["model_size"]:
            bench_files = sorted(bench_dir.glob(f"{quant}_t{threads}_rep*.json"))
            if bench_files:
                first = json.loads(bench_files[0].read_text(encoding="utf-8"))
                rep["model_size"] = int(first[0].get("model_size", 0))
                ts_values = []
                for bench_file in bench_files:
                    entries = json.loads(bench_file.read_text(encoding="utf-8"))
                    ts = entries[0].get("avg_ts")
                    if ts:
                        ts_values.append(float(ts))
                rep["s_per_token"] = (
                    1.0 / (sum(ts_values) / len(ts_values)) if ts_values else 0.0
                )
    if not accum:
        raise ValueError("no cell windows found in events.csv")
    out: dict[str, Any] = {"baseline_power_w": base_w, "cells": {}}
    for key, rep in accum.items():
        n = len(rep["net_j"])
        j_per_token = [j / TOKENS_PER_INVOCATION for j in rep["net_j"]]
        mean = sum(j_per_token) / n
        var = sum((x - mean) ** 2 for x in j_per_token) / (n - 1) if n > 1 else 0.0
        quant, threads_text = key.rsplit("_t", 1)
        workload = per_token_workload(rep["model_size"])
        out["cells"][key] = {
            "quant": quant,
            "threads": int(threads_text),
            "n": n,
            "j_per_token_mean": mean,
            "j_per_token_sd": var ** 0.5,
            "mean_duration_s": sum(rep["duration_s"]) / n,
            "s_per_token_bench": rep["s_per_token"],
            "flags": rep["flags"],
            "macs_per_token": workload["macs"],
            "bytes_per_token": workload["bytes"],
        }
    return out


def fit_energy_constants(cells: dict[str, Any]) -> dict[str, Any]:
    """Least squares for J/token against per-token workload.

    two_param:   J = e_mac*MACs + e_byte*bytes
    three_param: J = e_mac*MACs + e_byte*bytes + static_w * s_per_token
    The third column is bench-measured decode time, identifiable
    because threads vary time at fixed bytes.
    """
    rows = list(cells.values())
    if len(rows) < 3:
        raise ValueError("need at least three cells to fit")

    def solve(with_time: bool) -> dict[str, Any]:
        if with_time and not any(r.get("s_per_token_bench", 0.0) for r in rows):
            return {"skipped": "no decode-time data in bench JSON"}
        cols = 3 if with_time else 2
        ata = [[0.0] * cols for _ in range(cols)]
        atb = [0.0] * cols
        for row in rows:
            x = [row["macs_per_token"], row["bytes_per_token"]]
            if with_time:
                x.append(row.get("s_per_token_bench", 0.0))
            y = row["j_per_token_mean"]
            for i in range(cols):
                atb[i] += x[i] * y
                for j in range(cols):
                    ata[i][j] += x[i] * x[j]
        coef = _gauss_solve(ata, atb)
        residuals = {}
        ss_res = 0.0
        for key, row in cells.items():
            x = [row["macs_per_token"], row["bytes_per_token"]]
            if with_time:
                x.append(row.get("s_per_token_bench", 0.0))
            pred = sum(c * v for c, v in zip(coef, x))
            residuals[key] = row["j_per_token_mean"] - pred
            ss_res += residuals[key] ** 2
        result: dict[str, Any] = {
            "e_mac_pj": coef[0] * 1e12,
            "e_byte_pj": coef[1] * 1e12,
            "residual_j": residuals,
            "ss_res": ss_res,
        }
        if with_time:
            result["static_w"] = coef[2]
        return result

    return {"two_param": solve(False), "three_param": solve(True)}


def _gauss_solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-30:
            raise ValueError("singular system in energy fit")
        m[col], m[pivot] = m[pivot], m[col]
        for row in range(n):
            if row != col:
                factor = m[row][col] / m[col][col]
                for k in range(col, n + 1):
                    m[row][k] -= factor * m[col][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def run_analysis(raw_dir: Path, out_dir: Path) -> dict[str, Any]:
    if out_dir.exists():
        raise ValueError(
            f"output directory already exists: {out_dir} (experiments are "
            "append-only; pick a new directory)"
        )
    samples = load_samples(raw_dir / "samples.csv")
    events = load_events(raw_dir / "events.csv")
    analysis = analyze_cells(samples, events, raw_dir)
    analysis["fit"] = fit_energy_constants(analysis["cells"])
    out_dir.mkdir(parents=True)
    (out_dir / "analysis.json").write_text(
        json.dumps(analysis, indent=2) + "\n", encoding="utf-8"
    )
    return analysis
