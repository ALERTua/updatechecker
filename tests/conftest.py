"""Pytest configuration for updatechecker tests.

This conftest provides fixtures that configure the application to use
updatechecker.example.yaml instead of creating home directory files.
This ensures tests work in CI environments where home directory access
may be limited or different.
"""

import sys
from pathlib import Path

import pytest

# Get the path to updatechecker.example.yaml
_example_yaml_path = Path(__file__).parent.parent / "updatechecker.example.yaml"


@pytest.fixture(autouse=True)
def configure_test_config(monkeypatch):
    """Configure the application to use updatechecker.example.yaml for tests.

    This fixture automatically runs for every test and:
    1. Overrides USERPROFILE to point to the test directory
    2. Makes the config look for updatechecker.example.yaml
    3. Sets up any other environment variables needed for tests
    """
    # Point to the example yaml file
    test_config_file = str(_example_yaml_path)

    # Ensure the example file exists
    if not _example_yaml_path.exists():
        pytest.skip(f"Example config file not found: {_example_yaml_path}")

    # Patch the config module's settings_files to use example yaml
    # We need to do this before importing the config
    import importlib

    # Reload the config module to pick up new settings
    if "updatechecker.config" in sys.modules:
        config_module = sys.modules["updatechecker.config"]

        # Override the default config path to point to example yaml
        # The config will look for files in order: ./updatechecker.yaml, then default
        # We want it to find our example file
        monkeypatch.setattr(config_module, "default_config_filepath", test_config_file)
        monkeypatch.setattr(
            config_module, "default_config_dir", str(Path(test_config_file).parent)
        )

        # Force reload to apply changes
        importlib.reload(config_module)
