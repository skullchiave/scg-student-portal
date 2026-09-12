#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/import_fmt_bulk.py ——「どのシートを入れて、どれを入れないか」の検査。

★このファイルの存在理由。
  2026-09-11 に、本物の設問 1,846問を初めて DB へ入れるとき、**同じ日に2回**
  「入れるべきものを捨てる」判定を書いた。どちらも1回目は例外も出さず静かに通った:

    ① lesson_key を「丸数字を落として最初の数字を拾う」にした
       → `1-①` `1-②` `1-③`（同じ課の**別のテスト**）を重複と誤判定。
         教材によって丸数字の意味が逆だったのが原因（まとめテストは①＝通し番号、
         文法チェックは①＝その課の何枚目）。1,846問中 1,647問を捨てるところだった。

    ② 「全体」シートを「他シートの寄せ集めだから捨てる」と判定
       → 現物を照合したら重なりは9%で、**全体にしかない問題が 398+289 問**あった。
         最初の照合で0%と出たのは全体シートが1列ずれていたため（生の列で読むと合わない）。
         687問を捨てるところだった。

  どちらも「出力を見ても気づけない」型＝件数が減っても、減ったこと自体が正常に見える。
  だから**期待する枚数・問数を数字で固定する**。ここが動いたら、必ず人が理由を確かめること。

DB には触らない。Excel も読まない（判定ロジックだけを見る）。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import import_fmt_bulk as B  # noqa: E402


def sheet(file: str, name: str, n: int = 10) -> dict:
    return {"file": file, "sheet": name, "questions": n}


class TestLessonKey(unittest.TestCase):
    """新旧の重複を見つける鍵。ここを緩めると別のテストを取り違える。"""

    def test_newer_mark_is_ignored(self):
        self.assertEqual(B.lesson_key("①1-3"), B.lesson_key("①1-3 （新）"))

    def test_whitespace_is_ignored(self):
        self.assertEqual(B.lesson_key("2-① "), B.lesson_key("2-①"))
        self.assertEqual(B.lesson_key("2-①"), B.lesson_key("2-　①"))

    def test_maru_number_is_significant(self):
        """🔴 1度ここを間違えた。丸数字は落としてはいけない。

        `1-①` `1-②` `1-③` は同じ課の**別のテスト**。同一視すると2枚が捨てられる。
        """
        keys = {B.lesson_key(x) for x in ("1-①", "1-②", "1-③")}
        self.assertEqual(len(keys), 3, "同じ課の別テストが同一視されている")

    def test_different_lessons_differ(self):
        self.assertNotEqual(B.lesson_key("16-①"), B.lesson_key("17-①"))
        self.assertNotEqual(B.lesson_key("①1-3"), B.lesson_key("②4-6"))


class TestDecide(unittest.TestCase):
    F = "001.つなぐ日本語初級\\x.xlsx"

    def keeps(self, decisions):
        return {d.sheet for d in decisions if d.keep}

    def drops(self, decisions):
        return {d.sheet: d.reason for d in decisions if not d.keep}

    def test_old_version_is_dropped_and_new_kept(self):
        d = B.decide([sheet(self.F, "①1-3", 20), sheet(self.F, "①1-3 （新）", 20)])
        self.assertEqual(self.keeps(d), {"①1-3 （新）"})
        self.assertIn("①1-3", self.drops(d))

    def test_sibling_tests_all_kept(self):
        """🔴 回帰①：同じ課の別テストは全部入る。"""
        names = ["1-①", "1-②", "1-③", "2-① ", "2-②", "2-③"]
        d = B.decide([sheet(self.F, n) for n in names])
        self.assertEqual(len(self.keeps(d)), len(names), f"捨てられた: {self.drops(d)}")

    def test_aggregate_sheet_is_kept(self):
        """🔴 回帰②：「全体」は捨てない。寄せ集めではなく別の問題集だった。"""
        d = B.decide([sheet(self.F, "全体", 440), sheet(self.F, "1-①", 10)])
        self.assertIn("全体", self.keeps(d), "「全体」を捨ててはいけない（687問を失う）")

    def test_ruby_off_is_dropped(self):
        for name in ("第1課 ルビなし", "第1課 ルビなし版", "第1課 ルビふり前", "第1課 ルビ振り前"):
            with self.subTest(name=name):
                d = B.decide([sheet(self.F, name)])
                self.assertEqual(self.keeps(d), set(), f"{name} は入れない")

    def test_ruby_on_is_kept(self):
        for name in ("第1課 ルビあり", "第1課 ルビふり版", "第1課 ルビふり後"):
            with self.subTest(name=name):
                d = B.decide([sheet(self.F, name)])
                self.assertEqual(self.keeps(d), {name}, f"{name} は入れる")

    def test_empty_sheet_is_dropped(self):
        d = B.decide([sheet(self.F, "からっぽ", 0)])
        self.assertEqual(self.keeps(d), set())

    def test_template_is_dropped(self):
        d = B.decide([sheet(self.F, "課題登録FMT", 5)])
        self.assertEqual(self.keeps(d), set())

    def test_ambiguous_duplicate_stops_instead_of_guessing(self):
        """どちらが新しいか決められないときは、黙って選ばずに人へ投げる。"""
        d = B.decide([sheet(self.F, "①1-3 （新）", 20), sheet(self.F, "①1-3 (新)", 20)])
        reasons = list(self.drops(d).values())
        self.assertTrue(any(r.startswith("🔴") for r in reasons),
                        "決められないときは🔴で止めること")

    def test_every_decision_has_a_reason(self):
        """黙って捨てない＝落とすものには必ず理由がある。"""
        d = B.decide([sheet(self.F, "全体", 440), sheet(self.F, "1-①"),
                      sheet(self.F, "からっぽ", 0), sheet(self.F, "第1課 ルビなし")])
        for x in d:
            if not x.keep:
                self.assertTrue(x.reason.strip(), f"{x.sheet} に理由が無い")


