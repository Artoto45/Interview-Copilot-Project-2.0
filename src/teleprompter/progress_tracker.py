"""Utilities to align spoken candidate text with teleprompter script."""

from __future__ import annotations

import re


def normalize_for_match(text: str) -> str:
    """Lowercase text and keep only words/numbers separated by spaces."""
    cleaned = re.sub(r"[^\wáéíóúüñÁÉÍÓÚÜÑ]+", " ", text.lower())
    return " ".join(cleaned.split())


def estimate_char_progress(script_text: str, spoken_text: str, current_progress: int = 0) -> int:
    """
    Estimate where the speaker is.
    We convert the current_progress into a normalized index, and search FORWARD 
    from slightly before that index. This prevents false positives on common words 
    (like 'el' or 'y') from jumping to the end of the script.
    """
    if not script_text.strip() or not spoken_text.strip():
        return current_progress

    script_norm = normalize_for_match(script_text)
    spoken_norm = normalize_for_match(spoken_text)
    
    if not script_norm or not spoken_norm:
        return current_progress

    spoken_words = spoken_norm.split()
    if not spoken_words:
        return current_progress

    # Convert current absolute character progress into normalized string index
    current_ratio = current_progress / max(1, len(script_text))
    current_norm_idx = int(current_ratio * len(script_norm))
    
    # Search window starts slightly behind the current read position to allow corrections
    search_start = max(0, current_norm_idx - 60)
    
    # We only want to look ahead a reasonable amount (e.g. next 400 chars) to avoid jumping pages
    search_end = min(len(script_norm), current_norm_idx + 400)
    search_window = script_norm[search_start:search_end]

    max_window = min(12, len(spoken_words))
    best_end_relative = -1
    
    # 1. Strict suffix matching inside the forward window
    for size in range(max_window, 0, -1):
        suffix = " ".join(spoken_words[-size:])
        # Important: use find() not rfind() to lock onto the NEXT occurrence, not the LAST
        pos = search_window.find(suffix)
        if pos >= 0:
            best_end_relative = pos + len(suffix)
            break

    # 2. Fuzzy fallback: Drop trailing words if the exact suffix fails (misheard last word)
    if best_end_relative < 0:
        recent_words = spoken_words[-max_window:]
        for drop_count in range(1, 3):
            if len(recent_words) > drop_count + 1:
                chunk = " ".join(recent_words[:-drop_count])
                pos = search_window.find(chunk)
                if pos >= 0:
                    best_end_relative = pos + len(chunk) + (drop_count * 5)
                    break

    if best_end_relative < 0:
        return current_progress

    # Reconstruct absolute normalized index
    best_end_absolute = search_start + best_end_relative
    best_end_absolute = min(best_end_absolute, len(script_norm))

    # Map normalized-char ratio back into original script chars.
    ratio = best_end_absolute / max(1, len(script_norm))
    new_progress = int(len(script_text) * ratio)
    
    # Guarantee monotonic progression to prevent minor jitter
    return max(current_progress, new_progress)

