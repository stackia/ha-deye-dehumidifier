# Contributing

This repository uses [uv](https://docs.astral.sh/uv/) for Python versions,
a project virtual environment, and locked dependencies.

## Local development with Home Assistant core

To setup a local development environment, here are the recommended workflow:

1. Follow [instructions here](https://developers.home-assistant.io/docs/development_environment/#developing-with-visual-studio-code--devcontainer) to open the home-assistant/core repo in a VSCode devcontainer. If you are having trouble during repo cloning, try running `ssh-add` in your host machine.
2. Open a terminal in VSCode and run:

```sh
cd /workspaces
git clone git@github.com:stackia/ha-deye-dehumidifier.git
git clone git@github.com:stackia/libdeye.git
cd /workspace/core
mkdir -p config/custom_components
ln -s /workspaces/ha-deye-dehumidifier/custom_components/deye_dehumidifier /workspaces/core/config/custom_components/deye_dehumidifier
# Install Home Assistant core (official core-repo workflow)
pip install -e .
```

3. Select `File -> Add Folder to Workspace...` in VSCode, add both `/workspaces/ha-deye-dehumidifier` and `/workspaces/libdeye` into the workspace.
4. Select `File -> Save Workspace As...`, save the workspace into `/workspaces/hass.code-workspace`.
5. Edit settings for this workspace, add `"python.analysis.extraPaths": ["/workspaces/core", "/workspaces/libdeye"]`
6. Press F5 to start running a Home Assistant instance. This integration should be available now.
7. To debug `libdeye` locally, please refer to [this link](https://developers.home-assistant.io/docs/creating_integration_manifest/#custom-requirements-during-development--testing).

## Tooling in this repository

From the integration repository root:

```sh
# Install uv: https://docs.astral.sh/uv/getting-started/installation/
uv sync
uv run pre-commit install
uv run mypy .
uv run python scripts/check_versions.py
```

`uv sync` creates `.venv` and installs the `dev` dependency group from `uv.lock`.
This project is not installed as a package (`[tool.uv] package = false`); the
Home Assistant custom component lives under `custom_components/`.

To develop against a local checkout of `libdeye`:

```sh
uv add --editable ../libdeye
```
