"""Tests for the variables feature in config."""

import os
import pytest
from updatechecker.config import (
    substitute_variables,
    expand_env_variables,
    Variables,
    entry_validator,
    _read_yaml_variables,
    _read_yaml_entries,
    _get_variables,
)


class TestExpandEnvVariables:
    """Tests for the expand_env_variables function."""

    def test_single_env_variable_expansion(self, monkeypatch):
        """Test basic environment variable expansion."""
        monkeypatch.setenv('TEST_GAMES_DIR', 'D:\\Games')
        result = expand_env_variables('%TEST_GAMES_DIR%\\file.zip')
        assert result == 'D:\\Games\\file.zip'

    def test_multiple_env_variables(self, monkeypatch):
        """Test multiple environment variables in one string."""
        monkeypatch.setenv('BASE_DIR', 'D:\\Games')
        monkeypatch.setenv('SUB_DIR', 'GW2')
        result = expand_env_variables('%BASE_DIR%\\%SUB_DIR%\\file.zip')
        assert result == 'D:\\Games\\GW2\\file.zip'

    def test_undefined_env_variable_raises_error(self, monkeypatch):
        """Test that undefined environment variable raises ValueError."""
        # Make sure the variable is not set
        monkeypatch.delenv('UNDEFINED_VAR', raising=False)
        with pytest.raises(ValueError, match="Undefined environment variable"):
            expand_env_variables('%UNDEFINED_VAR%\\file.zip')

    def test_empty_string(self):
        """Test empty string handling."""
        result = expand_env_variables('')
        assert result == ''

    def test_none_value(self):
        """Test None value handling."""
        result = expand_env_variables(None)
        assert result is None

    def test_no_env_variables_in_string(self):
        """Test string without env variables passes through."""
        result = expand_env_variables('C:\\static\\path')
        assert result == 'C:\\static\\path'

    def test_env_var_with_path_separators(self, monkeypatch):
        """Test environment variable with path separators."""
        monkeypatch.setenv('USERPROFILE', 'C:\\Users\\TestUser')
        result = expand_env_variables('%USERPROFILE%\\Downloads')
        assert result == 'C:\\Users\\TestUser\\Downloads'


class TestSubstituteVariables:
    """Tests for the substitute_variables function."""

    def test_single_variable_substitution(self):
        """Test basic variable substitution."""
        variables = {'games_dir': 'D:\\Games', 'gw2_dir': 'D:\\Games\\GW2'}
        result = substitute_variables('{{games_dir}}\\file.zip', variables)
        assert result == 'D:\\Games\\file.zip'

    def test_multiple_variable_substitution(self):
        """Test multiple variables in one string."""
        variables = {'games_dir': 'D:\\Games', 'gw2_dir': 'D:\\Games\\GW2'}
        result = substitute_variables('{{gw2_dir}}\\Gw2-64.exe', variables)
        assert result == 'D:\\Games\\GW2\\Gw2-64.exe'

    def test_undefined_variable_raises_error(self):
        """Test that undefined variable raises ValueError."""
        variables = {'games_dir': 'D:\\Games'}
        with pytest.raises(ValueError, match="Undefined variable"):
            substitute_variables('{{undefined_var}}\\file.zip', variables)

    def test_empty_string(self):
        """Test empty string handling."""
        variables = {'games_dir': 'D:\\Games'}
        result = substitute_variables('', variables)
        assert result == ''

    def test_none_value(self):
        """Test None value handling."""
        variables = {'games_dir': 'D:\\Games'}
        result = substitute_variables(None, variables)
        assert result is None

    def test_no_variables_in_string(self):
        """Test string without variables passes through."""
        variables = {'games_dir': 'D:\\Games'}
        result = substitute_variables('C:\\static\\path', variables)
        assert result == 'C:\\static\\path'

    def test_multiple_variables_same_string(self):
        """Test multiple different variables in same string."""
        variables = {'base': 'D:\\Games', 'sub': 'GW2', 'folder': 'bin64'}
        result = substitute_variables('{{base}}\\{{sub}}\\{{folder}}', variables)
        assert result == 'D:\\Games\\GW2\\bin64'

    def test_env_variable_with_config_variable(self, monkeypatch):
        """Test combined %ENV_VAR% and {{config variable}} syntax."""
        monkeypatch.setenv('USERPROFILE', 'C:\\Users\\TestUser')
        variables = {'games_dir': 'D:\\Games'}
        result = substitute_variables(
            '%USERPROFILE%\\{{games_dir}}\\file.zip', variables
        )
        assert result == 'C:\\Users\\TestUser\\D:\\Games\\file.zip'

    def test_env_variable_first_then_config_variable(self, monkeypatch):
        """Test that env variables are expanded before config variables."""
        monkeypatch.setenv('MY_BASE', 'C:\\Base')
        variables = {'subfolder': 'Downloads'}
        # Env var should be expanded first, then config variable
        result = substitute_variables('%MY_BASE%\\{{subfolder}}\\file.zip', variables)
        assert result == 'C:\\Base\\Downloads\\file.zip'


