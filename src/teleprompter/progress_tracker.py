"""Utilities to align spoken candidate text with teleprompter script."""

from __future__ import annotations

import bisect
import re


_TAIL_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "at",
    "by",
    "is",
    "are",
    "was",
    "were",
    "it",
    "this",
    "that",
    "as",
    "be",
    "from",
}


def normalize_for_match(text: str) -> str:
    """Lowercase text and keep only word tokens separated by spaces."""
    cleaned = re.sub(r"[^\w]+", " ", (text or "").lower(), flags=re.UNICODE)
    return " ".join(cleaned.split())


def _normalize_with_char_map(text: str) -> tuple[str, list[int]]:
    """
    Normalize text while keeping a map from each normalized character
    to its corresponding original char position (1-based end index).
    """
    out_chars: list[str] = []
    norm_to_orig_end: list[int] = []
    in_space = True

    for idx, char in enumerate((text or "").lower()):
        if char.isalnum() or char == "_":
            out_chars.append(char)
            norm_to_orig_end.append(idx + 1)
            in_space = False
        else:
            if not in_space and out_chars:
                out_chars.append(" ")
                norm_to_orig_end.append(idx + 1)
            in_space = True

    if out_chars and out_chars[-1] == " ":
        out_chars.pop()
        norm_to_orig_end.pop()

    return "".join(out_chars), norm_to_orig_end


