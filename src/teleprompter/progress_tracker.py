"""Utilities to align spoken candidate text with teleprompter script."""

from __future__ import annotations

import re


def normalize_for_match(text: str) -> str:
    """Lowercase text and keep only words/numbers separated by spaces."""
    cleaned = re.sub(r"[^\wáéíóúüñÁÉÍÓÚÜÑ]+", " ", text.lower())
    return " ".join(cleaned.split())


def estimate_char_progress(script_text: str, spoken_text: str) -> int:
    """
    Estimate where the speaker currently is within ``script_text``.

    Strategy:
    - Normalize both strings for robust matching.
    - Look for the longest suffix of spoken words that appears in script.
    - Return a char index inside original script as progress cursor.
    """
    if not script_text.strip() or not spoken_text.strip():
        return 0

    script_norm = normalize_for_match(script_text)
    spoken_norm = normalize_for_match(spoken_text)
    if not script_norm or not spoken_norm:
        return 0

    spoken_words = spoken_norm.split()
    if not spoken_words:
        return 0

    # Prefer recent context: try longer suffixes first.
    max_window = min(12, len(spoken_words))
    best_end = -1

    for size in range(max_window, 1, -1):
        suffix = " ".join(spoken_words[-size:])
        pos = script_norm.rfind(suffix)
        if pos >= 0:
            best_end = pos + len(suffix)
            break

    if best_end < 0:
        # Fallback to single-word progress.
        pos = script_norm.rfind(spoken_words[-1])
        if pos >= 0:
            best_end = pos + len(spoken_words[-1])

    if best_end < 0:
        return 0

    # Map normalized-char ratio back into original script chars.
    ratio = min(1.0, best_end / max(1, len(script_norm)))
    return int(len(script_text) * ratio)