class TestVariablesModel:
    """Tests for the Variables model."""

    def test_valid_variables_dict(self):
        """Test creating valid Variables model."""
        vars_model = Variables(games_dir='D:\\Games', tools_dir='D:\\Tools')
        assert len(vars_model.model_dump()) == 2

    def test_none_value_returns_empty_dict(self):
        """Test None input returns empty dict."""
        vars_model = Variables.model_validate(None)
        assert vars_model.model_dump() == {}

    def test_non_string_value_raises_error(self):
        """Test that non-string values raise error."""
        with pytest.raises(ValueError, match="must have a string value"):
            Variables(games_dir=123)

    def test_non_dict_raises_error(self):
        """Test that non-dict input raises error."""
        with pytest.raises(ValueError, match="must be a dictionary"):
            Variables.model_validate("not a dict")


class TestEntryVariables:
    """Tests for per-entry variables feature."""

    def test_entry_specific_variables_override_main(self):
        """Test that entry-specific variables override main variables."""
        main_vars = {'games_dir': 'D:\\Games'}
        entries = {
            'entry1': {
                'url': 'https://example.com',
                'target': '{{games_dir}}\\file.zip',
                'variables': {'games_dir': 'E:\\Games'},
            }
        }
        result = entry_validator(entries, main_vars)
        assert result is True
        # The entry should use its own variable value
        merged = {**main_vars, **entries['entry1'].get('variables', {})}
        assert merged['games_dir'] == 'E:\\Games'

    def test_entry_specific_env_vars_in_variables(self, monkeypatch):
        """Test that entry-specific variables can contain env vars."""
        monkeypatch.setenv('TEST_DIR', 'F:\\Test')
        main_vars = {'games_dir': 'D:\\Games'}
        entries = {
            'entry1': {
                'url': 'https://example.com',
                'target': '{{custom_dir}}\\file.zip',
                'variables': {'custom_dir': '%TEST_DIR%'},
            }
        }
        result = entry_validator(entries, main_vars)
        assert result is True

    def test_entry_without_specific_variables_uses_main(self):
        """Test that entries without specific variables use main variables."""
        main_vars = {'games_dir': 'D:\\Games'}
        entries = {
            'entry1': {
                'url': 'https://example.com',
                'target': '{{games_dir}}\\file.zip',
            }
        }
        result = entry_validator(entries, main_vars)
        assert result is True

    def test_chained_variables_in_entry_vars(self):
        """Test that entry-specific variables can reference other entry variables."""
        main_vars = {'base': 'D:\\Base'}
        entries = {
            'entry1': {
                'url': 'https://example.com',
                'target': '{{subdir}}\\file.zip',
                'variables': {'subdir': '{{base}}\\Sub', 'deep': '{{subdir}}\\Deep'},
            }
        }
        result = entry_validator(entries, main_vars)
        assert result is True


class TestReadYamlVariables:
    """Tests for reading variables directly from YAML file."""

    def test_read_yaml_variables_from_file(self, tmp_path):
        """Test reading variables from a temporary YAML file."""
        yaml_content = """
variables:
  games_dir: D:\\Games
  tools_dir: D:\\Tools
  portable: '{{c_alert}}/Portable'

entries:
  test_entry:
    url: https://example.com
    target: '{{games_dir}}\\file.zip'
"""
        # The function looks for updatechecker.yaml
        yaml_file = tmp_path / "updatechecker.yaml"
        yaml_file.write_text(yaml_content)

        # Change to temp directory so it reads from there
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            variables = _read_yaml_variables()
            assert variables == {
                'games_dir': 'D:\\Games',
                'tools_dir': 'D:\\Tools',
                'portable': '{{c_alert}}/Portable',
            }
        finally:
            os.chdir(old_cwd)

    def test_read_yaml_variables_no_file(self, tmp_path):
        """Test reading variables when no YAML file exists."""
        old_cwd = os.getcwd()
        try:
            # Use a directory with no config file
            os.chdir(tmp_path)
            variables = _read_yaml_variables()
            assert variables == {}
        finally:
            os.chdir(old_cwd)

    def test_read_yaml_variables_no_variables_section(self, tmp_path):
        """Test reading variables when YAML has no variables section."""
        yaml_content = """
entries:
  test_entry:
    url: https://example.com
    target: C:\\Downloads
"""
        yaml_file = tmp_path / "updatechecker.yaml"
        yaml_file.write_text(yaml_content)

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            variables = _read_yaml_variables()
            assert variables == {}
        finally:
            os.chdir(old_cwd)


