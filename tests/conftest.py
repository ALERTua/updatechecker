"""Pytest configuration for updatechecker tests.

This conftest provides fixtures that configure the application to use
updatechecker.example.yaml instead of creating home directory files.
This ensures tests work in CI environments where home directory access
may be limited or different.
"""

import os
from pathlib import Path

import pytest

# Get the path to updatechecker.example.yaml
_example_yaml_path = Path(__file__).parent.parent / "updatechecker.example.yaml"


@pytest.fixture(autouse=True, scope="session")
def configure_test_config():
    """Configure the application to use updatechecker.example.yaml for tests.

    This fixture runs once per test session and sets environment variables
    to point the config to updatechecker.example.yaml.
    """
    # Ensure the example file exists
    if not _example_yaml_path.exists():
        pytest.skip(f"Example config file not found: {_example_yaml_path}")

    # Set environment variables to point to example yaml
    # The config looks for updatechecker.yaml in the config directory
    test_config_dir = str(Path(_example_yaml_path).parent)

    # Override USERPROFILE to point to the test directory
    # This makes the config look for updatechecker.yaml in the example file's directory
    os.environ["USERPROFILE"] = test_config_dir

    # Also set UPDATECHECKER_CONFIG to explicitly point to the example file
    os.environ["UPDATECHECKER_CONFIG"] = str(_example_yaml_path)

    yield

    # Cleanup
    if "USERPROFILE" in os.environ:
        del os.environ["USERPROFILE"]
    if "UPDATECHECKER_CONFIG" in os.environ:
        del os.environ["UPDATECHECKER_CONFIG"]
