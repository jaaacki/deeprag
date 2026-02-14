"""Tests for the extractor module."""

import pytest
from src.extractor import extract_movie_code, detect_subtitle


class TestExtractMovieCode:
    """Tests for extract_movie_code()."""

    def test_standard_code(self):
        assert extract_movie_code('SONE-760 English subbed The same commute.mp4') == 'SONE-760'

    def test_three_letter_prefix(self):
        assert extract_movie_code('JUR-589 English subbed To make them.mp4') == 'JUR-589'

    def test_long_prefix(self):
        assert extract_movie_code('MIDV-12345 Some title.mkv') == 'MIDV-12345'

    def test_six_letter_prefix(self):
        assert extract_movie_code('ACHIJK-001 title.mp4') == 'ACHIJK-001'

    def test_lowercase_input(self):
        assert extract_movie_code('sone-760 something.mp4') == 'SONE-760'

    def test_mixed_case(self):
        assert extract_movie_code('Sone-760 something.mp4') == 'SONE-760'

    def test_code_in_middle(self):
        assert extract_movie_code('Download SONE-760 HD.mp4') == 'SONE-760'

    def test_no_code(self):
        assert extract_movie_code('random movie file.mp4') is None

    def test_single_letter_prefix_ignored(self):
        """Single letter prefix is too short (min 2)."""
        assert extract_movie_code('A-123 title.mp4') is None

    def test_no_dash(self):
        assert extract_movie_code('SONE760 title.mp4') is None

    def test_path_with_directories(self):
        assert extract_movie_code('/watch/SONE-760 title.mp4') == 'SONE-760'


class TestDetectSubtitle:
    """Tests for detect_subtitle()."""

    def test_english_subbed(self):
        assert detect_subtitle('SONE-760 English subbed The same commute.mp4') == 'English Sub'

    def test_english_subtitle(self):
        assert detect_subtitle('SONE-760 English subtitle title.mp4') == 'English Sub'

    def test_eng_keyword(self):
        assert detect_subtitle('SONE-760 eng something.mp4') == 'English Sub'

    def test_chinese_subbed(self):
        assert detect_subtitle('SONE-760 Chinese subbed title.mp4') == 'Chinese Sub'

    def test_chi_keyword(self):
        assert detect_subtitle('SONE-760 chi title.mp4') == 'Chinese Sub'

    def test_no_subtitle(self):
        assert detect_subtitle('SONE-760 Some random title.mp4') == 'No Sub'

    def test_case_insensitive(self):
        assert detect_subtitle('SONE-760 ENGLISH SUBBED title.mp4') == 'English Sub'

    def test_english_subbed_over_chinese(self):
        """English subbed should be matched first when both keywords present."""
        assert detect_subtitle('SONE-760 English subbed Chinese subbed.mp4') == 'English Sub'
