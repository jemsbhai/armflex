# armflex

Operation-level energy modeling for LLM inference on Arm and edge devices.

armflex packages the TOML energy model (introduced in the FLAIRS-39 paper)
as a standalone Python library with a MicroPython subset. The code is being
extracted from the wattwarden project, which used it to meter and govern
live agent calls on a Neoverse V2 server.

## Mission

1. Extract the model core (toml_model, calibrate, phone_energy) from
   wattwarden into a dependency-free package and publish it to PyPI.
2. Ship a MicroPython subset of the estimator via mip, validated on a
   Cortex-M7 board (Arduino Giga): the energy model deploys where the LLM
   cannot.
3. Serve as the vessel for two papers:
   - IEEE SoutheastCon: the armflex core paper (package, method, Arm
     results).
   - FLAIRS-40 full paper: wattwarden plus armflex plus non-Arm edge
     devices plus pollard CPU-metric contributions. Substantially
     different in scope from the core paper, and cites it.

## Status

Pre-release scaffold. Nothing is published yet. See CHANGELOG.md for
package history and LOGBOOK.md for experiments.

## Development setup

```powershell
git clone https://github.com/jemsbhai/armflex
cd armflex
pip install -e ".[dev]"
pytest
python scripts\scan_prose.py .
```

The core has zero runtime dependencies. Python 3.10 or newer.

## Repository layout

- src/armflex/: package source
- tests/: pytest suite; every commit requires a green run
- scripts/scan_prose.py: banned-vocabulary and typography scan for all
  Markdown in the repo; runs before every commit
- LOGBOOK.md: pre-registered experiments, numbered EXP-101 onward
- findings.md: curated summary plus a raw findings log
- papers/: LaTeX sources for the two papers (added later)

## Relationship to wattwarden and pollard

wattwarden (https://github.com/jemsbhai/wattwarden) is the upstream
project and the first consumer: after extraction, wattwarden depends on
armflex. pollard meters the runtime side; the planned CPU-metric
contribution to pollard is tracked in the FLAIRS-40 paper scope.

## License

MIT. See LICENSE.
