#!/usr/bin/env python3
"""Script to check version consistency across project files."""

import json
from pathlib import Path
import re
import sys
from typing import cast


def _read_text(path: str) -> str:
    """Read a UTF-8 text file from the repository root."""
    return Path(path).read_text(encoding="utf-8")


def get_homeassistant_version_from_hacs() -> str | None:
    """Get Home Assistant version from hacs.json."""
    data = json.loads(_read_text("hacs.json"))
    return cast(str, data.get("homeassistant"))


def get_homeassistant_version_from_setup_cfg() -> str | None:
    """Get Home Assistant version from setup.cfg."""
    match = re.search(r"homeassistant==([0-9.]+)", _read_text("setup.cfg"))
    if match:
        return match.group(1)
    return None


def get_libdeye_version_from_manifest() -> str | None:
    """Get libdeye version from manifest.json."""
    data = json.loads(_read_text("custom_components/deye_dehumidifier/manifest.json"))
    for req in data.get("requirements", []):
        if req.startswith("libdeye=="):
            return cast(str, req.split("==")[1])
    return None


def get_libdeye_version_from_setup_cfg() -> str | None:
    """Get libdeye version from setup.cfg."""
    match = re.search(r"libdeye==([0-9.]+)", _read_text("setup.cfg"))
    if match:
        return match.group(1)
    return None


def get_python_version_from_precommit() -> str | None:
    """Get Python version from .pre-commit-config.yaml."""
    match = re.search(r"python: python([0-9.]+)", _read_text(".pre-commit-config.yaml"))
    if match:
        return match.group(1)
    return None


def get_python_version_from_mypy() -> str | None:
    """Get Python version from mypy.ini."""
    match = re.search(r"python_version = ([0-9.]+)", _read_text("mypy.ini"))
    if match:
        return match.group(1)
    return None


def get_python_version_from_workflow() -> str | None:
    """Get Python version from test.yml."""
    match = re.search(
        r'python-version: "([0-9.]+)"', _read_text(".github/workflows/test.yml")
    )
    if match:
        return match.group(1)
    return None


def get_python_version_from_setup_cfg() -> str | None:
    """Get Python version from setup.cfg."""
    match = re.search(r"python_requires = >=([0-9.]+)", _read_text("setup.cfg"))
    if match:
        return match.group(1)
    return None


def get_python_version_from_python_version_file() -> str | None:
    """Get Python version from .python-version."""
    return _read_text(".python-version").strip() or None


def main() -> None:
    """Check version consistency."""
    errors: list[str] = []

    # Check Home Assistant version
    ha_hacs = get_homeassistant_version_from_hacs()
    ha_setup = get_homeassistant_version_from_setup_cfg()

    if ha_hacs != ha_setup:
        errors.append(
            f"Home Assistant version mismatch: {ha_hacs} (hacs.json) vs {ha_setup} (setup.cfg)"
        )

    # Check libdeye version
    libdeye_manifest = get_libdeye_version_from_manifest()
    libdeye_setup = get_libdeye_version_from_setup_cfg()

    if libdeye_manifest != libdeye_setup:
        errors.append(
            f"libdeye version mismatch: {libdeye_manifest} (manifest.json) vs {libdeye_setup} (setup.cfg)"
        )

    # Check Python version - collect all versions
    python_versions: dict[str, str | None] = {
        ".pre-commit-config.yaml": get_python_version_from_precommit(),
        "mypy.ini": get_python_version_from_mypy(),
        "test.yml": get_python_version_from_workflow(),
        "setup.cfg": get_python_version_from_setup_cfg(),
        ".python-version": get_python_version_from_python_version_file(),
    }

    # Use first non-None version as reference
    reference_file = None
    reference_version = None
    for file, version in python_versions.items():
        if version is not None:
            reference_file = file
            reference_version = version
            break

    # Compare all versions to the reference
    if reference_version is not None:
        for file, version in python_versions.items():
            if version is not None and version != reference_version:
                errors.append(
                    f"Python version mismatch: {reference_version} ({reference_file}) vs {version} ({file})"
                )

    if errors:
        for error in errors:
            print(error)
        sys.exit(1)

    print("All versions are consistent!")
    sys.exit(0)


if __name__ == "__main__":
    main()
