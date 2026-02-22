import os
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, field_validator, model_validator

config_dirname = 'updatechecker'
config_filename = f'{config_dirname}.yaml'

# Pattern to match {{variable_name}}
VARIABLE_PATTERN = re.compile(r'\{\{(\w+)\}\}')

# Pattern to match %ENV_VAR%
ENV_PATTERN = re.compile(r'%(\w+)%')


class Entry(BaseModel):
    name: str
    url: str
    md5: str | None = None
    target: str
    git_asset: str | None = None
    unzip_target: str | None = None
    kill_if_locked: str | bool | None = False
    relaunch: bool | None = False
    launch: str | None = None
    arguments: str | None = None
    archive_password: str | None = None
    variables: dict | None = None
    flatten: bool | None = False
    chunked_download: bool | None = None  # None = auto, True = force, False = never
    use_content_length_check: bool | None = True

    @field_validator('unzip_target')
    def validate_unzip_target(cls, v: str):
        if v:
            v = Path(v)
            if not v.exists() or not v.is_dir():
                raise ValueError(f"unzip_target '{v}' must be an existing directory")
            v = str(v)
        return v

    @field_validator('url')
    def validate_url(cls, v: str):
        try:
            result = urlparse(v)
            if not all([result.scheme, result.netloc]):
                raise ValueError("Invalid URL")
        except Exception as e:
            raise ValueError(f"Invalid URL: {v}") from e

        return v


class Variables(BaseModel):
    """Dictionary of variable names to path strings."""

    model_config = {'extra': 'allow'}

    @model_validator(mode='before')
    @classmethod
    def validate_values(cls, v):
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("Variables must be a dictionary")
        # Validate all values are strings
        for key, value in v.items():
            if not isinstance(value, str):
                raise ValueError(f"Variable '{key}' must have a string value")
        return v


def expand_env_variables(text: str) -> str:
    """
    Expand %ENV_VAR% placeholders in text with values from environment variables.

    Args:
        text: String containing %ENV_VAR% placeholders

    Returns:
        String with all environment variables expanded

    Raises:
        ValueError: If an environment variable is referenced but not defined
    """
    if not text or not isinstance(text, str):
        return text

    def replace_env_var(match):
        var_name = match.group(1)
        if var_name not in os.environ:
            raise ValueError(
                f"Undefined environment variable: '{var_name}' referenced in path"
            )
        return os.environ[var_name]

    return ENV_PATTERN.sub(replace_env_var, text)


def substitute_variables(
    text: str, variables: dict, error_context: str = 'path'
) -> str:
    """
    Substitute {{variable_name}} placeholders in text with values from variables dict.
    Also expands %ENV_VAR% placeholders from environment variables.

    Args:
        text: String containing {{variable_name}} placeholders
        variables: Dictionary mapping variable names to their values
        error_context: Context string for error messages (e.g., entry name)

    Returns:
        String with all placeholders substituted

    Raises:
        ValueError: If a variable is referenced but not defined
    """
    if not text or not isinstance(text, str):
        return text

    # First expand environment variables
    text = expand_env_variables(text)

    if not VARIABLE_PATTERN.search(text):
        return text

    def replace_var(match):
        var_name = match.group(1)
        if var_name not in variables:
            raise ValueError(
                f"Undefined variable: '{var_name}' referenced in {error_context}"
            )
        return variables[var_name]

    return VARIABLE_PATTERN.sub(replace_var, text)


def entry_validator(entries, variables=None):
    """Validate entries and substitute variables in path fields."""
    if variables is None:
        variables = {}

    path_fields = ['target', 'unzip_target', 'kill_if_locked', 'launch', 'arguments']

    for entry_name, entry_data in entries.items():
        entry = entry_data.copy()
        entry_vars = entry.pop('variables', None) or {}

        # Expand environment variables in entry-specific variables
        expanded_entry_vars = {
            k: expand_env_variables(v) for k, v in entry_vars.items()
        }

        # Expand variable references in entry-specific variables iteratively
        max_iterations = 10
        for key in expanded_entry_vars:
            value = expanded_entry_vars[key]
            # Merge global vars with entry vars for resolution (entry vars take priority)
            merged_for_resolution = {**variables, **expanded_entry_vars}
            for _ in range(max_iterations):
                new_value = substitute_variables(
                    value, merged_for_resolution, f"entry '{entry_name}'"
                )
                if new_value == value:
                    break
                value = new_value
            expanded_entry_vars[key] = value

        # Merge variables (entry-specific take priority)
        merged = {**variables, **expanded_entry_vars}

        # Substitute variables in path fields
        for field in path_fields:
            if field in entry and entry[field]:
                entry[field] = substitute_variables(entry[field], merged)

        Entry(**entry, name=entry_name)

    return True


