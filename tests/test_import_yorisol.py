#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""test_import_yorisol.py — ヨリソル設問CSVの変換の回帰テスト（2026-09-05）

実物のCSVは使わない（手元に無いPCでも走るように、テストの中で作る）。
見ているのは「形を崩さずポータルの3テーブルに落ちるか」と「おかしい入力で黙って通さないか」。

  py -X utf8 -m unittest discover -s tests -p "test_import_yorisol.py" -v
"""
from __future__ import annotations

import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import import_yorisol as iy  # noqa: E402

QHEAD = ["システムID", "設問名", "作成者アカウント", "カテゴリ名", "設問ステータス",
         "設問文/説明", "形式", "解説の表示", "解説ラベル", "解説 (共通)"]
AHEAD = ["設問システムID", "設問名", "正解", "選択肢/ラベル", "正答値", "選択肢表示順"]


def qrow(sid, prompt, fmt="単一選択", cat=r"全体\総合\★テスト"):
    return [sid, f"問{sid}", "teacher01", cat, "公開", prompt, fmt, "0", "解説", ""]


def arow(sid, ok, label, order=""):
    return [sid, f"問{sid}", ok, label, "", order]


def write_csv(dirpath: Path, name: str, head: list[str], rows: list[list[str]], enc="cp932") -> Path:
    p = dirpath / name
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(head)
    w.writerows(rows)
    p.write_bytes(buf.getvalue().encode(enc))
    return p


class HtmlTest(unittest.TestCase):
    def test_br_becomes_newline(self):
        t, _ = iy.html_to_text("あ<br />い<br>う<BR/>え")
        self.assertEqual(t, "あ\nい\nう\nえ")

    def test_span_is_stripped_but_text_stays(self):
        t, dropped = iy.html_to_text('<span style="color:#e74c3c;">（　）</span>に入れます')
        self.assertEqual(t, "（　）に入れます")
        self.assertEqual(dropped, 1, "外した装飾の数を数えていること")

    def test_entities_are_unescaped(self):
        t, _ = iy.html_to_text("A&nbsp;&amp;&nbsp;B &lt;tag&gt;")
        self.assertNotIn("&amp;", t)
        self.assertIn("&", t)
        self.assertIn("<tag>", t)

    def test_blank_lines_are_collapsed_and_trimmed(self):
        t, _ = iy.html_to_text("あ<br /><br /><br /><br />い<br />")
        self.assertEqual(t, "あ\n\nい")


class BuildTest(unittest.TestCase):
    def build(self, qrows, arows):
        return iy.build([dict(zip(QHEAD, r)) for r in qrows],
                        [dict(zip(AHEAD, r)) for r in arows])

    def test_two_choices_one_correct(self):
        items, warn = self.build(
            [qrow("1", "（　）に入れます")],
            [arow("1", "0", "まちがい"), arow("1", "1", "せいかい")])
        self.assertEqual(warn, [])
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["choice_a"], "まちがい")
        self.assertEqual(it["choice_b"], "せいかい")
        self.assertEqual(it["correct"], "b", "2番目が正解なら b")
        self.assertEqual(it["seq"], 1)

    def test_first_choice_correct_is_a(self):
        items, _ = self.build([qrow("1", "文")],
                              [arow("1", "1", "せいかい"), arow("1", "0", "まちがい")])
        self.assertEqual(items[0]["correct"], "a")

    def test_display_order_is_honoured(self):
        items, _ = self.build([qrow("1", "文")],
                              [arow("1", "1", "あと", "2"), arow("1", "0", "さき", "1")])
        self.assertEqual(items[0]["choice_a"], "さき")
        self.assertEqual(items[0]["correct"], "b", "並べ替えた後の位置で正解を決めること")

    def test_three_choices_is_rejected(self):
        items, warn = self.build([qrow("1", "文")],
                                 [arow("1", "1", "A"), arow("1", "0", "B"), arow("1", "0", "C")])
        self.assertEqual(items, [], "2択でないものを黙って通さない")
        self.assertTrue(any("選択肢が 3" in w for w in warn))

    def test_no_correct_is_rejected(self):
        items, warn = self.build([qrow("1", "文")], [arow("1", "0", "A"), arow("1", "0", "B")])
        self.assertEqual(items, [])
        self.assertTrue(any("正解が 0" in w for w in warn))

    def test_two_correct_is_rejected(self):
        items, warn = self.build([qrow("1", "文")], [arow("1", "1", "A"), arow("1", "1", "B")])
        self.assertEqual(items, [])
        self.assertTrue(any("正解が 2" in w for w in warn))

    def test_unknown_format_warns_but_keeps(self):
        items, warn = self.build([qrow("1", "文", fmt="複数選択")],
                                 [arow("1", "1", "A"), arow("1", "0", "B")])
        self.assertEqual(len(items), 1, "警告は出すが変換自体は残す（人が判断する）")
        self.assertTrue(any("複数選択" in w for w in warn))

    def test_missing_choices_are_reported(self):
        items, warn = self.build([qrow("1", "文")], [])
        self.assertEqual(items, [])
        self.assertTrue(any("選択肢が 0" in w for w in warn))


class SqlTest(unittest.TestCase):
    def test_single_quote_is_escaped(self):
        items = [{"seq": 1, "prompt": "It's ok", "choice_a": "a'b", "choice_b": "B", "correct": "a"}]
        sql = iy.to_sql(items, "タイトル'つき", "", "correct")
        self.assertIn("It''s ok", sql)
        self.assertIn("a''b", sql)
        self.assertIn("タイトル''つき", sql)

    def test_is_open_false_and_transaction(self):
        items = [{"seq": 1, "prompt": "p", "choice_a": "A", "choice_b": "B", "correct": "b"}]
        sql = iy.to_sql(items, "T", "L", "correct")
        self.assertIn("is_open", sql)
        self.assertIn("false", sql, "取り込んだ直後に学生へ見せない")
        self.assertTrue(sql.strip().startswith("--"))
        self.assertIn("begin;", sql)
        self.assertIn("commit;", sql)

    def test_answer_column_is_configurable(self):
        items = [{"seq": 1, "prompt": "p", "choice_a": "A", "choice_b": "B", "correct": "a"}]
        self.assertIn("question_answers(question_id, answer)",
                      iy.to_sql(items, "T", "", "answer"))


class EndToEndTest(unittest.TestCase):
    def test_cp932_and_utf8_both_load(self):
        for enc in ("cp932", "utf-8"):
            with tempfile.TemporaryDirectory() as d:
                dp = Path(d)
                q = write_csv(dp, "q.csv", QHEAD,
                              [qrow("1", '<span style="color:#e74c3c;">（　）</span>です<br />A：はい')], enc)
                a = write_csv(dp, "a.csv", AHEAD, [arow("1", "0", "いいえ"), arow("1", "1", "はい")], enc)
                out_json, out_sql = dp / "o.json", dp / "o.sql"
                rc = iy.main(["--questions", str(q), "--answers", str(a),
                              "--out-json", str(out_json), "--out-sql", str(out_sql)])
                self.assertEqual(rc, 0, f"{enc} で警告なしに通ること")
                self.assertTrue(out_json.exists() and out_sql.exists())
                body = out_json.read_text(encoding="utf-8")
                self.assertIn("（　）です\\nA：はい", body, "brが改行になってJSONに入る")
                self.assertNotIn("<span", body)

    def test_title_falls_back_to_category_leaf(self):
        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            q = write_csv(dp, "q.csv", QHEAD, [qrow("1", "文", cat=r"全体\総合\★つなぐ")])
            a = write_csv(dp, "a.csv", AHEAD, [arow("1", "1", "A"), arow("1", "0", "B")])
            out = dp / "o.json"
            iy.main(["--questions", str(q), "--answers", str(a), "--out-json", str(out)])
            self.assertIn('"title": "★つなぐ"', out.read_text(encoding="utf-8"))

    def test_returns_nonzero_when_something_needs_attention(self):
        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            q = write_csv(dp, "q.csv", QHEAD, [qrow("1", "文")])
            a = write_csv(dp, "a.csv", AHEAD, [arow("1", "1", "A")])   # 選択肢1つ＝不正
            self.assertEqual(iy.main(["--questions", str(q), "--answers", str(a)]), 1,
                             "黙って成功を返さない")


if __name__ == "__main__":
    unittest.main(verbosity=2)
