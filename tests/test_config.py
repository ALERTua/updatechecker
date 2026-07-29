"""Tests for the config module."""


def test_config_creation(test_config):
    """Test that Config can be instantiated."""
    assert test_config is not None
    # Config should be created without immediate validation
    assert hasattr(test_config, '_config_path')


def test_config_entries_accessible(test_config):
    """Test that entries can be accessed from config."""
    # This should work without triggering validation errors
    entries = test_config.entries
    assert isinstance(entries, dict)


def test_config_variables_accessible(test_config):
    """Test that variables can be accessed from config."""
    variables = test_config.get_variables()
    assert isinstance(variables, dict)


class TestConfigNoRecursion:
    """Tests to ensure config loading doesn't cause infinite recursion."""

    def test_config_loads_without_infinite_recursion(self, test_config):
        """Test that config can be loaded without causing infinite recursion.

        This was the main bug: accessing config.entries or config.variables
        during validation triggered Dynaconf setup, which ran validators again,
        causing infinite recursion.
        """
        # This should not cause RecursionError
        assert test_config is not None
        # Basic sanity check - config should have entries property
        assert hasattr(test_config, 'entries')

    def test_get_variables_resolves_chained(self, test_config):
        """Test that get_variables resolves chained variable references."""
        variables = test_config.get_variables()
        # If games_dir is D:\Games and gw2_dir is {{games_dir}}\GW2
        # Then gw2_dir should be resolved to D:\Games\GW2
        if 'gw2_dir' in variables and 'games_dir' in variables:
            # The variable should have been resolved, not contain {{...}}
            assert '{{' not in variables['gw2_dir']


class TestKillIfLockedValidation:
    """kill_if_locked must be an executable path, not a bare boolean."""

    def _entry(self, **kwargs):
        from updatechecker.config import Entry

        return Entry(
            name='test',
            url='https://example.com/file.zip',
            target='./file.zip',
            **kwargs,
        )

    def test_true_is_rejected(self):
        import pytest

        with pytest.raises(ValueError, match='kill_if_locked'):
            self._entry(kill_if_locked=True)

    def test_false_is_normalized_to_none(self):
        assert self._entry(kill_if_locked=False).kill_if_locked is None

    def test_path_is_kept(self):
        entry = self._entry(kill_if_locked='C:/apps/tool.exe')
        assert entry.kill_if_locked == 'C:/apps/tool.exe'
