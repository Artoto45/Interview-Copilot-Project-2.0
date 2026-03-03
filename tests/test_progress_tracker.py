import unittest
from src.teleprompter.progress_tracker import estimate_char_progress, normalize_for_match

class TestProgressTracker(unittest.TestCase):
    def setUp(self):
        self.script_short = "Hello world this is a test."
        self.script_long = (
            "So, basically, I've been working in software engineering for about five years now. "
            "What I really enjoy is building scalable systems that make a real difference, "
            "especially when dealing with high-throughput microservices in a cloud-native environment."
        )

    def test_normalize_for_match(self):
        self.assertEqual(normalize_for_match("Hello WORLD!"), "hello world")
        self.assertEqual(normalize_for_match("¿Cómo estás? ¡Bien!"), "cómo estás bien")
        self.assertEqual(normalize_for_match("   lots   of   spaces  "), "lots of spaces")

    def test_empty_inputs(self):
        self.assertEqual(estimate_char_progress("", "hello"), 0)
        self.assertEqual(estimate_char_progress("hello", ""), 0)
        self.assertEqual(estimate_char_progress("   ", "   "), 0)

    def test_perfect_match(self):
        spoken = "so basically i've been working in software engineering"
        progress = estimate_char_progress(self.script_long, spoken)
        # Should match exactly up to "engineering"
        index_in_original = self.script_long.lower().find("engineering") + len("engineering")
        self.assertTrue(progress >= index_in_original - 5 and progress <= index_in_original + 5, 
                        f"Expected around {index_in_original}, got {progress}")

    def test_misheard_single_word_at_end(self):
        # "building scalable systems" -> "building suitable systems"
        spoken = "what i really enjoy is building suitable systems"
        progress = estimate_char_progress(self.script_long, spoken)
        # Should fuzzy match "building" or "building suitable systems" skipping suitable
        # The word right before the error is "building"
        index_building = self.script_long.lower().find("enjoy is building") + len("enjoy is building")
        
        # We expect progress to at least reach the fuzzy matched part
        self.assertTrue(progress >= index_building - 10)

    def test_omitted_word_in_middle(self):
        # Candidate skips "software" -> "working in engineering"
        spoken = "i've been working in engineering for about five years"
        progress = estimate_char_progress(self.script_long, spoken)
        # Suffix "for about five years" perfectly matches.
        index_years = self.script_long.lower().find("five years") + len("five years")
        self.assertTrue(progress >= index_years - 5 and progress <= index_years + 5)

    def test_stuttering_repeated_words(self):
        # "in software in software engineering"
        spoken = "i've been working in software in software engineering for about"
        progress = estimate_char_progress(self.script_long, spoken)
        # Suffix "engineering for about" perfectly matches.
        index_about = self.script_long.lower().find("for about") + len("for about")
        self.assertTrue(progress >= index_about - 5 and progress <= index_about + 5)

    def test_early_jump_protection(self):
        # If the script has the word "the" many times, saying "the" at the beginning shouldn't jump to the end.
        repetitive_script = "the first rule is the second rule which is the third rule"
        spoken = "the first"
        prog1 = estimate_char_progress(repetitive_script, spoken)
        
        spoken2 = "the first rule is the"
        prog2 = estimate_char_progress(repetitive_script, spoken2)
        
        # Prog2 shouldn't jump to the very last 'the'. 
        self.assertTrue(prog1 < prog2)
        # "the first rule is the" ends at index 21
        self.assertTrue(18 <= prog2 <= 25)

    def test_complete_gibberish_no_match(self):
        spoken = "bananas apples oranges"
        progress = estimate_char_progress(self.script_long, spoken)
        self.assertEqual(progress, 0)

    def test_fuzzy_recovery_from_long_error(self):
        # script: "... high-throughput microservices in a cloud-native environment."
        # spoken: "high throughput micro services in the clown native environment"
        spoken = "dealing with high throughput micro services in the clown native environment"
        progress = estimate_char_progress(self.script_long, spoken)
        # Even with mistakes, "environment" is a single word match at the end, 
        # or "native environment" if "native" is close.
        index = self.script_long.lower().find("environment") + len("environment")
        self.assertTrue(progress >= index - 10)

if __name__ == '__main__':
    unittest.main()
