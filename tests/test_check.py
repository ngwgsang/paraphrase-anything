import json
import subprocess
import sys
import time
import unittest

import _path  # noqa: F401
from paraphrase_everything.check import check

PE = str(_path.SCRIPTS / "pe.py")


def types(items):
    return sorted(i["type"] for i in items)


class ErrorsTest(unittest.TestCase):
    def test_identical_is_ok(self):
        text = "Revenue grew 42% in 2024 [1]. See https://a.io/v2 for details."
        r = check(text, text)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["alignment"], "sentence")

    def test_changed_number(self):
        r = check("Revenue grew 42% in 2024.", "In 2024, revenue rose by 45%.")
        self.assertFalse(r["ok"])
        self.assertEqual(sorted((e["type"], e["value"]) for e in r["errors"]),
                         [("number_extra", "45"), ("number_missing", "42")])

    def test_reordered_numbers_are_fine(self):
        r = check("From 2020 to 2024, users doubled to 10,000.",
                  "Users doubled to 10,000 between 2020 and 2024.")
        self.assertEqual(r["errors"], [])

    def test_vietnamese_number_format(self):
        r = check("Giá là 1.000,5 đồng.", "Mức giá 1000,5 đồng.", lang_code="vi")
        self.assertEqual(r["errors"], [])

    def test_full_width_digits(self):
        self.assertEqual(check("参加者は３０人です。", "参加したのは30人だ。")["errors"], [])

    def test_citation_removed(self):
        r = check("Results improved [2].", "Results got better.")
        self.assertEqual(types(r["errors"]), ["citation_missing"])

    def test_author_year_citation(self):
        r = check("This was shown (Smith et al., 2020).", "This was demonstrated.")
        self.assertEqual(types(r["errors"]), ["citation_missing"])

    def test_url_changed_and_url_digits_ignored(self):
        r = check("Docs at https://a.io/v2 now.", "Docs now live at https://a.io/v3.")
        self.assertEqual(types(r["errors"]), ["protected_span_extra", "protected_span_missing"])

    def test_code_preserved(self):
        r = check("Run `make test` first.", "First, run `make tests`.")
        self.assertEqual(types(r["errors"]), ["protected_span_extra", "protected_span_missing"])

    def test_placeholder_leftover(self):
        r = check("Run `x` now.", "Run ⟦P1⟧ now.")
        self.assertIn("placeholder_leftover", types(r["errors"]))


class WarningsTest(unittest.TestCase):
    def test_negation_dropped(self):
        r = check("The drug is not effective.", "The drug works well.")
        self.assertEqual(types(r["warnings"]), ["negation_mismatch"])

    def test_hedge_dropped_vi(self):
        r = check("Thuốc có thể gây buồn ngủ.", "Thuốc gây buồn ngủ.")
        self.assertEqual(types(r["warnings"]), ["hedge_mismatch"])

    def test_vi_multiword_negation_not_flagged(self):
        r = check("Tôi không hề biết chuyện đó.", "Tôi không biết gì về chuyện đó.")
        self.assertEqual(r["warnings"], [])

    def test_ja_negation(self):
        r = check("彼は会議に来なかった。", "彼は会議に来た。")
        self.assertEqual(types(r["warnings"]), ["negation_mismatch"])
        self.assertIn("proper_noun", r["unsupported"])

    def test_proper_noun_missing(self):
        r = check("We met Alice in Paris last week.", "We met her in the city last week.")
        self.assertEqual(sorted(w["value"] for w in r["warnings"] if w["type"] == "proper_noun_missing"),
                         ["Alice", "Paris"])

    def test_proper_noun_moved_to_sentence_start_is_fine(self):
        r = check("Yesterday Alice called.", "Alice called yesterday.")
        self.assertEqual(r["warnings"], [])

    def test_merged_sentences_align(self):
        r = check("Sales rose sharply. Profits fell slightly.",
                  "Sales rose sharply, while profits fell slightly.")
        self.assertTrue(r["ok"], r)

    def test_split_sentence_aligns(self):
        r = check("The team shipped the release on time and the customers were happy.",
                  "The team shipped the release on time. The customers were happy.")
        self.assertTrue(r["ok"], r)

    def test_omitted_sentence(self):
        original = ("The project started in spring. It faced budget problems. "
                    "Engineers rewrote the storage layer. Users noticed faster load times.")
        rewritten = ("The project began in spring. It ran into budget trouble. "
                     "Users saw quicker load times.")
        r = check(original, rewritten)
        unaligned = [w for w in r["warnings"] if w["type"] == "sentence_unaligned"]
        self.assertEqual(len(unaligned), 1)
        self.assertIn("storage layer", unaligned[0]["original"])

    def test_added_sentence(self):
        r = check("The cat slept on the sofa.",
                  "The cat slept on the sofa. It had chased mice all night long.")
        self.assertEqual(types(r["warnings"]), ["sentence_added"])

    def test_unknown_language_reports_unsupported(self):
        r = check("Some text here.", "Some text here.", lang_code="xx")
        self.assertEqual(sorted(r["unsupported"]), ["hedge", "negation", "proper_noun"])
        self.assertTrue(r["ok"])


class AcceptTest(unittest.TestCase):
    def test_antonym_rewrite_accepted(self):
        r = check("This is not uncommon.", "This is common.")
        self.assertFalse(r["ok"])
        wid = r["warnings"][0]["id"]
        r = check("This is not uncommon.", "This is common.",
                  accept=[{"id": wid, "reason": "double negative rewritten as positive"}])
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["accepted"][0]["reason"], "double negative rewritten as positive")

    def test_errors_and_reasonless_accepts_rejected(self):
        r = check("Not 5 apples.", "6 apples.",
                  accept=[{"id": "e1", "reason": "x"}, {"id": "w1", "reason": " "}, {"id": "w9", "reason": "x"}])
        self.assertFalse(r["ok"])
        self.assertEqual([x["why"] for x in r["rejected_accepts"]],
                         ["error ids cannot be accepted", "missing reason", "unknown id"])


class PerformanceTest(unittest.TestCase):
    def test_10k_words_under_a_second(self):
        sentence = "The committee did not approve the 2024 budget of 3,500 dollars yesterday. "
        text = sentence * 830  # ~10k words
        start = time.perf_counter()
        check(text, text)
        self.assertLess(time.perf_counter() - start, 1.0)


class CliTest(unittest.TestCase):
    def run_pe(self, *args, stdin=None):
        proc = subprocess.run([sys.executable, PE, "check", *args], input=stdin,
                              capture_output=True, text=True, encoding="utf-8")
        return proc.returncode, json.loads(proc.stdout)

    def test_exit_codes(self):
        code, r = self.run_pe("--original-text", "Có 3 con mèo.", "--rewritten-text", "Có ba con mèo.")
        self.assertEqual((code, r["lang"]), (1, "vi"))
        code, r = self.run_pe("-", "--rewritten-text", "Có 3 con mèo nhỏ.", stdin="Có 3 con mèo nhỏ.")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
