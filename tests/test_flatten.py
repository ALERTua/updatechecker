"""Tests for the flatten functionality in zip extraction."""

import tempfile
import zipfile
from pathlib import Path


from updatechecker.common_tools import unzip_file


class TestFlattenConfig:
    """Tests for the flatten field in config Entry model."""

    def test_entry_accepts_flatten_field(self):
        """Test that Entry model accepts the flatten field."""
        from updatechecker.config import Entry

        # Create a temp directory for unzip_target
        with tempfile.TemporaryDirectory() as temp_dir:
            entry = Entry(
                name="test",
                url="https://example.com",
                target=f"{temp_dir}/file.zip",
                unzip_target=temp_dir,
                flatten=True,
            )
            assert entry.flatten is True

    def test_entry_flatten_defaults_to_false(self):
        """Test that flatten defaults to False."""
        from updatechecker.config import Entry

        with tempfile.TemporaryDirectory() as temp_dir:
            entry = Entry(
                name="test",
                url="https://example.com",
                target=f"{temp_dir}/file.zip",
                unzip_target=temp_dir,
            )
            assert entry.flatten is False


class TestUnzipFileFlatten:
    """Tests for the unzip_file function with flatten parameter."""

    def test_flatten_single_directory(self):
        """Test flattening a zip with a single top-level directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "test.zip"
            extract_to = Path(temp_dir) / "output"

            # Create a zip with a single top-level directory
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("version_1.0.0/file1.txt", "content1")
                zf.writestr("version_1.0.0/file2.txt", "content2")

            extract_to.mkdir()

            # Extract with flatten=True
            unzip_file(zip_path, extract_to, flatten=True)

            # Verify files are directly in the output directory
            assert (extract_to / "file1.txt").exists()
            assert (extract_to / "file2.txt").exists()
            # The versioned folder should NOT exist
            assert not (extract_to / "version_1.0.0").exists()

    def test_flatten_false_preserves_directory(self):
        """Test that flatten=False preserves the directory structure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "test.zip"
            extract_to = Path(temp_dir) / "output"

            # Create a zip with a single top-level directory
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("version_1.0.0/file1.txt", "content1")
                zf.writestr("version_1.0.0/file2.txt", "content2")

            extract_to.mkdir()

            # Extract with flatten=False (default)
            unzip_file(zip_path, extract_to, flatten=False)

            # Verify files are in the versioned folder
            assert (extract_to / "version_1.0.0" / "file1.txt").exists()
            assert (extract_to / "version_1.0.0" / "file2.txt").exists()

    def test_flatten_multiple_directories_no_change(self):
        """Test that flatten doesn't change when multiple top-level directories exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "test.zip"
            extract_to = Path(temp_dir) / "output"

            # Create a zip with multiple top-level directories
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("dir1/file1.txt", "content1")
                zf.writestr("dir2/file2.txt", "content2")

            extract_to.mkdir()

            # Extract with flatten=True
            unzip_file(zip_path, extract_to, flatten=True)

            # Verify both directories exist (flatten should not have changed anything)
            assert (extract_to / "dir1" / "file1.txt").exists()
            assert (extract_to / "dir2" / "file2.txt").exists()

    def test_flatten_files_at_root_no_change(self):
        """Test that flatten doesn't change when files are at root level."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "test.zip"
            extract_to = Path(temp_dir) / "output"

            # Create a zip with files at root level
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("file1.txt", "content1")
                zf.writestr("file2.txt", "content2")

            extract_to.mkdir()

            # Extract with flatten=True
            unzip_file(zip_path, extract_to, flatten=True)

            # Verify files are directly in the output directory
            assert (extract_to / "file1.txt").exists()
            assert (extract_to / "file2.txt").exists()

    def test_flatten_mixed_files_and_directory(self):
        """Test flatten with mix of files and single directory - should warn and not flatten."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "test.zip"
            extract_to = Path(temp_dir) / "output"

            # Create a zip with files and a single directory
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("rootfile.txt", "root content")
                zf.writestr("version_1.0.0/file1.txt", "content1")

            extract_to.mkdir()

            # With mixed content, should warn and use normal extraction
            unzip_file(zip_path, extract_to, flatten=True)

            # Files should be in their original locations (normal extraction)
            assert (extract_to / "rootfile.txt").exists()
            # The versioned folder should exist (normal extraction, not flattened)
            assert (extract_to / "version_1.0.0" / "file1.txt").exists()
