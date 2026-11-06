"""lib/metrics.py（検索の指標）の試験。通信なし。

実行：basic フォルダで  python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import metrics  # noqa: E402


class NdcgTest(unittest.TestCase):
    def test_rank_one_is_one(self):
        self.assertAlmostEqual(metrics.ndcg_at_k(["a", "b"], ["a"], 10), 1.0)

    def test_rank_two_and_three(self):
        self.assertAlmostEqual(metrics.ndcg_at_k(["x", "a"], ["a"], 10), 0.6309, places=4)
        self.assertAlmostEqual(metrics.ndcg_at_k(["x", "y", "a"], ["a"], 10), 0.5, places=4)

    def test_outside_k_is_zero(self):
        ranked = [f"x{i}" for i in range(10)] + ["a"]
        self.assertEqual(metrics.ndcg_at_k(ranked, ["a"], 10), 0.0)

    def test_no_relevant_is_zero(self):
        self.assertEqual(metrics.ndcg_at_k(["a"], [], 10), 0.0)

    def test_two_relevant(self):
        # 正解2人が1位と3位：DCG = 1 + 0.5、IDCG = 1 + 0.6309
        self.assertAlmostEqual(metrics.ndcg_at_k(["a", "x", "b"], ["a", "b"], 10), 1.5 / 1.6309, places=4)

    def test_discount_values(self):
        self.assertAlmostEqual(metrics.discount(1), 1.0)
        self.assertAlmostEqual(metrics.discount(10), 0.2891, places=4)

    def test_rank_ten_counts_and_rank_eleven_does_not(self):
        at10 = [f"x{i}" for i in range(9)] + ["a"]
        at11 = [f"x{i}" for i in range(10)] + ["a"]
        self.assertAlmostEqual(metrics.ndcg_at_k(at10, ["a"], 10), 0.2891, places=4)
        self.assertEqual(metrics.recall_at_k(at10, ["a"], 10), 1.0)
        self.assertEqual(metrics.ndcg_at_k(at11, ["a"], 10), 0.0)
        self.assertEqual(metrics.recall_at_k(at11, ["a"], 10), 0.0)
        self.assertEqual(metrics.first_rank(at11, ["a"]), 11)

    def test_one_of_two_answers_at_rank_one(self):
        # 正解2人のうち1人だけが1位：1位かは 1 でも、nDCG は 1.0 にならない
        e = metrics.evaluate(["a"], ["a", "b"], 10)
        self.assertAlmostEqual(e["ndcg"], 0.613147, places=6)
        self.assertEqual(e["recall"], 0.5)
        self.assertEqual(e["hit1"], 1.0)

    def test_more_answers_than_k(self):
        # 正解が12人で、上位10件が全部正解：IDCG は上位10件ぶんなので nDCG は 1.0、再現率は 10/12
        relevant = [f"a{i}" for i in range(12)]
        self.assertAlmostEqual(metrics.ideal_dcg(relevant, 10), metrics.dcg([1] * 10))
        self.assertAlmostEqual(metrics.ndcg_at_k(relevant[:10], relevant, 10), 1.0)
        self.assertAlmostEqual(metrics.recall_at_k(relevant[:10], relevant, 10), 10 / 12)


class OtherMetricsTest(unittest.TestCase):
    def test_recall(self):
        self.assertEqual(metrics.recall_at_k(["a", "x"], ["a", "b"], 10), 0.5)
        self.assertEqual(metrics.recall_at_k(["x"], [], 10), 0.0)

    def test_hit_at_1(self):
        self.assertEqual(metrics.hit_at_1(["a", "b"], ["a"]), 1.0)
        self.assertEqual(metrics.hit_at_1(["b", "a"], ["a"]), 0.0)
        self.assertEqual(metrics.hit_at_1([], ["a"]), 0.0)

    def test_first_rank(self):
        self.assertEqual(metrics.first_rank(["x", "a"], ["a"]), 2)
        self.assertIsNone(metrics.first_rank(["x"], ["a"]))

    def test_average(self):
        rows = [metrics.evaluate(["a"], ["a"]), metrics.evaluate(["x"], ["a"])]
        a = metrics.average(rows)
        self.assertEqual(a["hit1"], 0.5)
        self.assertEqual(a["ndcg"], 0.5)
        self.assertEqual(metrics.average([]), {"ndcg": 0.0, "recall": 0.0, "hit1": 0.0})

    def test_trace_rows(self):
        rows = metrics.trace_rows(["x", "a"], ["a"], 10, label=str.upper)
        self.assertEqual(rows[0][:4], [1, "X", "", 0])
        self.assertEqual(rows[1][:4], [2, "A", "正解", 1])
        self.assertEqual(rows[1][4:], ["0.63", "0.63"])


if __name__ == "__main__":
    unittest.main()
