"""Pytest configuration for updatechecker tests.

This conftest provides fixtures that configure the application to use
updatechecker.example.yaml for tests that need it.
This ensures tests work in CI environments where home directory access
may be limited or different.
"""

from pathlib import Path

import pytest

# Get the path to updatechecker.example.yaml
_example_yaml_path = Path(__file__).parent.parent / "updatechecker.example.yaml"


@pytest.fixture
def example_config_path():
    """Provide the path to updatechecker.example.yaml for tests."""
    if not _example_yaml_path.exists():
        pytest.skip(f"Example config file not found: {_example_yaml_path}")
    return _example_yaml_path


@pytest.fixture
def test_config(example_config_path):
    """Provide a Config instance loaded from updatechecker.example.yaml.

    This fixture instantiates a new Config object using the example yaml file,
    ensuring tests have a consistent and isolated config for testing.
    """
    from updatechecker.config import Config

    return Config(example_config_path)
