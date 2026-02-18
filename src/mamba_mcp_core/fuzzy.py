"""Fuzzy name matching using Levenshtein distance.

Provides a shared implementation with HANA's scaled threshold strategy:
threshold = max(2, min(len(name) // 2, 5))

This adapts to input length — short names (2-3 chars) need close matches,
while longer names allow more tolerance. The range [2, 5] prevents both
overly strict matching on short inputs and overly loose matching on long ones.
"""


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein edit distance between two strings.

    Uses the Wagner-Fischer dynamic programming algorithm with
    two-row optimization for O(min(m,n)) space complexity.

    Args:
        s1: First string.
        s2: Second string.

    Returns:
        Minimum number of single-character edits to transform s1 into s2.
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def find_similar_names(
    name: str,
    candidates: list[str],
    max_results: int = 3,
) -> list[str]:
    """Find similar names using Levenshtein distance with scaled threshold.

    Compares the input name against all candidates (case-insensitive)
    and returns the closest matches within an edit distance threshold.
    The threshold scales with the length of the input name:
    - Minimum threshold: 2 (for short names)
    - Maximum threshold: 5 (for long names)
    - Formula: max(2, min(len(name) // 2, 5))

    Args:
        name: The name to match against.
        candidates: List of candidate names to search.
        max_results: Maximum number of suggestions to return.

    Returns:
        List of similar names sorted by edit distance (closest first).
        Returns empty list if no candidates are within the threshold.
    """
    if not candidates:
        return []

    # Threshold scales with name length: min 2, max 5
    threshold = max(2, min(len(name) // 2, 5))

    scored = [
        (candidate, levenshtein_distance(name.lower(), candidate.lower()))
        for candidate in candidates
    ]
    scored.sort(key=lambda x: x[1])

    return [candidate for candidate, distance in scored[:max_results] if distance <= threshold]
