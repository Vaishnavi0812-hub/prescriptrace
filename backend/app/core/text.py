"""Text normalisation shared by ingestion (index time) and lookup (query time).

Both sides must use the same function, otherwise exact matches silently fail.
"""

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def norm(text: str) -> str:
    """Lowercase, strip accents, turn punctuation into single spaces.

    >>> norm("  Amoxicillin/Clavulanate  ")
    'amoxicillin clavulanate'
    >>> norm("Paracétamol-500")
    'paracetamol 500'
    """
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    return _NON_ALNUM.sub(" ", ascii_only).strip()
