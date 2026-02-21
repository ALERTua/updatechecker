"""Tests for the config module."""
from updatechecker.config import _validate_entries_with_variables


def test_example_config(test_config):
    """Test that the example config loads correctly."""
    test_config.validators.validate_all()


class TestConfigNoRecursion:
    """Tests to ensure config loading doesn't cause infinite recursion."""

    def test_config_loads_without_infinite_recursion(self, test_config):
        """Test that config can be loaded without causing infinite recursion.

        This was the main bug: accessing config.entries or config.variables
        during validation triggered Dynaconf setup, which ran validators again,
        causing infinite recursion.
        """
        # This should not cause RecursionError
        # The fix is that we now read YAML directly instead of through config
        assert test_config is not None
        # Basic sanity check - config should have entries
        assert hasattr(test_config, 'entries')

    def test_validate_entries_does_not_trigger_setup(self, test_config):
        """Test that _validate_entries_with_variables doesn't trigger infinite setup."""
        # This should return True without RecursionError
        # The function now reads YAML directly
        result = _validate_entries_with_variables()
        assert result is True