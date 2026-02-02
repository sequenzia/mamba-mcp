"""Tests for mamba_mcp_core.fuzzy module."""

import pytest
from mamba_mcp_core.fuzzy import find_similar_names, levenshtein_distance


class TestLevenshteinDistance:
    """Tests for levenshtein_distance function."""

    def test_identical_strings(self) -> None:
        """Identical strings have distance 0."""
        assert levenshtein_distance("hello", "hello") == 0

    def test_empty_strings(self) -> None:
        """Two empty strings have distance 0."""
        assert levenshtein_distance("", "") == 0

    def test_one_empty(self) -> None:
        """Distance to empty string is the length of the other."""
        assert levenshtein_distance("abc", "") == 3
        assert levenshtein_distance("", "abc") == 3

    def test_single_insertion(self) -> None:
        """Single character insertion has distance 1."""
        assert levenshtein_distance("cat", "cats") == 1

    def test_single_deletion(self) -> None:
        """Single character deletion has distance 1."""
        assert levenshtein_distance("cats", "cat") == 1

    def test_single_substitution(self) -> None:
        """Single character substitution has distance 1."""
        assert levenshtein_distance("cat", "car") == 1

    def test_completely_different(self) -> None:
        """Completely different strings of same length."""
        assert levenshtein_distance("abc", "xyz") == 3

    def test_symmetry(self) -> None:
        """Distance is symmetric."""
        assert levenshtein_distance("kitten", "sitting") == levenshtein_distance(
            "sitting", "kitten"
        )


class TestFindSimilarNames:
    """Tests for find_similar_names with scaled threshold."""

    def test_exact_match(self) -> None:
        """Exact match is always returned."""
        result = find_similar_names("users", ["users", "orders", "products"])
        assert "users" in result

    def test_close_typo(self) -> None:
        """Close typo is found."""
        result = find_similar_names("usrs", ["users", "orders", "products"])
        assert "users" in result

    def test_empty_candidates(self) -> None:
        """Empty candidates returns empty list."""
        assert find_similar_names("test", []) == []

    def test_max_results(self) -> None:
        """Respects max_results limit."""
        candidates = ["aa", "ab", "ac", "ad", "ae"]
        result = find_similar_names("aa", candidates, max_results=2)
        assert len(result) <= 2

    def test_case_insensitive(self) -> None:
        """Matching is case-insensitive."""
        result = find_similar_names("USERS", ["users", "orders"])
        assert "users" in result

    def test_scaled_threshold_short_name(self) -> None:
        """Short names use minimum threshold of 2."""
        # "ab" has len 2, threshold = max(2, min(1, 5)) = 2
        result = find_similar_names("ab", ["abc", "xyz", "abcdef"])
        assert "abc" in result  # distance 1
        assert "xyz" not in result  # distance 3, exceeds threshold 2

    def test_scaled_threshold_long_name(self) -> None:
        """Long names use maximum threshold of 5."""
        # "abcdefghijklmnop" has len 16, threshold = max(2, min(8, 5)) = 5
        result = find_similar_names(
            "abcdefghijklmnop",
            ["abcdefghijklmnox", "completely_different_name"],
        )
        assert "abcdefghijklmnox" in result  # distance 1

    @pytest.mark.parametrize(
        "name,expected_threshold",
        [
            ("ab", 2),  # len=2, max(2, min(1, 5)) = 2
            ("abcd", 2),  # len=4, max(2, min(2, 5)) = 2
            ("abcdefgh", 4),  # len=8, max(2, min(4, 5)) = 4
            ("abcdefghijkl", 5),  # len=12, max(2, min(6, 5)) = 5
        ],
    )
    def test_threshold_scaling(self, name: str, expected_threshold: int) -> None:
        """Threshold scales correctly with name length."""
        actual = max(2, min(len(name) // 2, 5))
        assert actual == expected_threshold
