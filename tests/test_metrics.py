import json
import subprocess
import sys
import time
import unittest

import _path  # noqa: F401
from paraphrase_everything import lang
from paraphrase_everything.metrics import chrf, compare, ngram_overlap, pairwise, tokens

PE = str(_path.SCRIPTS / "pe.py")

ORIGINAL = ("The new policy will reduce costs for small businesses, but critics argue "
            "it may hurt workers in the long run.")
LIGHT = ("The new policy will cut costs for small businesses, though critics argue "
         "it could hurt workers in the long run.")
STANDARD = ("Small businesses will pay less under the new policy, although critics say "
            "workers might suffer over time.")
CREATIVE = ("Critics warn that while the policy trims expenses for small firms, employees "
            "could end up paying the price eventually.")


class PrimitivesTest(unittest.TestCase):
    def test_tokens_by_unit(self):
        self.assertEqual(tokens("Don't STOP, now!", lang.load("en")), ["don't", "stop", "now"])
        self.assertEqual(tokens("今日は、晴れ。", lang.load("ja")), list("今日は晴れ"))
        self.assertEqual(tokens("Ｈｅｌｌｏ　２０２４", lang.load("en")), ["hello", "2024"])

    def test_overlap_bounds(self):
        self.assertEqual(ngram_overlap(["a", "b"], ["a", "b"]), 1.0)
        self.assertEqual(ngram_overlap(["a", "b"], ["c", "d"]), 0.0)
        self.assertEqual(ngram_overlap([], []), 1.0)

    def test_chrf_bounds(self):
        self.assertEqual(chrf("same text", "same text"), 1.0)
        self.assertEqual(chrf("abc", "xyz"), 0.0)
        self.assertEqual(chrf("", ""), 1.0)


class CompareTest(unittest.TestCase):
    def test_divergence_increases_with_rewriting(self):
        scores = [compare(ORIGINAL, t)["overlap"] for t in (ORIGINAL, LIGHT, STANDARD, CREATIVE)]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(scores[0], 1.0)

    def test_mode_bands_match_calibration(self):
        self.assertEqual(compare(ORIGINAL, LIGHT, mode="light")["bands"]["overlap"], "within")
        self.assertEqual(compare(ORIGINAL, STANDARD, mode="standard")["bands"]["overlap"], "within")
        self.assertEqual(compare(ORIGINAL, CREATIVE, mode="creative")["bands"]["overlap"], "within")
        self.assertEqual(compare(ORIGINAL, ORIGINAL, mode="standard")["bands"]["overlap"], "above")

    def test_bands_never_fail(self):
        r = compare(ORIGINAL, ORIGINAL, mode="creative")
        self.assertEqual(r["bands"]["overlap"], "above")
        self.assertTrue(r["ok"])

    def test_target_ratio_is_enforced(self):
        long_text = "one two three four five six seven eight nine ten"
        self.assertTrue(compare(long_text, "one two three four five six seven", target_ratio=0.7)["ok"])
        r = compare(long_text, "one two", target_ratio=0.7)
        self.assertFalse(r["ok"])
        self.assertEqual(r["target"]["status"], "below")

    def test_copied_run_reported(self):
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        r = compare(text + " lambda.", "Intro words. " + text + " mu.")
        self.assertEqual(r["longest_copied_run"]["length"], 10)
        self.assertTrue(r["longest_copied_run"]["text"].startswith("alpha beta"))
        self.assertIsNone(compare(ORIGINAL, STANDARD)["longest_copied_run"]["text"])

    def test_japanese_uses_char_unit(self):
        r = compare("新しい政策はコストを削減する。", "新政策で負担は軽くなる。")
        self.assertEqual((r["lang"], r["length_unit"]), ("ja", "char"))

    def test_unknown_mode(self):
        with self.assertRaises(ValueError):
            compare("a", "b", mode="nope")

    def test_10k_words_fast(self):
        text = "The committee did not approve the 2024 budget of 3,500 dollars yesterday. " * 830
        start = time.perf_counter()
        compare(text, text.replace("committee", "board"))
        self.assertLess(time.perf_counter() - start, 1.0)


class PairwiseTest(unittest.TestCase):
    def test_distinct_variants_pass(self):
        r = pairwise([STANDARD, CREATIVE, LIGHT])
        self.assertEqual(len(r["pairs"]), 3)
        self.assertTrue(r["ok"], r)

    def test_near_duplicates_flagged(self):
        r = pairwise([ORIGINAL, LIGHT.replace("cut", "lower"), STANDARD])
        self.assertFalse(r["ok"])
        self.assertEqual([(p["a"], p["b"]) for p in r["too_similar"]], [(0, 1)])


class CliTest(unittest.TestCase):
    def run_pe(self, *args, stdin=None):
        proc = subprocess.run([sys.executable, PE, "metrics", *args], input=stdin,
                              capture_output=True, text=True, encoding="utf-8")
        return proc.returncode, json.loads(proc.stdout)

    def test_compare_and_target(self):
        code, r = self.run_pe("--original-text", ORIGINAL, "--rewritten-text", STANDARD, "--mode", "standard")
        self.assertEqual((code, r["bands"]["overlap"]), (0, "within"))
        code, r = self.run_pe("-", "--rewritten-text", "Short.", "--target-ratio", "0.7", stdin=ORIGINAL)
        self.assertEqual(code, 1)

    def test_pairwise_from_json_stdin(self):
        code, r = self.run_pe("--pairwise", "--variants-json", "-", stdin=json.dumps([ORIGINAL, ORIGINAL]))
        self.assertEqual((code, r["ok"]), (1, False))


if __name__ == "__main__":
    unittest.main()