class TestTsunaguCounts(unittest.TestCase):
    """★実物の教材に対する期待値。ここが動いたら必ず人が理由を確かめること。

    audit_fmt.py が書いた tmp/教材の不備一覧.json を読む。
    JSON が無い環境（会社PC・CI）では skip する＝落とさない。
    """

    AUDIT = REPO / "tmp" / "教材の不備一覧.json"
    BOOK = "001.つなぐ日本語初級"

    @classmethod
    def setUpClass(cls):
        if not cls.AUDIT.exists():
            raise unittest.SkipTest("tmp/教材の不備一覧.json が無い（audit_fmt.py を先に回す）")

    def test_counts_match_what_we_decided_to_import(self):
        audit = B.load_audit(self.AUDIT)
        byfile = B.walk(audit, self.BOOK)
        dec = []
        for _, sheets in sorted(byfile.items()):
            dec += B.decide(sheets)
        keep = [d for d in dec if d.keep]
        drop = [d for d in dec if not d.keep]

        self.assertEqual(len(byfile), 4, "つなぐ日本語初級で設問のあるExcelは4本")
        self.assertEqual(len(keep), 101, f"入れるシート数が変わった（除外: "
                                         f"{[(d.sheet, d.reason) for d in drop]}）")
        self.assertEqual(sum(d.questions for d in keep), 1826, "入れる問数が変わった")
        self.assertEqual(len(drop), 1, "除外は「①1-3（旧版）」の1枚だけのはず")
        self.assertEqual(drop[0].sheet, "①1-3")

    def test_nothing_is_blocked(self):
        """🔴 で止まるもの（人が決めるまで進めないもの）が無いこと。"""
        audit = B.load_audit(self.AUDIT)
        dec = []
        for _, sheets in sorted(B.walk(audit, self.BOOK).items()):
            dec += B.decide(sheets)
        blocked = [d for d in dec if not d.keep and d.reason.startswith("🔴")]
        self.assertEqual(blocked, [], f"人の判断待ちが残っている: "
                                      f"{[(d.sheet, d.reason) for d in blocked]}")


class TestOutStem(unittest.TestCase):
    """出力ファイル名。**元の相対パスと1対1**でないと、黙って上書きされる。

    ★2026-09-11 に実際に起きた。文字クラスにローマ数字（Ⅰ Ⅱ）が入っておらず、
      「文法チェックテストⅠ.xlsx」と「…Ⅱ.xlsx」が同じ出力名になり、
      **Ⅰの結果（440問ぶん）がⅡに上書きされた**。例外も警告も出ない。
    """

    def test_roman_numerals_do_not_collide(self):
        a = B.out_stem(r"001.つなぐ日本語初級\毎日のチェックテスト\Ⅰ\★ヨリソル_文法チェックテストⅠ.xlsx")
        b = B.out_stem(r"001.つなぐ日本語初級\毎日のチェックテスト\Ⅱ\★ヨリソル_文法チェックテストⅡ.xlsx")
        self.assertNotEqual(a, b, "Ⅰ と Ⅱ が同じ出力名になっている（上書き事故）")

    def test_same_filename_in_different_folders_do_not_collide(self):
        a = B.out_stem(r"001.つなぐ日本語初級\Ⅰ\同じ名前.xlsx")
        b = B.out_stem(r"001.つなぐ日本語初級\Ⅱ\同じ名前.xlsx")
        self.assertNotEqual(a, b, "同名ファイルが別フォルダにあると衝突する")

    def test_stable_for_the_same_path(self):
        p = r"001.つなぐ日本語初級\まとめテスト\Ⅰ\★ヨリソル_まとめテストⅠ（作成用）.xlsx"
        self.assertEqual(B.out_stem(p), B.out_stem(p), "同じ入力で名前が揺れる")

    def test_all_tsunagu_files_get_distinct_names(self):
        rels = [
            r"001.つなぐ日本語初級\まとめテスト\Ⅰ\★ヨリソル_まとめテストⅠ（作成用）.xlsx",
            r"001.つなぐ日本語初級\まとめテスト\Ⅱ\★JapanGo_まとめテストⅡ（作成用）.xlsx",
            r"001.つなぐ日本語初級\毎日のチェックテスト\Ⅰ\★ヨリソル_文法チェックテストⅠ.xlsx",
            r"001.つなぐ日本語初級\毎日のチェックテスト\Ⅱ\★ヨリソル_文法チェックテストⅡ.xlsx",
        ]
        self.assertEqual(len({B.out_stem(r) for r in rels}), len(rels))


