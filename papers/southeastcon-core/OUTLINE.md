# SoutheastCon core paper: outline

Working title: armflex: The TOML Operation-Level Energy Model for LLM
Inference Across the Arm Silicon Ladder

Venue: IEEE SoutheastCon (Region 3). Format: IEEEtran conference.
Author list, page limit, and review model to be confirmed from the
SoutheastCon 2027 CFP when it posts; deadlines never gate work.

Scope boundary (dual-submission bar): this paper is the package, the
method, and the Arm measurements. It does NOT cover the wattwarden
governance system, agent budget vetoes, non-Arm edge devices, or
pollard contributions; those belong to the FLAIRS-40 full paper,
which cites this one.

Evidence status legend used below: [done] = filed in the wattwarden
logbook with artifacts; [pending] = running or awaiting filing;
[planned] = registered or to be registered as EXP-101 onward in the
armflex logbook before any run.

## 1. Introduction

- Problem: LLM inference is moving onto Arm CPUs from cloud servers
  to phones and microcontrollers; energy is the binding resource, but
  per-call energy is rarely measurable in deployment.
- Answer: an operation-level model (TOML, FLAIRS-39 lineage) that
  prices MACs and DRAM traffic, calibrated once per silicon, then
  deployed as a zero-dependency estimator, down to MicroPython on
  Cortex-M7 where the LLM itself cannot run.
- Contributions:
  1. armflex, an open-source package: model core, calibration
     machinery, battery-telemetry analyzer; zero runtime deps.
  2. A calibrated decode time law on Neoverse V2: time/token =
     A + B/t, R^2 0.999 to 1.0000, with quant-independent floors
     [done, EXP-003a].
  3. Energy anchoring on Tensor G3 via battery telemetry with a
     three-parameter fit including static power [pending, EXP-003b].
  4. The remaining ladder legs [planned]: Cortex-A53 energy and
     timing on the Uno Q, a Raspberry Pi 5 rung (Cortex-A76), and
     the MicroPython estimator deployment on Cortex-M7.
  5. Honesty machinery as a design feature: estimates labeled
     predicted, assumptions surfaced in every result, uncalibrated
     profiles refuse to be reportable.

## 2. Background and related work

- TOML at FLAIRS-39 (cite; the origin of the operation-level method).
- Roofline-style and bandwidth-bound reasoning for decode.
- llama.cpp, GGUF quantization, KleidiAI kernels (measured, not
  assumed, per Section 5).

## 3. The model

- ModelSpec: GQA and SwiGLU aware architecture math from published
  config.json dimensions.
- Operation counts: prefill compute-priced (single full weight read),
  decode bandwidth-priced (full weight bytes per generated token, KV
  reads across context, one KV write), LM head accounting.
- The stated-assumptions list, verbatim from the package.
- Correction surfaced by data [done, EXP-001 side observation]: this
  GGUF stores the output head untied (1,777,088,000 stored vs 1.543e9
  architectural parameters), so decode byte pricing uses measured
  model_size, not architectural counts; 4.77 effective bits/weight.

## 4. The armflex package

- Zero-dependency core; src layout; append-only analysis guards.
- Calibration module: closed-form least squares, per-thread and
  per-quant fits.
- Phone telemetry module: locked unit rules, trapezoid integration,
  baseline netting, protocol-violation flags counted never hidden.
- MicroPython subset via mip, targeting Cortex-M7 (Arduino Giga): the
  estimator deploys where the LLM cannot; no LLM-on-M7 claim.

## 5. Calibration on the ladder

- Neoverse V2 (Google Axion, c4a-standard-16, Debian 13, llama.cpp
  6fed9f6ff, Qwen2.5-1.5B-Instruct) [done]:
  * EXP-001: KleidiAI refuted for decode: tg 0.935x at t8 (87.6 vs
    93.7 tok/s) and 0.853x at t16 (120.1 vs 140.9); pp roughly 1.01x.
    Kernel identity attested by perf: 60.37% of decode self time in
    ggml_gemv_q4_0_4x8_q8_0 via the runtime repack path.
  * EXP-002: quant x thread sweep; best served Q4_0 t8 at 92.8 tok/s,
    TTFT 14.8 ms.
  * EXP-003a: time/token = A + B/t over t in {1,2,4,8}; floors A
    quant-independent (4.44, 4.55, 3.95 ms), so the serial component
    is per-token overhead, not weight streaming; B = 54.67, 63.39,
    68.16 ms; the cross-quant bytes regression is not identifiable
    (R^2 0.41 to 0.87); ~150 GB/s downgraded from ceiling to observed
    maximum (150.8 GB/s, Q8_0 t8 served).
- Tensor G3 (Pixel 8 Pro, Termux) [pending, EXP-003b]: battery
  telemetry at 1 Hz, discharge-only guard, trapezoid integration,
  baseline netting, three-parameter fit adding static power times
  bench decode time. Numbers land here when the wattwarden logbook
  files them; the pre-registered predictions are not citable results.
- Raspberry Pi 5 (Cortex-A76) [planned, EXP-1xx]: llama.cpp timings
  plus USB input energy via the inline USB power meter (FNIRSI on
  hand; meter model and logging protocol locked in the EXP entry
  before any run). Adds a big-core single-board rung between the
  phone SoC and the small cores.
- Cortex-A53 (Arduino Uno Q, Debian side) [planned, EXP-1xx]:
  llama.cpp time measurements plus input energy via the same inline
  meter.
- Cortex-M7 (Arduino Giga, MicroPython) [planned, EXP-1xx]: estimator
  deployment validation: numerical agreement with CPython reference
  and on-device runtime cost.

## 6. Limitations, disclosed

- The t16 serving collapse on V2 is real, bounded (onset t9..t14),
  server-side, and its mechanism is recorded unexplained
  [done, EXP-004, EXP-005]; the operational rule (serve at t <= 8 on
  this host) does not depend on the mechanism.
- Measurement windows on the phone include model load; -n 512 bounds
  the contamination to a few percent.
- Placeholder profiles are never reported; only fitted constants with
  uncertainty are.

## 7. Conclusion

- One model, one calibration recipe, an Arm ladder from server to
  microcontroller; the estimator travels lighter than the workload it
  prices.

## Figure and table plan

- Fig: time/token vs 1/threads per quant with fitted lines (from
  wattwarden experiments/exp_003_time_fit artifacts, regenerated by
  script).
- Fig: KleidiAI vs generic tg bars at t8/t16 (EXP-001).
- Table: ladder summary: silicon, what was measured, which constants
  calibrated, status.
- Table: fitted constants with uncertainty (V2 time law; G3 energy
  constants when filed).
