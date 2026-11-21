"""Tests for multiple diverse variants (story 013).

Verifies that diverse variants along distinct axes pass individual fidelity checks,
satisfy pairwise divergence thresholds, and work on raw text without files across en, vi, and ja.
"""

import json
import subprocess
import sys
import unittest

import _path  # noqa: F401
from paraphrase_everything import check, metrics

PE = str(_path.SCRIPTS / "pe.py")

# English test fixtures
EN_ORIGINAL = ("The research team published their findings in 2024, demonstrating that "
               "renewable energy significantly reduces industrial carbon emissions.")
# Variant 1 - Structure: invert clause order and passive voice
EN_VAR_STRUCTURE = ("Industrial carbon emissions are significantly reduced by renewable energy, "
                    "as demonstrated by findings published by the research team in 2024.")
# Variant 2 - Register / Concision: formal and academic, concise phrasing
EN_VAR_FORMAL = ("In 2024, researchers confirmed that adopting renewable energy substantially "
                 "curbs industrial carbon output.")
# Variant 3 - Vocabulary / Direct voice: active, fresh phrasing
EN_VAR_DIRECT = ("A 2024 study showed that clean energy dramatically cuts the carbon footprint "
                 "of industrial operations.")
# Near duplicate of Variant 1 for testing pairwise failure
EN_VAR_NEAR_DUP = ("Industrial carbon emissions are notably reduced by renewable energy, "
                   "as demonstrated by findings published by the research team in 2024.")

# Vietnamese test fixtures
VI_ORIGINAL = ("Vào năm 2023, công ty đã đầu tư 50 tỷ đồng để mở rộng dây chuyền sản xuất "
               "nhằm đáp ứng nhu cầu ngày càng tăng của khách hàng.")
# Variant 1 - Structure: đưa mục đích lên trước, thay đổi cấu trúc câu
VI_VAR_STRUCTURE = ("Nhằm đáp ứng lượng nhu cầu ngày một lớn từ khách hàng, năm 2023 công ty "
                    "đã giải ngân 50 tỷ đồng nhằm nâng cấp và mở rộng dây chuyền sản xuất.")
# Variant 2 - Concision & Formal: súc tích, văn phong báo cáo
VI_VAR_CONCISE = ("Khoản đầu tư 50 tỷ đồng được công ty phân bổ năm 2023 nhằm phát triển "
                  "hạ tầng sản xuất theo đà tăng trưởng của thị trường.")
# Variant 3 - Vocabulary: dùng từ vựng thay thế hợp lý
VI_VAR_VOCAB = ("Doanh nghiệp đã dành nguồn kinh phí 50 tỷ đồng trong năm 2023 để gia tăng "
                "quy mô chế tạo phục vụ sức mua gia tăng của người tiêu dùng.")

# Japanese test fixtures
JA_ORIGINAL = "同社は2024年に500人の新規採用を行い、海外事業の展開を加速させる計画である。"
# Variant 1 - Structure: 目的を前置
JA_VAR_STRUCTURE = "海外事業の拡大をスピードアップさせるため、同社は2024年に500名の新たな人材を採用する見通しだ。"
# Variant 2 - Register: フォーマル・簡潔
JA_VAR_FORMAL = "2024年度における500人規模の新規雇用を通じて、グローバル市場への進出を推し進める方針を示した。"
# Variant 3 - Vocabulary: 言い換え
JA_VAR_VOCAB = "国外ビジネスの成長を後押しすべく、2024年にスタッフ500人を新たに迎え入れる方針を掲げている。"


class VariantsFidelityTest(unittest.TestCase):
    """Verify that every variant preserves facts and numbers across languages."""

    def test_english_variants_pass_fidelity(self):
        for var in (EN_VAR_STRUCTURE, EN_VAR_FORMAL, EN_VAR_DIRECT):
            report = check.check(EN_ORIGINAL, var, lang_code="en")
            self.assertTrue(report["ok"], f"Failed fidelity: {report}")

    def test_vietnamese_variants_pass_fidelity(self):
        for var in (VI_VAR_STRUCTURE, VI_VAR_CONCISE, VI_VAR_VOCAB):
            report = check.check(VI_ORIGINAL, var, lang_code="vi")
            self.assertTrue(report["ok"], f"Failed fidelity: {report}")

    def test_japanese_variants_pass_fidelity(self):
        for var in (JA_VAR_STRUCTURE, JA_VAR_FORMAL, JA_VAR_VOCAB):
            report = check.check(JA_ORIGINAL, var, lang_code="ja")
            self.assertTrue(report["ok"], f"Failed fidelity: {report}")

    def test_corrupted_variant_fails_fidelity(self):
        bad_number = EN_VAR_DIRECT.replace("2024", "2025")
        report = check.check(EN_ORIGINAL, bad_number, lang_code="en")
        self.assertFalse(report["ok"])
        self.assertTrue(any(e["type"].startswith("number_") for e in report["errors"]))


