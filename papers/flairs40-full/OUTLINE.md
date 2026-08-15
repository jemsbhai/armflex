# FLAIRS-40 full paper: outline

Working title: From Measured Joules to Governed Agents: TOML Energy
Modeling Across Cloud Arm Servers and Heterogeneous Edge Devices

Venue: FLAIRS-40 (2027, St. Pete Beach). The FLAIRS-40 author kit is
not yet released (checked 2026-08-14); structure follows FLAIRS-39
conventions until it is: mandatory FLAIRS template, double-blind
submission with anonymized authors, full papers up to 6 pages
excluding references. Swap in the official kit when published;
deadlines never gate work.

Scope boundary (dual-submission bar): this paper is the SYSTEM and
its reach: wattwarden governance, the full measure-model-govern
pipeline, non-Arm edge devices, and the pollard CPU-metric
contribution. The package internals, the Arm calibration method, and
the ladder measurements are the SoutheastCon core paper, cited here
rather than restated. Overlap is limited to a summary subsection with
citations.

Evidence status legend: [done] = filed in the wattwarden logbook with
artifacts; [pending] = running or awaiting filing; [planned] =
registered or to be registered as EXP-101 onward in the armflex
logbook; [open] = scope decision pending user decree.

## 1. Introduction

- Lineage: TOML introduced at FLAIRS-39 as a model; this paper closes
  the loop: measure the silicon, fit the constants, deploy the
  estimator, and let it govern live agent calls before dispatch.
- Contributions:
  1. wattwarden: sweep driver, configuration advisor, and a pollard
     meter that prices every agent call in joules [done].
  2. Pre-dispatch energy governance demonstrated live: budget vetoes
     before tokens are spent [done].
  3. Cross-ISA reach: the same estimator calibrated beyond Arm on
     x86 (RAPL-class telemetry) and CUDA (NVML) edge hardware, and
     deployed on non-Arm microcontrollers [planned, EXP-1xx].
  4. A CPU-metric contribution to pollard [open: upstream PR vs
     documented integration].
  5. The armflex core, cited: package and Arm ladder results.

## 2. Background

- FLAIRS-39 TOML paper (cite).
- The armflex core paper (cite; package, method, Arm ladder).
- pollard: Runtime, meters with precheck, Budget with extra joules,
  BudgetExceeded as a pre-dispatch veto.

## 3. The wattwarden system

- Architecture: bench and sweep drivers, benchparse, advisor, the
  TOML meter on pollard, governed-agent example.
- The gains ledger, all measured, all one-line configuration changes
  [done, EXP-001/002/004 + advisor]:
  * t16 to t8 serving: 52.4 to 92.8 tok/s, +77% throughput.
  * Cost at recommended config: 3.45 to 1.94 $/Mtok, -44%.
  * KleidiAI to generic build for decode at t16 bench: +17%.
  * Q8_0 to Q4_0 at t8 served: +17% throughput, quality tradeoff
    unmeasured here.
  * Model bytes: 1.89 to 1.07 GB, -44%.

## 4. Arm results, summarized from the core paper

- One subsection, citation-forward: V2 time law A + B/t; KleidiAI
  decode refutation; ~150 GB/s as observed maximum; G3 energy
  anchoring [pending, EXP-003b]; Pi 5 (A76), A53, and M7 legs
  [planned].
- The t16 serving collapse disclosed as unexplained with its bounds
  [done, EXP-004/005].

## 5. Beyond Arm: heterogeneous edge reach [planned]

- The non-Arm slate on hand: the x86 laptop (RAPL-class telemetry via
  HWiNFO or LibreHardwareMonitor) and the RTX 4090 (NVML, which
  pollard already meters: the natural bridge to Section 6).
- ESP32-class boards on hand extend the reach to non-Arm
  microcontrollers: MicroPython estimator deployment on Xtensa or
  RISC-V cores (exact variant recorded at EXP registration),
  mirroring the core paper's Cortex-M7 deployment across ISAs; no
  LLM-on-MCU claim.
- Inventory note: the Raspberry Pi 5 on hand is Arm silicon
  (Cortex-A76) and therefore belongs to the core paper's ladder, not
  this section; no Jetson is in the lab.
- Each device gets a pre-registered EXP-1xx entry in the armflex
  logbook: hypothesis, protocol, predictions before any run.
- The claim under test: the operation-level form transfers across
  ISAs with per-silicon constants; report where it does not.

## 6. The pollard CPU-metric contribution [open]

- Today pollard meters NVML; CPU-side energy is the gap the armflex
  estimator fills.
- Scope decree pending: an upstream PR contributing the armflex meter
  into pollard, or a documented integration shipped from this repo.
- Either way: precheck semantics, Budget joules, and a worked example.

## 7. Governance evaluation [done]

- The live finale on the V2 host: three calls charged 6.65, 8.16, and
  4.41 J against a 30 J budget; the fourth call (max_tokens 100000)
  vetoed BEFORE dispatch by the precheck path.
- What pre-dispatch veto buys over post-hoc accounting.

## 8. Limitations and conclusion

- Estimator error bounds inherit from the core paper's calibration;
  governance decisions are only as good as the constants.
- Cross-ISA constants are per-silicon by construction; no claim of
  universal constants.
- Conclusion: the joule as a first-class budget currency for agents,
  from cloud Arm to the edge.

## Figure and table plan

- Fig: pipeline diagram: measure, fit, deploy, govern.
- Fig: governed-agent transcript timeline with the veto marked.
- Table: gains ledger (Section 3).
- Table: cross-ISA constants with uncertainty, one row per device
  [lands as EXP-1xx results file].
