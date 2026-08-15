"""Scaffold smoke tests: the package imports and reports a version."""

import armflex


def test_import_exposes_version():
    assert isinstance(armflex.__version__, str)
    assert armflex.__version__


def test_version_is_semver_shaped():
    parts = armflex.__version__.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)
