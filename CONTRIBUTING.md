# Contributing

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
pip install -e .
```

3. Select `File -> Add Folder to Workspace...` in VSCode, add both `/workspaces/ha-deye-dehumidifier` and `/workspaces/libdeye` into the workspace.
4. Select `File -> Save Workspace As...`, save the workspace into `/workspaces/hass.code-workspace`.
5. Edit settings for this workspace, add `"python.analysis.extraPaths": ["/workspaces/core", "/workspaces/libdeye"]`
6. Press F5 to start running a Home Assistant instance. This integration should be available now.
7. To debug `libdeye` locally, please refer to [this link](https://developers.home-assistant.io/docs/creating_integration_manifest/#custom-requirements-during-development--testing).
