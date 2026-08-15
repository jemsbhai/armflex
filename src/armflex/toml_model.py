"""The TOML operation-level energy model for Arm CPU LLM inference.

This module is pure model: architecture specs, operation counts, and energy
estimation. It has no pollard coupling; the pollard meter adapter lives
downstream in wattwarden's meter.py.

Method: count multiply-accumulate operations and DRAM traffic for prefill
and decode phases of decoder-only transformer inference, then price them
with per-operation energy constants from an ArmCpuProfile. Estimates are
predictions, always labeled as such. Profiles ship uncalibrated; EXP-002
fits the constants and flips the calibrated flag. Uncalibrated numbers are
for relative comparison and admission control only, never for reporting.

Stated modeling assumptions (also surfaced in every estimate):
- Weight MACs per token equal the matmul parameter count (one MAC per
  weight); embedding lookup is treated as free.
- Attention score MACs per token at context c are 2 * L * d * c.
- Prefill is compute-priced: weights are read once in total; activations
  are ignored.
- Decode is bandwidth-priced: full weight bytes are read per generated
  token, plus KV cache reads across the current context and one KV write.
- The LM head runs once per generated token plus once at the end of
  prefill.
- Static power is charged only when a wall-clock duration is supplied.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PJ_TO_J = 1e-12

# Nominal effective bits per weight for GGUF quantizations, including scale
# and block overheads. Nominal figures; the bytes they imply are inputs to
# calibration, not reported results.
QUANT_BITS_EFFECTIVE: dict[str, float] = {
    "Q4_0": 4.5,
    "Q4_K_M": 4.85,
    "Q8_0": 8.5,
    "F16": 16.0,
}


@dataclass(frozen=True)
class ModelSpec:
    """Decoder-only transformer architecture, GQA and SwiGLU aware.

    Dimension sources: the model's published HF config.json.
    """

    name: str
    n_layers: int
    d_model: int
    n_heads: int
    n_kv_heads: int
    d_ff: int
    vocab: int
    tie_embeddings: bool = True

    @property
    def head_dim(self) -> int:
        return self.d_model // self.n_heads

    @property
    def kv_dim(self) -> int:
        return self.n_kv_heads * self.head_dim

    @property
    def weight_macs_per_token(self) -> int:
        """Matmul MACs per token, excluding attention scores and LM head."""
        attn = 2 * self.d_model * self.d_model + 2 * self.d_model * self.kv_dim
        mlp = 3 * self.d_model * self.d_ff
        return self.n_layers * (attn + mlp)

    @property
    def lm_head_macs(self) -> int:
        return self.d_model * self.vocab

    @property
    def n_params(self) -> int:
        """Approximate parameter count (norms and biases ignored)."""
        embeddings = self.vocab * self.d_model
        if not self.tie_embeddings:
            embeddings *= 2
        return embeddings + self.weight_macs_per_token

    def weight_bytes(self, quant: str) -> float:
        bits = _quant_bits(quant)
        return self.n_params * bits / 8.0

    def kv_bytes_per_token(self, kv_cache_bytes_per_value: int = 2) -> int:
        """Bytes to store K and V for one token across all layers (f16)."""
        return 2 * self.n_layers * self.kv_dim * kv_cache_bytes_per_value


@dataclass(frozen=True)
class ArmCpuProfile:
    """Per-operation energy constants for one Arm CPU target.

    All energy constants are picojoules. calibrated=False means the values
    are placeholders pending fitting (EXP-002) and must never be reported
    as results.
    """

    name: str
    e_mac_pj: dict[str, float]
    e_dram_pj_per_byte: float
    p_static_w: float
    calibrated: bool
    provenance: str

    def mac_energy_j(self, quant: str, macs: float) -> float:
        try:
            per_op = self.e_mac_pj[quant]
        except KeyError as exc:
            known = ", ".join(sorted(self.e_mac_pj))
            raise KeyError(
                f"profile {self.name!r} has no MAC energy for quant {quant!r}; "
                f"known: {known}"
            ) from exc
        return macs * per_op * PJ_TO_J

    def dram_energy_j(self, byte_count: float) -> float:
        return byte_count * self.e_dram_pj_per_byte * PJ_TO_J


@dataclass(frozen=True)
class TomlEstimate:
    """A predicted energy figure with its full derivation attached."""

    label: str
    model: str
    profile: str
    quant: str
    prompt_tokens: int
    output_tokens: int
    prefill_j: float
    decode_j: float
    static_j: float
    breakdown: dict[str, float]
    assumptions: tuple[str, ...]

    @property
    def total_j(self) -> float:
        return self.prefill_j + self.decode_j + self.static_j


def prefill_macs(spec: ModelSpec, prompt_tokens: int) -> float:
    """Weight MACs plus quadratic attention-score MACs for the prompt."""
    if prompt_tokens <= 0:
        return 0.0
    weights = prompt_tokens * spec.weight_macs_per_token
    attention = spec.n_layers * spec.d_model * prompt_tokens * (prompt_tokens + 1)
    return float(weights + attention + spec.lm_head_macs)


def decode_macs(spec: ModelSpec, prompt_tokens: int, output_tokens: int) -> float:
    """MACs to generate output_tokens starting from a prompt_tokens context."""
    if output_tokens <= 0:
        return 0.0
    n_o = output_tokens
    weights = n_o * (spec.weight_macs_per_token + spec.lm_head_macs)
    context_sum = n_o * prompt_tokens + n_o * (n_o + 1) // 2
    attention = 2 * spec.n_layers * spec.d_model * context_sum
    return float(weights + attention)


def decode_bytes(
    spec: ModelSpec, quant: str, prompt_tokens: int, output_tokens: int
) -> float:
    """DRAM bytes for decode: weights per token, KV reads, KV writes."""
    if output_tokens <= 0:
        return 0.0
    n_o = output_tokens
    weights = n_o * spec.weight_bytes(quant)
    kv_tok = spec.kv_bytes_per_token()
    context_sum = n_o * prompt_tokens + n_o * (n_o + 1) // 2
    kv_reads = kv_tok * context_sum
    kv_writes = kv_tok * n_o
    return float(weights + kv_reads + kv_writes)


def prefill_bytes(spec: ModelSpec, quant: str, prompt_tokens: int) -> float:
    """DRAM bytes for prefill: one full weight read plus KV writes."""
    if prompt_tokens <= 0:
        return 0.0
    return float(spec.weight_bytes(quant) + spec.kv_bytes_per_token() * prompt_tokens)


def estimate_energy(
    spec: ModelSpec,
    profile: ArmCpuProfile,
    quant: str,
    prompt_tokens: int,
    output_tokens: int,
    duration_s: float | None = None,
) -> TomlEstimate:
    """Predict joules for one inference call. Prediction, not measurement."""
    pf_macs = prefill_macs(spec, prompt_tokens)
    dc_macs = decode_macs(spec, prompt_tokens, output_tokens)
    pf_bytes = prefill_bytes(spec, quant, prompt_tokens)
    dc_bytes = decode_bytes(spec, quant, prompt_tokens, output_tokens)

    prefill_j = profile.mac_energy_j(quant, pf_macs) + profile.dram_energy_j(pf_bytes)
    decode_j = profile.mac_energy_j(quant, dc_macs) + profile.dram_energy_j(dc_bytes)
    static_j = profile.p_static_w * duration_s if duration_s is not None else 0.0

    assumptions = list(_BASE_ASSUMPTIONS)
    if not profile.calibrated:
        assumptions.append(
            f"profile {profile.name!r} is UNCALIBRATED: constants are "
            "placeholders pending EXP-002; use for relative comparison and "
            "admission control only"
        )
    if duration_s is None:
        assumptions.append("no duration supplied: static energy excluded")

    return TomlEstimate(
        label="predicted",
        model=spec.name,
        profile=profile.name,
        quant=quant,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        prefill_j=prefill_j,
        decode_j=decode_j,
        static_j=static_j,
        breakdown={
            "prefill_macs": pf_macs,
            "decode_macs": dc_macs,
            "prefill_dram_bytes": pf_bytes,
            "decode_dram_bytes": dc_bytes,
        },
        assumptions=tuple(assumptions),
    )


_BASE_ASSUMPTIONS = (
    "one MAC per matmul weight per token; embedding lookup free",
    "attention score MACs per token at context c: 2*L*d*c",
    "prefill compute-priced with a single full weight read",
    "decode bandwidth-priced: full weight bytes per generated token",
    "LM head once per generated token plus once at prefill end",
)


def _quant_bits(quant: str) -> float:
    try:
        return QUANT_BITS_EFFECTIVE[quant]
    except KeyError as exc:
        known = ", ".join(sorted(QUANT_BITS_EFFECTIVE))
        raise KeyError(f"unknown quant {quant!r}; known: {known}") from exc


# Model registry. Dimensions transcribed from published HF config.json files.
QWEN25_1_5B = ModelSpec(
    name="qwen2.5-1.5b-instruct",
    n_layers=28,
    d_model=1536,
    n_heads=12,
    n_kv_heads=2,
    d_ff=8960,
    vocab=151936,
    tie_embeddings=True,
)

QWEN25_0_5B = ModelSpec(
    name="qwen2.5-0.5b-instruct",
    n_layers=24,
    d_model=896,
    n_heads=14,
    n_kv_heads=2,
    d_ff=4864,
    vocab=151936,
    tie_embeddings=True,
)

MODEL_SPECS: dict[str, ModelSpec] = {
    QWEN25_1_5B.name: QWEN25_1_5B,
    QWEN25_0_5B.name: QWEN25_0_5B,
}


def resolve_spec(model_name: str) -> ModelSpec:
    """Match a model or file name like qwen2.5-1.5b-instruct-q4_0 to a spec."""
    key = model_name.strip().lower()
    if key in MODEL_SPECS:
        return MODEL_SPECS[key]
    for name, spec in MODEL_SPECS.items():
        if key.startswith(name):
            return spec
    known = ", ".join(sorted(MODEL_SPECS))
    raise KeyError(f"no ModelSpec matches {model_name!r}; known: {known}")


# Placeholder profiles. Order-of-magnitude system-level constants so that
# relative comparisons behave sensibly before calibration. EXP-002 replaces
# them with fitted values and sets calibrated=True.
NEOVERSE_N1 = ArmCpuProfile(
    name="neoverse-n1",
    e_mac_pj={"Q4_0": 2.5, "Q4_K_M": 2.7, "Q8_0": 3.5, "F16": 6.0},
    e_dram_pj_per_byte=60.0,
    p_static_w=6.0,
    calibrated=False,
    provenance="placeholder pending EXP-002 fit on Oracle A1; do not report",
)

NEOVERSE_V2 = ArmCpuProfile(
    name="neoverse-v2",
    e_mac_pj={"Q4_0": 1.8, "Q4_K_M": 2.0, "Q8_0": 2.6, "F16": 4.5},
    e_dram_pj_per_byte=45.0,
    p_static_w=6.0,
    calibrated=False,
    provenance="placeholder pending EXP-00x fit on a V2 instance; do not report",
)

PROFILES: dict[str, ArmCpuProfile] = {
    NEOVERSE_N1.name: NEOVERSE_N1,
    NEOVERSE_V2.name: NEOVERSE_V2,
}
