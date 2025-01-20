import os
from pathlib import Path

from typing import Optional, Union
from pydantic import BaseModel, field_validator
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


def entry_validator(entries):
    for entry_name in entries.keys():
        entry = entries[entry_name]
        Entry(**entry, name=entry_name)

    return True

fresh_vars = [
    "entries",
]

defaults = dict(
    entries=[],
)

validators = [
    Validator("entries", must_exist=True),
    Validator('entries', is_type_of=dict),
    Validator("entries", condition=entry_validator),
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
