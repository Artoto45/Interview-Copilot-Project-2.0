from src.teleprompter.progress_tracker import estimate_char_progress


def test_progress_detects_basic_alignment():
    script = "I have worked in software engineering for five years."
    spoken = "worked in software engineering"

    progress = estimate_char_progress(script, spoken)

    assert progress > 10
    assert progress < len(script)


def test_progress_returns_zero_when_no_match():
    script = "I enjoy building reliable systems"
    spoken = "completely unrelated sentence"

    assert estimate_char_progress(script, spoken) == 0


def test_progress_prefers_recent_suffix():
    script = "one two three four five six seven"
    spoken = "zero three four five"

    progress = estimate_char_progress(script, spoken)

    assert progress >= script.index("five")
