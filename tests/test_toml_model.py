"""Tests for the TOML energy model: architecture math, scaling behavior,
and honesty flags. No pollard coupling here."""

import pytest

from armflex.toml_model import (
    MODEL_SPECS,
    NEOVERSE_N1,
    QWEN25_0_5B,
    QWEN25_1_5B,
    decode_macs,
    estimate_energy,
    prefill_macs,
    resolve_spec,
)


def test_param_count_qwen_1_5b_matches_published_size():
    # Qwen2.5-1.5B has roughly 1.54e9 parameters.
    assert QWEN25_1_5B.n_params == pytest.approx(1.54e9, rel=0.03)


def test_param_count_qwen_0_5b_matches_published_size():
    # Qwen2.5-0.5B has roughly 0.49e9 parameters.
    assert QWEN25_0_5B.n_params == pytest.approx(0.49e9, rel=0.05)


def test_decode_energy_scales_roughly_linearly_in_output_tokens():
    a = estimate_energy(QWEN25_1_5B, NEOVERSE_N1, "Q4_0", 0, 100)
    b = estimate_energy(QWEN25_1_5B, NEOVERSE_N1, "Q4_0", 0, 200)
    ratio = b.decode_j / a.decode_j
    assert 1.9 < ratio < 2.3


def test_prefill_attention_term_is_exactly_quadratic():
    # Recover the attention component and check it equals L*d*n*(n+1)
    # to the integer. This pins the mechanism without magic thresholds.
    n = 4096
    spec = QWEN25_1_5B
    total = prefill_macs(spec, n)
    weights = n * spec.weight_macs_per_token
    attention = total - weights - spec.lm_head_macs
    expected = spec.n_layers * spec.d_model * n * (n + 1)
    assert attention == expected


def test_prefill_is_superlinear_in_prompt_length():
    # A purely linear prefill would give a doubling ratio just under 2.0
    # (the constant LM head term drags it below). The quadratic attention
    # term must lift it clearly above.
    ratio = prefill_macs(QWEN25_1_5B, 8192) / prefill_macs(QWEN25_1_5B, 4096)
    assert ratio > 2.05


def test_longer_prompt_makes_each_decoded_token_dearer():
    # KV reads across a longer context cost more per generated token.
    near = decode_macs(QWEN25_1_5B, 100, 50)
    far = decode_macs(QWEN25_1_5B, 4000, 50)
    assert far > near


def test_estimate_is_labeled_predicted_and_flags_uncalibrated():
    est = estimate_energy(QWEN25_1_5B, NEOVERSE_N1, "Q4_0", 128, 128)
    assert est.label == "predicted"
    assert any("UNCALIBRATED" in a for a in est.assumptions)


def test_total_is_sum_of_phases():
    est = estimate_energy(QWEN25_1_5B, NEOVERSE_N1, "Q4_0", 128, 128, duration_s=2.0)
    assert est.total_j == pytest.approx(est.prefill_j + est.decode_j + est.static_j)
    assert est.static_j == pytest.approx(NEOVERSE_N1.p_static_w * 2.0)


def test_static_energy_excluded_without_duration():
    est = estimate_energy(QWEN25_1_5B, NEOVERSE_N1, "Q4_0", 128, 128)
    assert est.static_j == 0.0
    assert any("static energy excluded" in a for a in est.assumptions)


def test_energy_is_positive_and_finite_for_typical_call():
    est = estimate_energy(QWEN25_1_5B, NEOVERSE_N1, "Q4_0", 512, 256)
    assert 0.0 < est.total_j < 1e5


def test_q8_costs_more_than_q4_for_identical_call():
    q4 = estimate_energy(QWEN25_1_5B, NEOVERSE_N1, "Q4_0", 256, 256)
    q8 = estimate_energy(QWEN25_1_5B, NEOVERSE_N1, "Q8_0", 256, 256)
    assert q8.total_j > q4.total_j


def test_unknown_quant_raises_with_known_list():
    with pytest.raises(KeyError, match="known:"):
        estimate_energy(QWEN25_1_5B, NEOVERSE_N1, "Q2_K", 10, 10)


def test_resolve_spec_matches_config_style_names():
    assert resolve_spec("qwen2.5-1.5b-instruct-q4_k_m") is QWEN25_1_5B
    assert resolve_spec("QWEN2.5-0.5B-INSTRUCT-Q8_0") is QWEN25_0_5B
    with pytest.raises(KeyError):
        resolve_spec("mystery-model-9b")
    assert set(MODEL_SPECS) == {"qwen2.5-1.5b-instruct", "qwen2.5-0.5b-instruct"}