def estimate_char_progress(
    script_text: str,
    spoken_text: str,
    current_progress: int = 0,
    final_pass: bool = False,
) -> int:
    """
    Estimate where the speaker is in the script.

    Behavior goals:
    - move forward monotonically
    - avoid jumping to the end from weak one-word matches
    - allow recovery from minor ASR errors using a short fuzzy fallback
    - in final_pass mode, apply a stronger late-tail rescue on speech stop
    """
    if not (script_text or "").strip() or not (spoken_text or "").strip():
        return current_progress

    script_norm, norm_to_orig_end = _normalize_with_char_map(script_text)
    spoken_norm = normalize_for_match(spoken_text)

    if not script_norm or not spoken_norm or not norm_to_orig_end:
        return current_progress

    spoken_words = spoken_norm.split()
    if not spoken_words:
        return current_progress

    current_norm_idx = bisect.bisect_left(norm_to_orig_end, current_progress)
    current_norm_idx = min(max(0, current_norm_idx), max(0, len(script_norm) - 1))

    back_window = 120 if final_pass else 80
    forward_window = 500 if final_pass else 320
    search_start = max(0, current_norm_idx - back_window)
    search_end = min(len(script_norm), current_norm_idx + forward_window)
    search_window = script_norm[search_start:search_end]

    max_window = min(12, len(spoken_words))
    if max_window <= 0:
        return current_progress

    min_window = 2 if len(script_norm) >= 140 else 1

    # For long scripts, a single token can cause bad jumps near the end.
    if len(spoken_words) == 1 and len(script_norm) >= 140:
        only = spoken_words[0]
        if len(only) < 8 or current_progress < int(len(script_text) * 0.90):
            return current_progress
        min_window = 1

    best_end_relative = -1
    best_match_words = 0

    # 1) Strict suffix matching in a bounded forward window.
    for size in range(max_window, min_window - 1, -1):
        suffix = " ".join(spoken_words[-size:])
        pos = search_window.find(suffix)
        if pos >= 0:
            best_end_relative = pos + len(suffix)
            best_match_words = size
            break

    # 2) Fuzzy fallback: drop up to 2 trailing words for minor ASR drift.
    if best_end_relative < 0:
        recent_words = spoken_words[-max_window:]
        for drop_count in range(1, 3):
            chunk_size = len(recent_words) - drop_count
            if chunk_size >= min_window:
                chunk = " ".join(recent_words[:-drop_count])
                pos = search_window.find(chunk)
                if pos >= 0:
                    best_end_relative = pos + len(chunk)
                    best_match_words = chunk_size
                    break

    # 3) Strong single-word rescue for noisy ASR (long, unique token only).
    if best_end_relative < 0:
        recent_words = spoken_words[-max_window:]
        for token in reversed(recent_words):
            if len(token) < 7:
                continue
            pos = search_window.find(token)
            if pos >= 0 and search_window.count(token) == 1:
                best_end_relative = pos + len(token)
                best_match_words = 1
                break

    if best_end_relative < 0:
        # Keep current progress, but still run the tail recovery pass below.
        # This rescues noisy near-end reads where strict/fuzzy window match fails.
        new_progress = current_progress
    else:
        best_end_absolute = search_start + best_end_relative
        best_end_absolute = min(best_end_absolute, len(script_norm))

        if best_end_absolute <= 0:
            new_progress = current_progress
        else:
            map_idx = min(best_end_absolute - 1, len(norm_to_orig_end) - 1)
            new_progress = norm_to_orig_end[map_idx]

        # Guard unrealistic leaps from weak matches.
        max_forward_jump = max(
            90,
            int(len(spoken_norm) * 2.8),
            len(spoken_words) * 24,
        )
        new_progress = min(new_progress, current_progress + max_forward_jump)

        # Do not enter the last segment without enough lexical evidence.
        end_guard_start = max(0, len(script_text) - 170)
        if new_progress >= end_guard_start:
            tail_words = script_norm.split()[-10:]
            spoken_recent = set(spoken_words[-14:])
            overlap = sum(1 for word in tail_words if word in spoken_recent)
            if overlap < 3 and best_match_words < 4:
                new_progress = min(new_progress, max(current_progress, end_guard_start - 1))

    # Tail recovery pass:
    # If the user has progressed through most of the response, allow a bounded
    # forward nudge from strong lexical anchors in the tail. This improves
    # completion in adversarial/paraphrased reads without reintroducing end jumps.
    tail_start_ratio = 0.65 if final_pass else 0.72
    if current_progress >= int(len(script_text) * tail_start_ratio):
        tail_norm_start = max(0, len(script_norm) - (420 if final_pass else 260))
        tail_segment = script_norm[tail_norm_start:]
        tail_recent = spoken_words[-(28 if final_pass else 16):]
        tail_script_words = script_norm.split()[-(24 if final_pass else 16):]
        tail_content_words = [
            word
            for word in tail_script_words
            if len(word) >= 4 and word not in _TAIL_STOPWORDS
        ]
        tail_overlap = sum(
            1
            for word in tail_content_words
            if word in set(tail_recent)
        )

        min_tail_overlap = 1 if final_pass else 2
        if tail_overlap >= min_tail_overlap:
            recover_norm_end = -1
            for token in reversed(tail_recent):
                min_token_len = 5 if final_pass else 6
                if len(token) < min_token_len:
                    continue
                pos = tail_segment.find(token)
                if pos < 0:
                    continue
                # Avoid weak anchors that appear multiple times in the tail segment.
                if tail_segment.count(token) > 1:
                    continue
                candidate_norm_end = tail_norm_start + pos + len(token)
                candidate_map_idx = min(
                    candidate_norm_end - 1,
                    len(norm_to_orig_end) - 1,
                )
                candidate_progress = norm_to_orig_end[candidate_map_idx]
                if candidate_progress > current_progress:
                    recover_norm_end = candidate_norm_end
                    break

            # Secondary rescue: phrase-level anchor from recent tail words.
            if recover_norm_end < 0:
                phrase_sizes = (4, 3, 2) if final_pass else (3, 2)
                for size in phrase_sizes:
                    if len(tail_recent) < size:
                        continue
                    for idx in range(len(tail_recent) - size, -1, -1):
                        phrase_words = tail_recent[idx:idx + size]
                        if any(
                            len(word) < 4 or word in _TAIL_STOPWORDS
                            for word in phrase_words
                        ):
                            continue
                        phrase = " ".join(phrase_words)
                        pos = tail_segment.rfind(phrase)
                        if pos < 0:
                            continue
                        candidate_norm_end = tail_norm_start + pos + len(phrase)
                        candidate_map_idx = min(
                            candidate_norm_end - 1,
                            len(norm_to_orig_end) - 1,
                        )
                        candidate_progress = norm_to_orig_end[candidate_map_idx]
                        if candidate_progress > current_progress:
                            recover_norm_end = candidate_norm_end
                            break
                    if recover_norm_end > 0:
                        break

            if recover_norm_end > 0:
                recover_map_idx = min(
                    recover_norm_end - 1,
                    len(norm_to_orig_end) - 1,
                )
                recover_progress = norm_to_orig_end[recover_map_idx]

                max_tail_step = max(
                    120 if final_pass else 80,
                    int(len(spoken_norm) * (2.7 if final_pass else 2.2)),
                    len(spoken_words) * (24 if final_pass else 18),
                )
                recover_progress = min(
                    recover_progress,
                    current_progress + max_tail_step,
                )
                if recover_progress > new_progress:
                    new_progress = recover_progress

    # Final-pass short-script completion:
    # For brief answers, ASR often drops the last 1-2 words even when the
    # candidate effectively finished reading. When most tail content words are
    # present, allow a soft snap to the end to preserve readability.
    if final_pass and len(script_text) <= 220:
        tail_words = script_norm.split()[-12:]
        tail_content_words = [
            word for word in tail_words
            if len(word) >= 4 and word not in _TAIL_STOPWORDS
        ]
        if tail_content_words and current_progress >= int(len(script_text) * 0.78):
            spoken_recent_set = set(spoken_words[-32:])
            missing_content = [
                word for word in tail_content_words
                if word not in spoken_recent_set
            ]
            matched_content = len(tail_content_words) - len(missing_content)
            min_matched = max(3, int(len(tail_content_words) * 0.60))
            if matched_content >= min_matched and len(missing_content) <= 3:
                new_progress = max(new_progress, len(script_text) - 2)

    return max(current_progress, new_progress)
