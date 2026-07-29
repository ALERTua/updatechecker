"""Tests for per-entry error isolation in the main updatechecker flow."""

from unittest.mock import patch

import yaml

from updatechecker.updatechecker import updatechecker


def write_config(path, data):
    path.write_text(yaml.safe_dump(data), encoding='utf-8')


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
