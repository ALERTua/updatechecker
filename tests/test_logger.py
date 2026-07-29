"""Tests for the DownloadProgressManager lifecycle and display consistency."""

from unittest.mock import MagicMock

from updatechecker.logger import DownloadProgressManager


def make_manager(started: bool = False):
    """Manager with a mocked rich Progress injected."""
    manager = DownloadProgressManager()
    progress = MagicMock()
    progress.live.is_started = started
    progress.add_task.side_effect = range(1000)
    manager._progress = progress
    return manager, progress


class TestLifecycle:
    """Rows have an explicit begin/update/finish lifecycle."""

    def test_begin_registers_row_and_starts_display(self):
        manager, progress = make_manager(started=False)

        manager.begin('C:/a/f.zip', 'f.zip')

        progress.add_task.assert_called_once_with('Downloading f.zip', total=None)
        progress.start.assert_called_once()

    def test_begin_same_key_resets_instead_of_duplicating(self):
        """Re-downloading the same destination must not add a second row."""
        manager, progress = make_manager(started=True)

        manager.begin('C:/a/f.zip', 'f.zip')
        manager.begin('C:/a/f.zip', 'f.zip', total=100)

        assert progress.add_task.call_count == 1
        progress.reset.assert_called_once()

    def test_finish_removes_row_and_stops_display_when_last(self):
        manager, progress = make_manager(started=True)
        manager.begin('a', 'a.zip')
        manager.begin('b', 'b.zip')

        manager.finish('a')
        progress.stop.assert_not_called()

        manager.finish('b')
        progress.stop.assert_called_once()
        assert progress.remove_task.call_count == 2

    def test_finish_prints_summary_on_success(self):
        manager, progress = make_manager(started=True)
        manager.begin('a', 'f.zip')
        task = MagicMock()
        task.id = 0
        task.completed = 1024
        task.elapsed = 2.0
        task.description = 'Downloading f.zip'
        progress.tasks = [task]

        manager.finish('a', success=True)

        printed = progress.console.print.call_args.args[0]
        assert 'f.zip' in printed
        assert '1.00 KB' in printed

    def test_finish_prints_no_summary_on_failure(self):
        manager, progress = make_manager(started=True)
        manager.begin('a', 'f.zip')
        task = MagicMock()
        task.id = 0
        task.completed = 512
        task.description = 'Downloading f.zip'
        progress.tasks = [task]

        manager.finish('a', success=False)

        progress.console.print.assert_not_called()


class TestUpdateSafety:
    """Updates must be monotonic and ignore unregistered keys."""

    def test_update_unknown_key_is_ignored(self):
        """A straggler callback after finish() must not resurrect the
        display or create a new row."""
        manager, progress = make_manager(started=True)
        manager.begin('a', 'f.zip')
        manager.finish('a')
        progress.reset_mock()

        manager.update('a', 50, 100)

        progress.update.assert_not_called()
        progress.add_task.assert_not_called()
        progress.start.assert_not_called()

    def test_update_is_monotonic(self):
        """Stale (smaller) sums from racing chunk callbacks are ignored."""
        manager, progress = make_manager(started=True)
        manager.begin('a', 'f.zip')

        manager.update('a', 50, 100)
        manager.update('a', 30, 100)

        assert progress.update.call_count == 1
        assert progress.update.call_args.kwargs['completed'] == 50

    def test_reset_allows_going_back(self):
        """Chunked-to-single fallback restarts the row explicitly."""
        manager, progress = make_manager(started=True)
        manager.begin('a', 'f.zip')

        manager.update('a', 90, 100)
        manager.reset('a', total=100)
        manager.update('a', 10, 100)

        progress.reset.assert_called_once()
        assert progress.update.call_args.kwargs['completed'] == 10

    def test_update_without_total_keeps_row_indeterminate(self):
        """Unknown-size downloads still advance the byte counter."""
        manager, progress = make_manager(started=True)
        manager.begin('a', 'f.zip')

        manager.update('a', 4096, None)

        kwargs = progress.update.call_args.kwargs
        assert kwargs['completed'] == 4096
        assert 'total' not in kwargs