class Config:
    """Configuration class that loads and manages config from a YAML file.

    This class provides a cleaner API for loading and accessing configuration
    from a specific YAML file path. It reads YAML directly without relying
    on Dynaconf validators.
    """

    def __init__(self, config_path: str | Path):
        """Initialize Config with a specific config file path.

        Args:
            config_path: Path to the YAML config file.
        """
        self._config_path = Path(config_path)
        self._yaml_data = self._read_yaml_data()

    def _read_yaml_data(self) -> dict:
        """Read YAML data directly from config file.

        Returns the full YAML data dict, or empty dict if file not found.
        """
        if self._config_path.exists():
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    return data or {}
            except Exception:
                pass
        return {}

    @property
    def entries(self) -> dict:
        """Get entries from config."""
        return self._yaml_data.get('entries') or {}

    @property
    def variables(self) -> dict:
        """Get raw variables from config."""
        return self._yaml_data.get('variables') or {}

    @property
    def github_token(self) -> str | None:
        """Get github_token from config."""
        return self._yaml_data.get("github_token")

    def get_variables(self) -> dict:
        """Get variables with expansion of environment variables and chained variables.

        Returns:
            Dictionary of resolved variables.
        """
        variables = self._yaml_data.get('variables') or {}

        # Expand environment variables first
        expanded = {k: expand_env_variables(v) for k, v in variables.items()}

        # Resolve variable references iteratively (in order for forward references)
        resolved = {}
        max_iterations = 10  # Prevent infinite loops

        for key, value in expanded.items():
            for _ in range(max_iterations):
                new_value = substitute_variables(value, resolved, 'variables')
                if new_value == value:
                    break
                value = new_value
            resolved[key] = value

        return resolved

    def validate(self) -> None:
        """Validate the configuration.

        This validates entries and variables structure without requiring
        all paths to exist (which depends on the runtime environment).
        """
        entries = self.entries
        variables = self.get_variables()
        entry_validator(entries, variables)

    def __repr__(self) -> str:
        return f"Config(path='{self._config_path}')"


# Keep these for backward compatibility with tests that use them directly
# These functions read from the default config locations (current dir and home dir)


def _get_default_config_paths():
    """Get list of default config file paths to search."""
    home_dir = os.getenv('USERPROFILE', '~').replace('\\', '/')
    return [
        f"./{config_filename}",
        f"{home_dir}/{config_filename}",
    ]


def _read_yaml_data() -> dict:
    """Read YAML data from default config locations.

    Returns the full YAML data dict from the first config file found,
    or empty dict if no file found.
    """
    for config_file in _get_default_config_paths():
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    return data or {}
            except Exception:
                pass
    return {}


def _read_yaml_variables() -> dict:
    """Read variables from default config locations."""
    return _read_yaml_data().get('variables') or {}


def _read_yaml_entries() -> dict:
    """Read entries from default config locations."""
    return _read_yaml_data().get('entries') or {}


def _get_variables() -> dict:
    """Get variables from config, return empty dict if not set.

    Expands environment variables and chained config variables in variable values.
    Variables are processed in order, so later variables can reference earlier ones.
    """
    variables = _read_yaml_variables() or {}

    # Expand environment variables first
    expanded = {k: expand_env_variables(v) for k, v in variables.items()}

    # Resolve variable references iteratively (in order for forward references)
    resolved = {}
    max_iterations = 10  # Prevent infinite loops

    for key, value in expanded.items():
        for _ in range(max_iterations):
            new_value = substitute_variables(value, resolved, 'variables')
            if new_value == value:
                break
            value = new_value
        resolved[key] = value

    return resolved


def _validate_entries_with_variables(value=None):
    """Legacy function - for backward compatibility."""
    return entry_validator(_read_yaml_entries(), _get_variables())