class TestTitlePrefix(unittest.TestCase):
    """一覧に出す見出し。87件（いずれ437件）が名前だけで見分けられること。"""

    def test_vendor_and_markers_are_stripped(self):
        self.assertEqual(
            B.title_prefix_of(r"a\b\★ヨリソル_文法チェックテストⅠ.xlsx"), "文法チェックテストⅠ")
        self.assertEqual(
            B.title_prefix_of(r"a\b\★JapanGo_まとめテストⅡ（作成用）.xlsx"), "まとめテストⅡ")

    def test_no_private_words_leak_to_the_screen(self):
        """業者名・作り手の符丁は先生の画面に出さない。"""
        for rel in (r"a\★ヨリソル_文法チェックテストⅠ.xlsx",
                    r"a\★JapanGo_まとめテストⅡ（作成用）.xlsx"):
            got = B.title_prefix_of(rel)
            for bad in ("ヨリソル", "JapanGo", "★", "作成用"):
                self.assertNotIn(bad, got, f"{bad} が見出しに残っている: {got}")

    def test_different_files_give_different_prefixes(self):
        a = B.title_prefix_of(r"a\Ⅰ\★ヨリソル_文法チェックテストⅠ.xlsx")
        b = B.title_prefix_of(r"a\Ⅱ\★ヨリソル_文法チェックテストⅡ.xlsx")
        self.assertNotEqual(a, b)


class TestContentDedup(unittest.TestCase):
    """中身を読んで見つける重複。名前の照合では絶対に見つからない型。

    ★実物で見つかった: 文法チェックテストⅡ の `26-②`〜`30-②` の14枚が
      `24-③` と1問たがわず同じだった＝第26〜30課ぶんはまだ書かれていない。
      そのまま入れると「27-①」という名前で第24課の問題が配られる。
      **名前は正しく見えるので、画面を見ても気づけない。**

    教材フォルダが無い環境では skip する（会社PC・CI では落とさない）。
    """

    AUDIT = REPO / "tmp" / "教材の不備一覧.json"
    BOOK = "001.つなぐ日本語初級"

    @classmethod
    def setUpClass(cls):
        if not cls.AUDIT.exists():
            raise unittest.SkipTest("tmp/教材の不備一覧.json が無い")
        if not B.DEFAULT_BASE.exists():
            raise unittest.SkipTest("教材フォルダが見えない環境")

    def decisions(self):
        audit = B.load_audit(self.AUDIT)
        dec = []
        for _, sheets in sorted(B.walk(audit, self.BOOK).items()):
            dec += B.decide(sheets)
        return B.content_dedup(B.DEFAULT_BASE, dec)

    def test_identical_sheets_collapse_to_one(self):
        dec = self.decisions()
        keep = [d for d in dec if d.keep]
        drop = [d for d in dec if not d.keep]

        self.assertEqual(len(keep), 87, "中身の重複を落としたあとのシート数が変わった")
        self.assertEqual(sum(d.questions for d in keep), 1686, "入れる問数が変わった")

        same = [d for d in drop if "1問たがわず同じ" in d.reason]
        self.assertEqual(len(same), 14, "24-③ と同じ14枚が落ちるはず")
        self.assertEqual({d.sheet for d in same},
                         {"26-②", "26-③", "27-①", "27-②", "27-③", "27-④",
                          "28-①", "28-②", "28-③", "29-①", "29-②", "29-③",
                          "30-①", "30-②"})

    def test_the_original_is_kept(self):
        """重複を落とすとき、元の1枚は必ず残ること（全部消したら本末転倒）。"""
        keep = {d.sheet for d in self.decisions() if d.keep}
        self.assertIn("24-③", keep, "重複の元になった1枚が消えている")
        self.assertIn("26-①", keep, "26-① は中身が違うので残るはず")

    def test_unreadable_sheets_are_not_silently_dropped(self):
        """読めなかったシートを「読めないから」で捨てない＝静かに消える側を作らない。"""
        import inspect
        src = inspect.getsource(B.content_dedup)
        self.assertIn("unreadable", src)
        self.assertIn("out = list(rest) + unreadable", src,
                      "読めなかったものが結果に残っていない")


if __name__ == "__main__":
    unittest.main(verbosity=2)