class VariantsDivergenceTest(unittest.TestCase):
    """Verify pairwise divergence and threshold detection across diverse variants."""

    def test_english_diverse_variants_pairwise_pass(self):
        variants = [EN_VAR_STRUCTURE, EN_VAR_FORMAL, EN_VAR_DIRECT]
        report = metrics.pairwise(variants, lang_code="en", max_overlap=0.50)
        self.assertTrue(report["ok"], f"Pairs too similar: {report['too_similar']}")
        self.assertEqual(len(report["pairs"]), 3)

    def test_vietnamese_diverse_variants_pairwise_pass(self):
        variants = [VI_VAR_STRUCTURE, VI_VAR_CONCISE, VI_VAR_VOCAB]
        report = metrics.pairwise(variants, lang_code="vi", max_overlap=0.50)
        self.assertTrue(report["ok"], f"Pairs too similar: {report['too_similar']}")
        self.assertEqual(len(report["pairs"]), 3)

    def test_japanese_diverse_variants_pairwise_pass(self):
        variants = [JA_VAR_STRUCTURE, JA_VAR_FORMAL, JA_VAR_VOCAB]
        report = metrics.pairwise(variants, lang_code="ja", max_overlap=0.50)
        self.assertTrue(report["ok"], f"Pairs too similar: {report['too_similar']}")
        self.assertEqual(len(report["pairs"]), 3)

    def test_near_duplicate_pair_flagged(self):
        variants = [EN_VAR_STRUCTURE, EN_VAR_NEAR_DUP, EN_VAR_DIRECT]
        report = metrics.pairwise(variants, lang_code="en", max_overlap=0.50)
        self.assertFalse(report["ok"])
        self.assertEqual(len(report["too_similar"]), 1)
        self.assertEqual((report["too_similar"][0]["a"], report["too_similar"][0]["b"]), (0, 1))

    def test_custom_max_overlap_threshold(self):
        variants = [EN_VAR_STRUCTURE, EN_VAR_FORMAL]
        strict = metrics.pairwise(variants, lang_code="en", max_overlap=0.10)
        self.assertFalse(strict["ok"])


class VariantsCliTest(unittest.TestCase):
    """Test pairwise variant evaluation on raw text without files via CLI."""

    def run_pe(self, *args, stdin=None):
        proc = subprocess.run([sys.executable, PE, *args], input=stdin,
                              capture_output=True, text=True, encoding="utf-8")
        return proc.returncode, json.loads(proc.stdout) if proc.stdout else {}

    def test_pairwise_with_variant_flags_raw_text(self):
        code, out = self.run_pe(
            "metrics", "--pairwise",
            "--variant", EN_VAR_STRUCTURE,
            "--variant", EN_VAR_FORMAL,
            "--variant", EN_VAR_DIRECT,
        )
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["count"], 3)
        self.assertEqual(len(out["pairs"]), 3)

    def test_pairwise_near_duplicates_returns_issues(self):
        code, out = self.run_pe(
            "metrics", "--pairwise",
            "--variant", EN_VAR_STRUCTURE,
            "--variant", EN_VAR_NEAR_DUP,
        )
        self.assertEqual(code, 1)
        self.assertFalse(out["ok"])
        self.assertEqual(len(out["too_similar"]), 1)

    def test_pairwise_variants_json_stdin(self):
        variants = [EN_VAR_STRUCTURE, EN_VAR_FORMAL, EN_VAR_DIRECT]
        code, out = self.run_pe(
            "metrics", "--pairwise", "--variants-json", "-",
            stdin=json.dumps(variants),
        )
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main()
