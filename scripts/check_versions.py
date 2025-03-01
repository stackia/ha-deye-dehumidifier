#!/usr/bin/env python3
"""Script to check version consistency across project files."""

import json
import re
import sys
from typing import Dict, List, Optional, cast


def get_homeassistant_version_from_hacs() -> Optional[str]:
    """Get Home Assistant version from hacs.json."""
    with open("hacs.json", "r") as f:
        data = json.load(f)
    return cast(str, data.get("homeassistant"))


def get_homeassistant_version_from_setup_cfg() -> Optional[str]:
    """Get Home Assistant version from setup.cfg."""
    with open("setup.cfg", "r") as f:
        content = f.read()
    match = re.search(r"homeassistant==([0-9.]+)", content)
    if match:
        return match.group(1)
    return None


def get_libdeye_version_from_manifest() -> Optional[str]:
    """Get libdeye version from manifest.json."""
    with open("custom_components/deye_dehumidifier/manifest.json", "r") as f:
        data = json.load(f)
    for req in data.get("requirements", []):
        if req.startswith("libdeye=="):
            return cast(str, req.split("==")[1])
    return None


def get_libdeye_version_from_setup_cfg() -> Optional[str]:
    """Get libdeye version from setup.cfg."""
    with open("setup.cfg", "r") as f:
        content = f.read()
    match = re.search(r"libdeye==([0-9.]+)", content)
    if match:
        return match.group(1)
    return None


def get_python_version_from_precommit() -> Optional[str]:
    """Get Python version from .pre-commit-config.yaml."""
    with open(".pre-commit-config.yaml", "r") as f:
        content = f.read()
    match = re.search(r"python: python([0-9.]+)", content)
    if match:
        return match.group(1)
    return None


def get_python_version_from_mypy() -> Optional[str]:
    """Get Python version from mypy.ini."""
    with open("mypy.ini", "r") as f:
        content = f.read()
    match = re.search(r"python_version = ([0-9.]+)", content)
    if match:
        return match.group(1)
    return None


def get_python_version_from_workflow() -> Optional[str]:
    """Get Python version from test.yml."""
    with open(".github/workflows/test.yml", "r") as f:
        content = f.read()
    match = re.search(r'python-version: "([0-9.]+)"', content)
    if match:
        return match.group(1)
    return None


def get_python_version_from_setup_cfg() -> Optional[str]:
    """Get Python version from setup.cfg."""
    with open("setup.cfg", "r") as f:
        content = f.read()
    match = re.search(r"python_requires = >=([0-9.]+)", content)
    if match:
        return match.group(1)
    return None


def main() -> None:
    """Check version consistency."""
    errors: List[str] = []

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
    python_versions: Dict[str, Optional[str]] = {
        ".pre-commit-config.yaml": get_python_version_from_precommit(),
        "mypy.ini": get_python_version_from_mypy(),
        "test.yml": get_python_version_from_workflow(),
        "setup.cfg": get_python_version_from_setup_cfg(),
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
    else:
        print("All versions are consistent!")
        sys.exit(0)


if __name__ == "__main__":
    main()
