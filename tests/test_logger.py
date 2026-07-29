"""Tests for download progress bookkeeping in logger."""

from unittest.mock import MagicMock

from updatechecker import logger as ulog


class TestProgressLifecycle:
    """The display is shared: it must stop only after the LAST download."""

    def test_display_stops_only_after_last_download(self, monkeypatch):
        mock_progress = MagicMock()
        mock_progress.live.is_started = True
        monkeypatch.setattr(ulog, '_progress', mock_progress)
        monkeypatch.setattr(ulog, '_active_downloads', 0)

        ulog.start_download_progress()
        ulog.start_download_progress()

        ulog.stop_download_progress()
        mock_progress.stop.assert_not_called()

        ulog.stop_download_progress()
        mock_progress.stop.assert_called_once()

    def test_stop_without_start_does_not_underflow(self, monkeypatch):
        mock_progress = MagicMock()
        mock_progress.live.is_started = True
        monkeypatch.setattr(ulog, '_progress', mock_progress)
        monkeypatch.setattr(ulog, '_active_downloads', 0)

        ulog.stop_download_progress()
        ulog.start_download_progress()
        ulog.stop_download_progress()

        # The unmatched stop must not leave the counter at -1
        assert mock_progress.stop.call_count == 2


class TestDownloadTasks:
    """Progress rows are keyed by a unique key, not the display name."""

    def _patch_state(self, monkeypatch, mock_progress):
        monkeypatch.setattr(ulog, 'get_progress', lambda: mock_progress)
        monkeypatch.setattr(ulog, '_download_tasks', {})
        monkeypatch.setattr(ulog, '_download_start_times', {})
        monkeypatch.setattr(ulog, '_download_speeds', {})

    def test_same_filename_different_keys_get_separate_rows(self, monkeypatch):
        mock_progress = MagicMock()
        mock_progress.live.is_started = True
        mock_progress.add_task.side_effect = [1, 2]
        self._patch_state(monkeypatch, mock_progress)

        ulog.update_download_progress(
            'C:/a/latest.zip', 10, 100, description='latest.zip'
        )
        ulog.update_download_progress(
            'C:/b/latest.zip', 10, 100, description='latest.zip'
        )

        assert mock_progress.add_task.call_count == 2

    def test_same_key_reuses_the_row(self, monkeypatch):
        mock_progress = MagicMock()
        mock_progress.live.is_started = True
        mock_progress.add_task.return_value = 1
        self._patch_state(monkeypatch, mock_progress)

        ulog.update_download_progress('C:/a/f.zip', 10, 100, description='f.zip')
        ulog.update_download_progress('C:/a/f.zip', 50, 100, description='f.zip')

        assert mock_progress.add_task.call_count == 1

    def test_remove_download_task_clears_state(self, monkeypatch):
        monkeypatch.setattr(ulog, '_download_tasks', {'k': 1})
        monkeypatch.setattr(ulog, '_download_start_times', {'k': 0.0})
        monkeypatch.setattr(ulog, '_download_speeds', {1: 5.0})

        ulog.remove_download_task('k')

        assert ulog._download_tasks == {}
        assert ulog._download_start_times == {}
        assert ulog._download_speeds == {}
