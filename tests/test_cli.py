"""Tests for CLI module."""

from updatechecker.cli import parse_arg_entries


class TestParseEntries:
    """Tests for parse_entries function."""

    def test_parse_entries_none(self):
        """Test that None input returns None."""
        assert parse_arg_entries(None) is None

    def test_parse_entries_single(self):
        """Test parsing a single entry."""
        result = parse_arg_entries("entry1")
        assert result == ["entry1"]

    def test_parse_entries_multiple(self):
        """Test parsing multiple entries."""
        result = parse_arg_entries("entry1,entry2,entry3")
        assert result == ["entry1", "entry2", "entry3"]

    def test_parse_entries_with_spaces(self):
        """Test parsing entries with spaces."""
        result = parse_arg_entries("entry1, entry2 , entry3")
        assert result == ["entry1", "entry2", "entry3"]

    def test_parse_entries_empty_strings(self):
        """Test that empty strings are filtered out."""
        result = parse_arg_entries("entry1,,entry2, ,entry3")
        assert result == ["entry1", "entry2", "entry3"]
