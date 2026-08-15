"""EXP-003a: fit the TOML decode time structure from measured sweep data.

Two views of the same 15 cells (EXP-002 means):

1. Per thread level: time-per-token vs model bytes across quants.
   Slope inverts to an effective bandwidth; intercept is the compute
   and overhead floor; the Q4_K_M residual tests quant-dependent
   compute cost.
2. Per quant: time-per-token vs 1/threads over the scaling regime
   (t in {1,2,4,8}; t16 excluded as the collapsed serving regime,
   EXP-002/004/005). The extrapolated floor A_q is compared with
   bytes_q divided by the observed ~150 GB/s ceiling.

Pure Python closed-form least squares; no new dependencies. Energy
constants are NOT produced here; that is EXP-003b with real power
telemetry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# GGUF file sizes in bytes, recorded at provisioning (box ls output,
# 2026-08-14, Qwen/Qwen2.5-1.5B-Instruct-GGUF files).
MODEL_BYTES: dict[str, int] = {
    "Q4_0": 1_066_227_232,
    "Q4_K_M": 1_117_320_736,
    "Q8_0": 1_894_532_128,
}

SCALING_THREADS = (1, 2, 4, 8)
CEILING_GBS = 150.0  # observed platform ceiling, EXP-001/002


def linfit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Ordinary least squares y = a*x + b. Returns (a, b, r2)."""
    n = len(xs)
    if n < 2 or len(ys) != n:
        raise ValueError("linfit needs at least two paired points")
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        raise ValueError("linfit needs varying x values")
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    r2 = 1.0 if ss_tot == 0 else 1.0 - ss_res / ss_tot
    return slope, intercept, r2


def load_times(exp_dir: Path) -> dict[str, dict[int, float]]:
    """Seconds per generated token, from EXP-002 gen_tok_s means."""
    raw = json.loads((exp_dir / "results.json").read_text(encoding="utf-8"))
    times: dict[str, dict[int, float]] = {}
    for entry in raw.values():
        quant = entry["condition"]["quant"]
        threads = int(entry["condition"]["threads"])
        tg = float(entry["summary"]["gen_tok_s"]["mean"])
        times.setdefault(quant, {})[threads] = 1.0 / tg
    return times


def fit_per_thread(times: dict[str, dict[int, float]]) -> dict[str, Any]:
    quants = sorted(times, key=lambda q: MODEL_BYTES[q])
    out: dict[str, Any] = {}
    thread_levels = sorted(next(iter(times.values())))
    for t in thread_levels:
        xs = [float(MODEL_BYTES[q]) for q in quants]
        ys = [times[q][t] for q in quants]
        slope, intercept, r2 = linfit(xs, ys)
        fitted = {q: slope * MODEL_BYTES[q] + intercept for q in quants}
        out[f"t{t}"] = {
            "threads": t,
            "slope_s_per_byte": slope,
            "effective_gbs": (1.0 / slope) / 1e9 if slope > 0 else None,
            "intercept_ms": intercept * 1e3,
            "r2": r2,
            "residual_ms": {
                q: (times[q][t] - fitted[q]) * 1e3 for q in quants
            },
        }
    return out


def fit_per_quant(times: dict[str, dict[int, float]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for quant, per_t in sorted(times.items()):
        xs = [1.0 / t for t in SCALING_THREADS if t in per_t]
        ys = [per_t[t] for t in SCALING_THREADS if t in per_t]
        slope, intercept, r2 = linfit(xs, ys)
        predicted_floor_ms = MODEL_BYTES[quant] / (CEILING_GBS * 1e9) * 1e3
        out[quant] = {
            "floor_A_ms": intercept * 1e3,
            "parallel_B_ms": slope * 1e3,
            "r2": r2,
            "floor_predicted_from_ceiling_ms": predicted_floor_ms,
            "scaling_threads": list(SCALING_THREADS),
        }
    return out


def render_markdown(per_thread: dict[str, Any], per_quant: dict[str, Any]) -> str:
    lines = [
        "# EXP-003a fit: TOML decode time structure (Axion V2, EXP-002 data)",
        "",
        "## Per thread level: time/token vs model bytes across quants",
        "",
        "| threads | effective GB/s | intercept ms | R^2 | Q4_0 resid ms | Q4_K_M resid ms | Q8_0 resid ms |",
        "|---|---|---|---|---|---|---|",
    ]
    for key in sorted(per_thread, key=lambda k: per_thread[k]["threads"]):
        row = per_thread[key]
        res = row["residual_ms"]
        gbs = row["effective_gbs"]
        gbs_text = f"{gbs:.0f}" if gbs is not None else "n/a"
        lines.append(
            f"| {row['threads']} | {gbs_text} | {row['intercept_ms']:.2f} "
            f"| {row['r2']:.3f} | {res.get('Q4_0', 0.0):+.2f} "
            f"| {res.get('Q4_K_M', 0.0):+.2f} | {res.get('Q8_0', 0.0):+.2f} |"
        )
    lines += [
        "",
        "## Per quant: time/token vs 1/threads (t in {1,2,4,8}; t16 excluded)",
        "",
        "| quant | floor A ms (fit) | floor ms predicted from 150 GB/s | parallel B ms | R^2 |",
        "|---|---|---|---|---|",
    ]
    for quant, row in per_quant.items():
        lines.append(
            f"| {quant} | {row['floor_A_ms']:.2f} "
            f"| {row['floor_predicted_from_ceiling_ms']:.2f} "
            f"| {row['parallel_B_ms']:.2f} | {row['r2']:.4f} |"
        )
    lines += [
        "",
        "Interpretation is written in LOGBOOK.md (EXP-003a results), not "
        "here: this file is the mechanical fit output.",
    ]
    return "\n".join(lines)


def run_fit(exp_dir: Path, out_dir: Path) -> dict[str, Any]:
    if out_dir.exists():
        raise ValueError(
            f"output directory already exists: {out_dir} (experiments are "
            "append-only; pick a new directory)"
        )
    times = load_times(exp_dir)
    per_thread = fit_per_thread(times)
    per_quant = fit_per_quant(times)
    out_dir.mkdir(parents=True)
    payload = {
        "source": str(exp_dir),
        "model_bytes": MODEL_BYTES,
        "per_thread": per_thread,
        "per_quant": per_quant,
    }
    (out_dir / "fit.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    markdown = render_markdown(per_thread, per_quant)
    (out_dir / "fit.md").write_text(markdown + "\n", encoding="utf-8")
    return payload
