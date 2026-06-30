# AGENTS.md

## Cursor Cloud specific instructions

This repo is a **Home Assistant custom integration** (`custom_components/deye_dehumidifier`) for Deye dehumidifiers. It is not a standalone app — the "application" is a Home Assistant instance with this integration loaded. Requires **Python 3.13**.

### Environment / tooling
- Dependencies live in a local venv at `.venv`, created with [`uv`](https://docs.astral.sh/uv/) (installed at `~/.local/bin`). The startup update script handles installing Python 3.13, creating `.venv`, and installing `.[dev]`.
- Activate the venv with `source .venv/bin/activate` (or prefix commands with `.venv/bin/`). If `uv` is not on your PATH, use `~/.local/bin/uv`.

### Lint / type / version checks (mirrors CI in `.github/workflows`)
- Type check: `mypy .`
- Version consistency: `python scripts/check_versions.py`
- Full lint suite (isort, flake8, black, file hygiene): `pre-commit run --all-files`

### Running the app (Home Assistant dev instance)
- A HA config dir lives at `/home/ubuntu/ha-config`. It contains `configuration.yaml` and a symlink `custom_components/deye_dehumidifier -> /workspace/custom_components/deye_dehumidifier`. If that dir/symlink is missing (e.g. fresh VM), recreate it:
  ```sh
  mkdir -p /home/ubuntu/ha-config/custom_components
  ln -sfn /workspace/custom_components/deye_dehumidifier /home/ubuntu/ha-config/custom_components/deye_dehumidifier
  ```
- Start HA: `source .venv/bin/activate && hass -c /home/ubuntu/ha-config`. UI is at `http://localhost:8123`.
- An owner account is already onboarded: `testuser` / `testpassword123` (persists via snapshot).

### Non-obvious caveats
- **Dependency pins to run HA:** installing `.[dev]` resolves two transitive deps to versions that crash HA 2024.11 on startup. They must be pinned back: `josepy<2` (newer `josepy` removed `ComparableX509` needed by `acme`) and `pycares<5` (newer `pycares` changed `getaddrinfo` signature, breaking `aiodns`). The update script applies these pins after the main install.
- **`default_config`** pulls optional components (camera/stream/voice) that compile native wheels (`PyTurboJPEG`, `pymicro-vad`, `pyspeex-noise`); these need system packages `build-essential` and `libturbojpeg0-dev` (already in the snapshot). These components are unrelated to this integration — if they fail to set up, it does not affect `deye_dehumidifier`.
- **Completing the config flow** (adding a real device) requires real Deye Smart app credentials (phone number + password) and cloud/MQTT access. Without credentials you can only verify the integration loads and its config flow form opens — actual device data cannot be fetched.
- There are no automated unit tests in this repo; correctness is enforced via `mypy` + `pre-commit` + `scripts/check_versions.py`.
