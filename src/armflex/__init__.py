"""armflex: operation-level energy modeling for LLM inference on Arm and
edge devices.

The core is dependency-free. Modules arrive by extraction from
wattwarden: toml_model and calibrate (landed), phone_energy (pending).
"""

from armflex.toml_model import (
    MODEL_SPECS,
    PROFILES,
    ArmCpuProfile,
    ModelSpec,
    TomlEstimate,
    estimate_energy,
    resolve_spec,
)

__version__ = "0.0.1"

__all__ = [
    "__version__",
    "ArmCpuProfile",
    "MODEL_SPECS",
    "ModelSpec",
    "PROFILES",
    "TomlEstimate",
    "estimate_energy",
    "resolve_spec",
]
