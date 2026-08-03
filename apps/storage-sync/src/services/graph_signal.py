import re
from typing import List


class GraphSignalClassifier:
    """
    Service for checking if node content contains high-signal corporate governance keywords
    (e.g., related party, subsidiaries, joint venture, auditor, guarantees) warranting Graph RAG extraction.
    """

    PATTERNS: List[str] = [
        r"related\s+party",
        r"subsidiary",
        r"holding\s+company",
        r"joint\s+venture",
        r"director",
        r"key\s+managerial",
        r"kmp",
        r"auditor",
        r"guarantee",
        r"facility\s+agreement",
        r"borrowing",
        r"acquisition",
        r"merger",
        r"amalgamation",
        r"jurisdiction",
        r"ownership",
        r"exhibit\s+21",
        r"consolidation",
    ]

    _COMPILED_PATTERNS = [re.compile(pat, re.IGNORECASE) for pat in PATTERNS]

    @classmethod
    def is_high_signal(cls, text: str, min_length: int = 0) -> bool:
        """Return True if text exceeds min_length and contains high-signal corporate governance terms."""
        if not text or len(text.strip()) < min_length:
            return False
        return any(compiled.search(text) is not None for compiled in cls._COMPILED_PATTERNS)
