import unittest

import _path  # noqa: F401
from paraphrase_everything import lang
from paraphrase_everything.text import count, markers_pattern, split_sentences


def sentences(text, code):
    return [text[s:e] for s, e in split_sentences(text, lang.load(code))]


class SplitSentencesTest(unittest.TestCase):
    def test_english_abbreviations_initials_decimals(self):
        self.assertEqual(sentences("Dr. Smith weighed 3.5 kg. J. Doe agreed!", "en"),
                         ["Dr. Smith weighed 3.5 kg.", "J. Doe agreed!"])

    def test_closing_quotes_stay_with_sentence(self):
        self.assertEqual(sentences('He said "stop." Then left.', "en"),
                         ['He said "stop."', "Then left."])

    def test_vietnamese(self):
        self.assertEqual(sentences("Ông ở TP. Hồ Chí Minh. Bà ở Hà Nội.", "vi"),
                         ["Ông ở TP. Hồ Chí Minh.", "Bà ở Hà Nội."])

    def test_japanese_without_spaces(self):
        self.assertEqual(sentences("今日は晴れ。「明日は？」と聞いた。", "ja"),
                         ["今日は晴れ。", "「明日は？」", "と聞いた。"])

    def test_newlines_split(self):
        self.assertEqual(sentences("# Title\n- item one\n\nBody text", "en"),
                         ["# Title", "- item one", "Body text"])


class MarkersTest(unittest.TestCase):
    def test_longest_first_counts_once(self):
        p = markers_pattern(lang.load("vi")["negation_markers"], True)
        self.assertEqual(count(p, "Tôi không hề biết."), 1)
        self.assertEqual(count(p, "Tôi không biết, chưa từng nghe."), 2)

    def test_contractions_and_word_bounds(self):
        p = markers_pattern(lang.load("en")["negation_markers"], True)
        self.assertEqual(count(p, "I don't know, nobody knows."), 2)
        self.assertEqual(count(p, "Nothing is noted in Nottingham."), 1)

    def test_empty_markers(self):
        self.assertIsNone(markers_pattern([], True))
        self.assertEqual(count(None, "anything"), 0)


if __name__ == "__main__":
    unittest.main()