class TestReadYamlEntries:
    """Tests for reading entries directly from YAML file."""

    def test_read_yaml_entries_from_file(self, tmp_path):
        """Test reading entries from a temporary YAML file."""
        yaml_content = """
variables:
  games_dir: D:\\Games

entries:
  test_entry:
    url: https://example.com
    target: '{{games_dir}}\\file.zip'

  another_entry:
    url: https://another.com
    target: C:\\Downloads
"""
        # The function looks for updatechecker.yaml
        yaml_file = tmp_path / "updatechecker.yaml"
        yaml_file.write_text(yaml_content)

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            entries = _read_yaml_entries()
            assert 'test_entry' in entries
            assert entries['test_entry']['url'] == 'https://example.com'
            assert 'another_entry' in entries
        finally:
            os.chdir(old_cwd)

    def test_read_yaml_entries_no_file(self, tmp_path):
        """Test reading entries when no YAML file exists."""
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            entries = _read_yaml_entries()
            assert entries == {}
        finally:
            os.chdir(old_cwd)


class TestGetVariables:
    """Tests for _get_variables function that reads and expands variables."""

    def test_get_variables_chained_references(self, tmp_path):
        """Test that _get_variables handles chained variable references."""
        yaml_content = """
variables:
  games_dir: D:\\Games
  gw2_dir: '{{games_dir}}\\GW2'
  tools_dir: '{{gw2_dir}}\\_tools'

entries: {}
"""
        yaml_file = tmp_path / "updatechecker.yaml"
        yaml_file.write_text(yaml_content)

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            variables = _get_variables()
            assert variables['games_dir'] == 'D:\\Games'
            assert variables['gw2_dir'] == 'D:\\Games\\GW2'
            assert variables['tools_dir'] == 'D:\\Games\\GW2\\_tools'
        finally:
            os.chdir(old_cwd)

    def test_get_variables_undefined_reference_raises_error(self, tmp_path):
        """Test that undefined variable reference raises ValueError."""
        yaml_content = """
variables:
  games_dir: '{{undefined_var}}\\Games'

entries: {}
"""
        yaml_file = tmp_path / "updatechecker.yaml"
        yaml_file.write_text(yaml_content)

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with pytest.raises(ValueError, match="Undefined variable: 'undefined_var'"):
                _get_variables()
        finally:
            os.chdir(old_cwd)

    def test_get_variables_infinite_loop_prevention(self, tmp_path):
        """Test that infinite loops in variable references are prevented."""
        # This creates a circular reference: a -> b -> c -> a
        # Should not loop forever, should hit max iterations
        yaml_content = """
variables:
  var_a: '{{var_b}}'
  var_b: '{{var_c}}'
  var_c: '{{var_a}}'

entries: {}
"""
        yaml_file = tmp_path / "updatechecker.yaml"
        yaml_file.write_text(yaml_content)

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            # This should raise an error because of the circular reference
            # (it will fail to resolve after max iterations)
            with pytest.raises(ValueError, match="Undefined variable"):
                _get_variables()
        finally:
            os.chdir(old_cwd)


class TestEntryVariablesWithGlobalReferences:
    """Tests for entry-specific variables referencing global variables."""

    def test_entry_var_references_global_var(self, tmp_path):
        """Test that entry variables can reference global config variables."""
        yaml_content = """
variables:
  base_dir: D:\\Base
  global_var: '{{base_dir}}\\Global'

entries:
  test_entry:
    url: https://example.com
    target: '{{custom}}\\file.zip'
    variables:
      custom: '{{base_dir}}\\Custom'

entries: {}
"""
        yaml_file = tmp_path / "updatechecker.yaml"
        yaml_file.write_text(yaml_content)

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            variables = _get_variables()
            # Global variable should be expanded
            assert variables['global_var'] == 'D:\\Base\\Global'
        finally:
            os.chdir(old_cwd)
