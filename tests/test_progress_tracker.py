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

    def test_no_jump_to_end_with_single_tail_word(self):
        script = (
            "In my previous role at Webhelp, I faced a project with no prior experience. "
            "I coordinated changes with the team and documented each step. "
            "Overall, I learned that being open and supportive helps when you're new to a project."
        )
        current = int(len(script) * 0.70)
        progress = estimate_char_progress(script, "project", current_progress=current)
        # Should not jump to the last chars on a weak one-word match.
        self.assertTrue(progress <= current + 90)
        self.assertTrue(progress < len(script) - 20)

    def test_end_guard_requires_tail_evidence(self):
        script = (
            "I proactively walked the team through the updated procedures. "
            "This collaboration led to a 92 percent QA score in the first review. "
            "Overall, I learned that being open and supportive can drive great results, "
            "even when you're new to a project."
        )
        current = int(len(script) * 0.75)
        progress = estimate_char_progress(
            script,
            "great results",
            current_progress=current,
        )
        # Without enough tail evidence, we should not snap to the absolute end.
        self.assertTrue(progress < len(script) - 20)

    def test_tail_phrase_can_reach_end(self):
        script = (
            "I proactively walked the team through the updated procedures. "
            "This collaboration led to a 92 percent QA score in the first review. "
            "Overall, I learned that being open and supportive can drive great results, "
            "even when you're new to a project."
        )
        current = int(len(script) * 0.75)
        spoken = "even when you're new to a project"
        progress = estimate_char_progress(script, spoken, current_progress=current)
        self.assertTrue(progress >= len(script) - 25)

    def test_tail_recovery_nudges_forward_with_tail_anchors(self):
        script = (
            "I documented every update and aligned the team with a clear rollout plan. "
            "In the final stage, we closed with handoffplaybook and retrospective cadence "
            "to keep onboarding quality consistent."
        )
        current = int(len(script) * 0.72)
        spoken = "retrospective cadence consistent"
        progress = estimate_char_progress(script, spoken, current_progress=current)
        self.assertTrue(progress > current + 20)
        self.assertTrue(progress <= len(script))

    def test_tail_recovery_applies_when_primary_match_fails(self):
        script = (
            "Absolutely. During a restructuring at Webhelp in October 2025, I noticed some "
            "issues with team morale. **I** wanted to influence leadership to address these "
            "concerns. So, I gathered feedback from my colleagues about their challenges. "
            "**Then**, I documented everything clearly and presented it to my supervisor. "
            "This helped them see the bigger picture. As a result, leadership implemented "
            "new support measures, leading to a 92% satisfaction rate in our team. **It** "
            "was rewarding to see our voices heard. [PAUSE]"
        )
        current = script.lower().find("satisfaction rate in our team") + len(
            "satisfaction rate in our team"
        )
        spoken = (
            "absolutely during a restructuring at webhelp in october 2025 i noticed some "
            "issues with team morale i wanted to influence leadership to address these concerns "
            "so i gathered feedback from my colleagues about their challenges then i documented "
            "everything clearly and presented it to my supervisor this helped them see the "
            "bigger picture as a result leaders implemented support new measures a 92 "
            "satisfaction rate in our team it was to our see heard voices pause"
        )
        progress = estimate_char_progress(script, spoken, current_progress=current)
        voices_end = script.lower().find("voices") + len("voices")
        self.assertTrue(progress >= voices_end)

    def test_final_pass_recovers_further_on_heavy_tail_omission(self):
        script = (
            "Absolutely. During a restructuring at Webhelp in October 2025, I noticed some "
            "issues with team morale. I gathered feedback, documented everything clearly, and "
            "presented it to leadership. As a result, we implemented support measures leading "
            "to a 92 percent satisfaction rate in our team. It was rewarding to see our voices "
            "heard."
        )
        current = script.lower().find("satisfaction rate in our team") + len(
            "satisfaction rate in our team"
        )
        spoken = (
            "i gathered feedback and documented everything clearly then presented it to leadership "
            "as a result we implemented support measures with 92 satisfaction in our team "
            "it was to our see heard voices"
        )
        normal = estimate_char_progress(
            script,
            spoken,
            current_progress=current,
            final_pass=False,
        )
        final = estimate_char_progress(
            script,
            spoken,
            current_progress=current,
            final_pass=True,
        )
        self.assertTrue(final >= normal)
        self.assertTrue(final >= len(script) - 10)

    def test_final_pass_short_script_soft_completion(self):
        script = (
            "My salary expectation is between $600 and $700 USD per month. "
            "I'm flexible and open to discuss based on the role responsibilities."
        )
        current = int(len(script) * 0.80)
        spoken = (
            "my salary expectation is between 600 and 700 usd per month "
            "i am flexible and open to discuss based on the role"
        )
        normal = estimate_char_progress(
            script,
            spoken,
            current_progress=current,
            final_pass=False,
        )
        final = estimate_char_progress(
            script,
            spoken,
            current_progress=current,
            final_pass=True,
        )
        self.assertTrue(final >= normal)
        self.assertTrue(final >= len(script) - 5)

if __name__ == '__main__':
    unittest.main()
