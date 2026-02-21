from updatechecker.config import config_kwargs, Dynaconf, Path


def test_example_config():
    example_config_dirpath = Path(__file__).parent.parent
    example_config = example_config_dirpath / 'updatechecker.example.yaml'
    config = Dynaconf(
        root_path=example_config_dirpath,
        settings_files=[example_config],
        **config_kwargs,
    )
    config.validators.validate_all()
