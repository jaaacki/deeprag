"""Tests for the renamer module."""

import os
import tempfile

import pytest
from src.renamer import sanitize_filename, build_filename, find_matching_folder, move_file


class TestSanitizeFilename:
    """Tests for sanitize_filename()."""

    def test_clean_filename(self):
        assert sanitize_filename('Ruri Saijo - [English Sub] SONE-760 Title.mp4') == \
            'Ruri Saijo - [English Sub] SONE-760 Title.mp4'

    def test_removes_invalid_chars(self):
        assert sanitize_filename('Title: with <bad> chars?.mp4') == 'Title with bad chars.mp4'

    def test_collapses_spaces(self):
        assert sanitize_filename('Too   many   spaces.mp4') == 'Too many spaces.mp4'

    def test_removes_null_bytes(self):
        assert sanitize_filename('file\x00name.mp4') == 'filename.mp4'

    def test_collapses_dots(self):
        assert sanitize_filename('file...name.mp4') == 'file.name.mp4'


class TestBuildFilename:
    """Tests for build_filename()."""

    def test_standard_build(self):
        result = build_filename('Ruri Saijo', 'English Sub', 'SONE-760', 'The Same Commute Train', '.mp4')
        assert result == 'Ruri Saijo - [English Sub] SONE-760 The Same Commute Train.mp4'

    def test_no_sub(self):
        result = build_filename('Ruri Saijo', 'No Sub', 'SONE-760', 'Title', '.mp4')
        assert result == 'Ruri Saijo - [No Sub] SONE-760 Title.mp4'

    def test_extension_without_dot(self):
        result = build_filename('Actress', 'No Sub', 'ABC-123', 'Title', 'mkv')
        assert result == 'Actress - [No Sub] ABC-123 Title.mkv'

    def test_long_title_truncated(self):
        long_title = 'A' * 300
        result = build_filename('Actress', 'English Sub', 'ABC-123', long_title, '.mp4')
        assert len(result) <= 200

    def test_invalid_chars_in_title(self):
        result = build_filename('Actress', 'No Sub', 'ABC-123', 'Title: Bad?', '.mp4')
        assert ':' not in result
        assert '?' not in result


class TestFindMatchingFolder:
    """Tests for find_matching_folder()."""

    def test_exact_match(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'Ruri Saijo'))
            assert find_matching_folder(d, 'Ruri Saijo') == 'Ruri Saijo'

    def test_case_insensitive_match(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'Ruri Saijo'))
            assert find_matching_folder(d, 'ruri saijo') == 'Ruri Saijo'

    def test_no_match_returns_input(self):
        with tempfile.TemporaryDirectory() as d:
            assert find_matching_folder(d, 'New Actress') == 'New Actress'

    def test_nonexistent_dir(self):
        assert find_matching_folder('/nonexistent/path', 'Actress') == 'Actress'


class TestMoveFile:
    """Tests for move_file()."""

    def test_basic_move(self):
        with tempfile.TemporaryDirectory() as src_dir, \
             tempfile.TemporaryDirectory() as dest_dir:
            # Create source file
            src_file = os.path.join(src_dir, 'original.mp4')
            with open(src_file, 'w') as f:
                f.write('test content')

            result = move_file(src_file, dest_dir, 'Actress Name', 'new_name.mp4')

            assert os.path.exists(result)
            assert not os.path.exists(src_file)
            assert 'Actress Name' in result
            assert result.endswith('new_name.mp4')

    def test_creates_actress_folder(self):
        with tempfile.TemporaryDirectory() as src_dir, \
             tempfile.TemporaryDirectory() as dest_dir:
            src_file = os.path.join(src_dir, 'original.mp4')
            with open(src_file, 'w') as f:
                f.write('test')

            move_file(src_file, dest_dir, 'New Actress', 'file.mp4')

            assert os.path.isdir(os.path.join(dest_dir, 'New Actress'))

    def test_collision_handling(self):
        with tempfile.TemporaryDirectory() as src_dir, \
             tempfile.TemporaryDirectory() as dest_dir:
            # Create actress folder and existing file
            actress_dir = os.path.join(dest_dir, 'Actress')
            os.makedirs(actress_dir)
            existing = os.path.join(actress_dir, 'file.mp4')
            with open(existing, 'w') as f:
                f.write('existing')

            # Create new file
            src_file = os.path.join(src_dir, 'original.mp4')
            with open(src_file, 'w') as f:
                f.write('new')

            result = move_file(src_file, dest_dir, 'Actress', 'file.mp4')

            assert os.path.exists(result)
            assert 'file (1).mp4' in result
