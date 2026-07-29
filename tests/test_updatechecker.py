"""Tests for per-entry error isolation in the main updatechecker flow."""

from unittest.mock import patch

import yaml

from updatechecker.updatechecker import prepare_entry, updatechecker


def write_config(path, data):
    path.write_text(yaml.safe_dump(data), encoding='utf-8')


class TestBrokenConfig:
    """A broken config must fail the run loudly, not silently do nothing."""

    def test_invalid_yaml_fails_the_run(self, tmp_path):
        config_path = tmp_path / 'updatechecker.yaml'
        config_path.write_text('entries: [unclosed', encoding='utf-8')

        with patch('updatechecker.updatechecker.process_entry') as mock_process:
            failed = updatechecker(config_path=config_path, _async=False)

        assert failed == 1
        mock_process.assert_not_called()

    def test_missing_config_returns_zero(self, tmp_path):
        failed = updatechecker(
            config_path=tmp_path / 'does-not-exist.yaml', _async=False
        )
        assert not failed


class TestPrepareEntryVariables:
    """Runtime variable resolution must match config validation."""

    def test_entry_variable_can_reference_entry_variable(self, tmp_path):
        entry = prepare_entry(
            {
                'url': 'https://example.com/f.zip',
                'target': '{{full_dir}}/f.zip',
                'variables': {
                    'base': str(tmp_path),
                    'full_dir': '{{base}}/sub',
                },
            },
            'e1',
            {},
        )
        assert entry.target == f'{tmp_path}/sub/f.zip'

    def test_entry_variable_overrides_global(self, tmp_path):
        entry = prepare_entry(
            {
                'url': 'https://example.com/f.zip',
                'target': '{{dir}}/f.zip',
                'variables': {'dir': str(tmp_path / 'entry')},
            },
            'e1',
            {'dir': str(tmp_path / 'global')},
        )
        assert entry.target == f'{tmp_path / "entry"}/f.zip'

    def test_unzip_target_may_not_exist_yet(self, tmp_path):
        """First run on a fresh machine: unzip_target doesn't exist yet."""
        entry = prepare_entry(
            {
                'url': 'https://example.com/f.zip',
                'target': str(tmp_path / 'f.zip'),
                'unzip_target': str(tmp_path / 'not-created-yet'),
            },
            'e1',
            {},
        )
        assert entry.unzip_target == str(tmp_path / 'not-created-yet')


class TestEntryErrorIsolation:
    """One failing entry must not prevent the remaining entries from running."""

    def test_invalid_entry_does_not_abort_others(self, tmp_path):
        """An entry failing preparation is skipped; the rest are processed."""
        config_path = tmp_path / 'updatechecker.yaml'
        write_config(
            config_path,
            {
                'entries': {
                    'bad': {
                        'url': 'https://example.com/file.zip',
                        'target': '{{undefined_variable}}/file.zip',
                    },
                    'good': {
                        'url': 'https://example.com/file.zip',
                        'target': str(tmp_path / 'file.zip'),
                    },
                }
            },
        )

        with patch('updatechecker.updatechecker.process_entry') as mock_process:
            failed = updatechecker(config_path=config_path, _async=False)

        assert failed == 1
        processed = [call.args[0].name for call in mock_process.call_args_list]
        assert processed == ['good']

    def test_process_entry_exception_does_not_abort_others(self, tmp_path):
        """An exception inside process_entry is contained to that entry."""
        config_path = tmp_path / 'updatechecker.yaml'
        write_config(
            config_path,
            {
                'entries': {
                    'first': {
                        'url': 'https://example.com/a.zip',
                        'target': str(tmp_path / 'a.zip'),
                    },
                    'second': {
                        'url': 'https://example.com/b.zip',
                        'target': str(tmp_path / 'b.zip'),
                    },
                }
            },
        )

        def boom(entry, force, token):
            if entry.name == 'first':
                raise RuntimeError('boom')

        with patch(
            'updatechecker.updatechecker.process_entry', side_effect=boom
        ) as mock_process:
            failed = updatechecker(config_path=config_path, _async=False)

        assert failed == 1
        assert mock_process.call_count == 2

    def test_all_entries_ok_returns_zero(self, tmp_path):
        """Successful run reports zero failed entries."""
        config_path = tmp_path / 'updatechecker.yaml'
        write_config(
            config_path,
            {
                'entries': {
                    'only': {
                        'url': 'https://example.com/a.zip',
                        'target': str(tmp_path / 'a.zip'),
                    },
                }
            },
        )

        with patch('updatechecker.updatechecker.process_entry'):
            failed = updatechecker(config_path=config_path, _async=False)

        assert failed == 0

    def test_isolation_in_async_mode(self, tmp_path):
        """Isolation also holds with the thread pool enabled."""
        config_path = tmp_path / 'updatechecker.yaml'
        write_config(
            config_path,
            {
                'entries': {
                    'first': {
                        'url': 'https://example.com/a.zip',
                        'target': str(tmp_path / 'a.zip'),
                    },
                    'second': {
                        'url': 'https://example.com/b.zip',
                        'target': str(tmp_path / 'b.zip'),
                    },
                }
            },
        )

        def boom(entry, force, token):
            if entry.name == 'first':
                raise RuntimeError('boom')

        with patch(
            'updatechecker.updatechecker.process_entry', side_effect=boom
        ) as mock_process:
            failed = updatechecker(config_path=config_path, _async=True, threads=2)

        assert failed == 1
        assert mock_process.call_count == 2
