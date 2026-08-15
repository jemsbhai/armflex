# Changelog

All notable changes to armflex are documented in this file. The format
follows Keep a Changelog conventions and the project uses semantic
versioning.

## [Unreleased]

### Added

- toml_model extracted from wattwarden: ModelSpec architecture math,
  ArmCpuProfile energy constants, TomlEstimate with derivation and
  stated assumptions, prefill and decode operation counts, and the
  model and profile registries. Thirteen tests migrated with it, and
  the top-level package re-exports the main entry points.
- Project scaffold: pyproject.toml (src layout, zero runtime
  dependencies), package skeleton with version metadata, pytest smoke
  tests, prose scanner, logbook, findings document, changelog,
  gitignore, and env template.
