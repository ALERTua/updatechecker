import os
import re
import yaml
from pathlib import Path

from typing import Optional, Union
from pydantic import BaseModel, field_validator, model_validator
from dynaconf import Dynaconf, Validator, ValidationError
from urllib.parse import urlparse

config_dirname = 'updatechecker'
config_filename = f'{config_dirname}.yaml'
default_config_dir = f"{os.getenv('USERPROFILE', '~')}".replace('\\', '/')
default_config_filepath = f"{default_config_dir}/{config_filename}"

if not os.path.exists(default_config_dir):
    os.makedirs(default_config_dir)


class Entry(BaseModel):
    name: str
    url: str
    md5: Optional[str] = None
    target: str
    git_asset: Optional[str] = None
    unzip_target: Optional[str] = None
    kill_if_locked: Optional[Union[str, bool]] = False
    relaunch: Optional[bool] = False
    launch: Optional[str] = None
    arguments: Optional[str] = None
    archive_password: Optional[str] = None
    variables: Optional[dict] = None

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


# Pattern to match {{variable_name}}
VARIABLE_PATTERN = re.compile(r'\{\{(\w+)\}\}')

# Pattern to match %ENV_VAR%
ENV_PATTERN = re.compile(r'%(\w+)%')


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
            raise ValueError(f"Undefined environment variable: '{var_name}' referenced in path")
        return os.environ[var_name]

    return ENV_PATTERN.sub(replace_env_var, text)


def substitute_variables(text: str, variables: dict) -> str:
    """
    Substitute {{variable_name}} placeholders in text with values from variables dict.
    Also expands %ENV_VAR% placeholders from environment variables.

    Args:
        text: String containing {{variable_name}} placeholders
        variables: Dictionary mapping variable names to their values

    Returns:
        String with all placeholders substituted

    Raises:
        ValueError: If a variable is referenced but not defined
    """
    if not text or not isinstance(text, str):
        return text

    # First expand environment variables
    text = expand_env_variables(text)

    def replace_var(match):
        var_name = match.group(1)
        if var_name not in variables:
            raise ValueError(f"Undefined variable: '{var_name}' referenced in path")
        return variables[var_name]

    return VARIABLE_PATTERN.sub(replace_var, text)


def entry_validator(entries, variables=None):
    """Validate entries and substitute variables in path fields."""
    if variables is None:
        variables = {}

    # Path fields that should have variable substitution
    path_fields = ['target', 'unzip_target', 'kill_if_locked', 'launch', 'arguments']

    for entry_name in entries.keys():
        entry = entries[entry_name].copy()

        # Get entry-specific variables if present
        entry_vars = entry.pop('variables', None) or {}
        
        # First expand environment variables in entry-specific variables
        expanded_entry_vars = {}
        for key, value in entry_vars.items():
            expanded_entry_vars[key] = expand_env_variables(value)
        
        # Then expand chained config variables in entry-specific variables
        # (can reference other entry-specific variables or main variables)
        max_iterations = 10
        for key in list(expanded_entry_vars.keys()):
            value = expanded_entry_vars[key]
            for _ in range(max_iterations):
                if not VARIABLE_PATTERN.search(value):
                    break
                
                def replace_var(match):
                    var_name = match.group(1)
                    # Check entry-specific vars first, then main variables
                    if var_name in expanded_entry_vars:
                        return expanded_entry_vars[var_name]
                    if var_name in variables:
                        return variables[var_name]
                    raise ValueError(f"Undefined variable: '{var_name}' referenced in entry '{entry_name}'")
                
                new_value = VARIABLE_PATTERN.sub(replace_var, value)
                if new_value == value:
                    break
                value = new_value
            expanded_entry_vars[key] = value

        # Merge main variables with entry-specific variables (entry vars take priority)
        merged_variables = {**variables, **expanded_entry_vars}

        # Substitute variables in path fields
        for field in path_fields:
            if field in entry and entry[field]:
                entry[field] = substitute_variables(entry[field], merged_variables)

        Entry(**entry, name=entry_name)

    return True

fresh_vars = [
    "entries",
    "variables",
]

defaults = dict(
    entries=[],
    variables={},
)


def _read_yaml_variables() -> dict:
    """Read variables directly from YAML file to avoid triggering Dynaconf setup.
    This prevents infinite recursion during validation."""
    # Try local file first, then default config directory
    config_files = [
        f"./{config_filename}",
        default_config_filepath,
    ]
    
    for config_file in config_files:
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    if data and 'variables' in data:
                        return data['variables'] or {}
            except Exception:
                pass
    return {}


def _read_yaml_entries() -> dict:
    """Read entries directly from YAML file to avoid triggering Dynaconf setup.
    This prevents infinite recursion during validation."""
    # Try local file first, then default config directory
    config_files = [
        f"./{config_filename}",
        default_config_filepath,
    ]
    
    for config_file in config_files:
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    if data and 'entries' in data:
                        return data['entries'] or {}
            except Exception:
                pass
    return {}


def _get_variables() -> dict:
    """Get variables from config, return empty dict if not set.
    Expands environment variables and chained config variables in variable values.
    Variables are processed in order, so later variables can reference earlier ones."""
    # Read raw YAML to avoid triggering Dynaconf validation
    variables = _read_yaml_variables() or {}
    
    # First expand environment variables in all values
    expanded_variables = {}
    for key, value in variables.items():
        expanded_variables[key] = expand_env_variables(value)
    
    # Then iteratively expand config variable references until no more substitutions
    # Process in order so variables can reference previously defined ones
    final_variables = {}
    max_iterations = 10  # Prevent infinite loops
    for key in list(expanded_variables.keys()):
        value = expanded_variables[key]
        for _ in range(max_iterations):
            # Check if there are any variable references left
            if not VARIABLE_PATTERN.search(value):
                break
            # Try to substitute
            def replace_var(match):
                var_name = match.group(1)
                if var_name not in final_variables:
                    raise ValueError(f"Undefined variable: '{var_name}' referenced in '{key}'")
                return final_variables[var_name]
            new_value = VARIABLE_PATTERN.sub(replace_var, value)
            if new_value == value:
                break  # No more changes
            value = new_value
        final_variables[key] = value
    
    return final_variables


def _validate_entries_with_variables(value=None):
    """Validate entries with variable substitution."""
    # Read entries from YAML directly to avoid triggering Dynaconf setup
    return entry_validator(_read_yaml_entries(), _get_variables())


validators = [
    Validator("entries", must_exist=True),
    Validator('entries', is_type_of=dict),
    Validator("entries", condition=_validate_entries_with_variables),
    Validator("variables", is_type_of=dict, default={}),
]
config_kwargs = dict(
    # env='updatechecker',
    load_dotenv=False,
    apply_default_on_none=True,
    auto_cast=True,
    lowercase_read=True,
    # root_path=default_config_dir,
    yaml_loader='safe_load',
    core_loaders=['YAML'],
    defaults=defaults,
    dotted_lookup=False,
    fresh_vars=fresh_vars,
    # settings_files=[
    #     default_config_filepath,
    #     f"./{config_filename}",
    # ],
    validators=validators,
)
config = Dynaconf(
    env='updatechecker',
    root_path=default_config_dir,
    settings_files=[
        default_config_filepath,
        f"./{config_filename}",
    ],
    **config_kwargs,
)


if __name__ == '__main__':
    try:
        config.validators.validate_all()
    except ValidationError as e:
        accumulative_errors = e.details
        print(accumulative_errors)
    pass
