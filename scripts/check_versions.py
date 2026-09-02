#!/usr/bin/env python3
"""Script to check version consistency across project files."""

import json
from pathlib import Path
import re
import sys
import tomllib
from typing import Any


def load_pyproject() -> dict[str, Any]:
    """Load project metadata from pyproject.toml."""
    with Path("pyproject.toml").open("rb") as f:
        return tomllib.load(f)


def get_project_dependency_version(pyproject: dict[str, Any], name: str) -> str | None:
    """Get a pinned runtime dependency version from pyproject.toml."""
    for dep in pyproject["project"].get("dependencies", []):
        if isinstance(dep, str) and dep.startswith(f"{name}=="):
            return dep.split("==", 1)[1]
    return None


def get_dev_dependency_version(pyproject: dict[str, Any], name: str) -> str | None:
    """Get a pinned dev dependency version from pyproject.toml."""
    for dep in pyproject.get("dependency-groups", {}).get("dev", []):
        if isinstance(dep, str) and dep.startswith(f"{name}=="):
            return dep.split("==", 1)[1]
    return None


def get_requires_python(pyproject: dict[str, Any]) -> str | None:
    """Get the minimum Python version from requires-python."""
    requires = pyproject["project"].get("requires-python", "")
    match = re.search(r">=([0-9.]+)", requires)
    return match.group(1) if match else None


def normalize_python_version(version: str | None) -> str | None:
    """Normalize a Python version to major.minor for cross-file comparison."""
    if version is None:
        return None
    parts = version.split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return version


def get_json_field(path: str, field: str) -> str | None:
    """Get a string field from a JSON file."""
    with Path(path).open(encoding="utf-8") as f:
        data = json.load(f)
    value = data.get(field)
    return value if isinstance(value, str) else None


def get_libdeye_version_from_manifest() -> str | None:
    """Get libdeye version from manifest.json."""
    with Path("custom_components/deye_dehumidifier/manifest.json").open(
        encoding="utf-8"
    ) as f:
        data = json.load(f)
    for req in data.get("requirements", []):
        if isinstance(req, str) and req.startswith("libdeye=="):
            return req.split("==", 1)[1]
    return None


def get_python_version_from_precommit() -> str | None:
    """Get Python version from .pre-commit-config.yaml."""
    content = Path(".pre-commit-config.yaml").read_text(encoding="utf-8")
    match = re.search(r"python: python([0-9.]+)", content)
    return match.group(1) if match else None


def get_python_version_file() -> str | None:
    """Get Python version from .python-version."""
    path = Path(".python-version")
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def main() -> None:
    """Check version consistency."""
    errors: list[str] = []
    pyproject = load_pyproject()

    project_version = pyproject["project"].get("version")
    manifest_version = get_json_field(
        "custom_components/deye_dehumidifier/manifest.json", "version"
    )
    if project_version != manifest_version:
        errors.append(
            "Integration version mismatch: "
            f"{project_version} (pyproject.toml) vs {manifest_version} (manifest.json)"
        )

    ha_hacs = get_json_field("hacs.json", "homeassistant")
    ha_dev = get_dev_dependency_version(pyproject, "homeassistant")
    if ha_hacs != ha_dev:
        errors.append(
            "Home Assistant version mismatch: "
            f"{ha_hacs} (hacs.json) vs {ha_dev} (pyproject.toml)"
        )

    libdeye_manifest = get_libdeye_version_from_manifest()
    libdeye_project = get_project_dependency_version(pyproject, "libdeye")
    if libdeye_manifest != libdeye_project:
        errors.append(
            "libdeye version mismatch: "
            f"{libdeye_manifest} (manifest.json) vs {libdeye_project} (pyproject.toml)"
        )

    python_versions: dict[str, str | None] = {
        ".pre-commit-config.yaml": normalize_python_version(
            get_python_version_from_precommit()
        ),
        "pyproject.toml [tool.mypy]": normalize_python_version(
            pyproject.get("tool", {}).get("mypy", {}).get("python_version")
        ),
        ".python-version": normalize_python_version(get_python_version_file()),
        "pyproject.toml requires-python": normalize_python_version(
            get_requires_python(pyproject)
        ),
    }

    reference_file = None
    reference_version = None
    for file, version in python_versions.items():
        if version is not None:
            reference_file = file
            reference_version = version
            break

    if reference_version is not None:
        for file, version in python_versions.items():
            if version is not None and version != reference_version:
                errors.append(
                    f"Python version mismatch: {reference_version} ({reference_file}) "
                    f"vs {version} ({file})"
                )

    if errors:
        for error in errors:
            print(error)
        sys.exit(1)

    print("All versions are consistent!")
    sys.exit(0)


if __name__ == "__main__":
    main()
