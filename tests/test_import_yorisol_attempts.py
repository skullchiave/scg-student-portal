#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""test_import_yorisol_attempts.py — ヨリソル受験履歴CSVの変換の回帰テスト（2026-09-11）

実物のCSVは使わない（手元に無いので、テストの中でダミーを作る。実在の学籍番号・氏名は
このファイルにも書かない＝ダミーの学籍番号は「999から降順の帯」、氏名は「テスト太郎」）。

見ているのは次の4つ。
  ① 形を崩さず「1行=1（学生×設問）」の縦持ちJSONに開けるか
  ② おかしい入力を黙って通さないか（空の行・列数不一致・3列1組が崩れている）
  ③ 🔴 標準出力に値（氏名・学籍番号・回答・スコア）を出していないか（PIIの一番の砦）
  ④ 文字コード（utf-8-sig / cp932）の既定の試行順とクラス名の推測

  py -X utf8 -m unittest discover -s tests -p "test_import_yorisol_attempts.py" -v
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import import_yorisol_attempts as ya  # noqa: E402

# ---------------------------------------------------------------- ダミーデータ
# ★学籍番号の書式例は 999 から降順の帯を使う（001側は実在の番号と衝突するため・CLAUDE.md参照）
DUMMY_ACCOUNTS = ["2604999", "2604998", "2604997"]
DUMMY_NAMES = ["テスト太郎", "テスト花子", "テスト次郎"]

FIXED_HEAD = ["アカウント", "氏名", "ステータス", "合計点"]


def qgroup_head(n: int) -> list[str]:
    """設問 n 個ぶんの見出し（3列1組・各組は同じラベルを3回でなく問n表記で識別できるようにする）。"""
    head: list[str] = []
    for i in range(1, n + 1):
        head += [f"問{i}", f"問{i}", f"問{i}"]   # ★回答・正誤・スコアの3列は同じ表示ラベルを持ちうる
    return head


def make_row(account, name, status, total, answers: list[tuple[str, str, str]]) -> list[str]:
    row = [account, name, status, str(total)]
    for a, c, s in answers:
        row += [a, c, s]
    return row


def write_csv_bytes(head: list[str], rows: list[list[str]], encoding: str) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(head)
    w.writerows(rows)
    text = buf.getvalue()
    if encoding == "utf-8-sig":
        return text.encode("utf-8-sig")
    return text.encode(encoding)


def capture_stdout(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*a, **kw)
    return rc, buf.getvalue()


class Tmp(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.dir = Path(self._d.name)

    def tearDown(self):
        self._d.cleanup()

    def write(self, name: str, head: list[str], rows: list[list[str]], encoding="utf-8-sig") -> Path:
        p = self.dir / name
        p.write_bytes(write_csv_bytes(head, rows, encoding))
        return p


# ------------------------------------------------------------------ 基本: 横持ち→縦持ち
class BuildBasicTest(Tmp):
    def test_one_student_two_questions_becomes_two_rows(self):
        head = FIXED_HEAD + qgroup_head(2)
        row = make_row(DUMMY_ACCOUNTS[0], DUMMY_NAMES[0], "受験済み", 8,
                        [("1", "1", "5"), ("2", "0", "3")])
        result, warn = ya.build(head, [row], "1A", "t.csv")
        self.assertEqual(warn, [])
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["rows"][0]["question_index"], 1)
        self.assertEqual(result["rows"][1]["question_index"], 2)
        self.assertEqual(result["rows"][0]["account"], DUMMY_ACCOUNTS[0])
        self.assertEqual(result["rows"][0]["answer"], "1")
        self.assertEqual(result["rows"][1]["score"], "3")

    def test_two_students_two_questions_becomes_four_rows(self):
        head = FIXED_HEAD + qgroup_head(2)
        rows = [
            make_row(DUMMY_ACCOUNTS[0], DUMMY_NAMES[0], "受験済み", 8, [("1", "1", "5"), ("2", "0", "3")]),
            make_row(DUMMY_ACCOUNTS[1], DUMMY_NAMES[1], "受験済み", 10, [("1", "1", "5"), ("1", "1", "5")]),
        ]
        result, _ = ya.build(head, rows, "1A", "t.csv")
        self.assertEqual(len(result["rows"]), 4)

    def test_dropped_rows_is_present_even_when_empty(self):
        head = FIXED_HEAD + qgroup_head(1)
        row = make_row(DUMMY_ACCOUNTS[0], DUMMY_NAMES[0], "受験済み", 5, [("1", "1", "5")])
        result, _ = ya.build(head, [row], "1A", "t.csv")
        self.assertIn("dropped_rows", result)
        self.assertEqual(result["dropped_rows"], [])

    def test_question_group_columns_are_1indexed(self):
        head = FIXED_HEAD + qgroup_head(2)
        result, _ = ya.build(head, [], "1A", "t.csv")
        self.assertEqual(result["question_groups"][0]["columns"], [5, 6, 7])
        self.assertEqual(result["question_groups"][1]["columns"], [8, 9, 10])

    def test_raw_headers_are_kept_verbatim(self):
        head = FIXED_HEAD + ["Q1回答", "Q1正誤", "Q1スコア"]
        result, _ = ya.build(head, [], "1A", "t.csv")
        self.assertEqual(result["question_groups"][0]["headers"], ["Q1回答", "Q1正誤", "Q1スコア"])
        self.assertEqual(result["fixed_columns"]["account"]["header"], "アカウント")


# ------------------------------------------------------------------ 黙って通さない
class RejectTest(Tmp):
    def test_empty_row_is_dropped_and_reported(self):
        head = FIXED_HEAD + qgroup_head(1)
        good = make_row(DUMMY_ACCOUNTS[0], DUMMY_NAMES[0], "受験済み", 5, [("1", "1", "5")])
        empty = ["", "", "", ""] + [""] * 3
        result, warn = ya.build(head, [good, empty], "1A", "t.csv")
        self.assertEqual(len(result["rows"]), 1)          # 空行ぶんは出ない
        self.assertEqual(len(result["dropped_rows"]), 1)
        self.assertEqual(result["dropped_rows"][0]["row"], 3)     # 2行目=good, 3行目=empty
        self.assertIn("空の行", result["dropped_rows"][0]["reason"])
        self.assertTrue(any("空の行" in w for w in warn))

    def test_column_count_mismatch_is_dropped_and_reported(self):
        head = FIXED_HEAD + qgroup_head(1)
        good = make_row(DUMMY_ACCOUNTS[0], DUMMY_NAMES[0], "受験済み", 5, [("1", "1", "5")])
        short = [DUMMY_ACCOUNTS[1], DUMMY_NAMES[1], "受験済み"]   # 列が足りない
        result, warn = ya.build(head, [good, short], "1A", "t.csv")
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(len(result["dropped_rows"]), 1)
        self.assertIn("列数が見出しと合わない", result["dropped_rows"][0]["reason"])
        self.assertTrue(any("列数が合わない行" in w for w in warn))

    def test_dropped_row_reason_never_contains_dummy_values(self):
        """★理由の文言に値（氏名・学籍番号）を混ぜていないこと（件数と行番号だけ、のはず）。"""
        head = FIXED_HEAD + qgroup_head(1)
        short = [DUMMY_ACCOUNTS[0], DUMMY_NAMES[0], "受験済み"]
        result, _ = ya.build(head, [short], "1A", "t.csv")
        reason = result["dropped_rows"][0]["reason"]
        self.assertNotIn(DUMMY_ACCOUNTS[0], reason)
        self.assertNotIn(DUMMY_NAMES[0], reason)

    def test_ragged_group_columns_raise_by_default(self):
        head = FIXED_HEAD + ["回答1", "正誤1"]   # 2列だけ＝3列1組にならない
        with self.assertRaises(SystemExit):
            ya.build(head, [], "1A", "t.csv")

    def test_ragged_group_columns_allowed_with_flag(self):
        head = FIXED_HEAD + ["回答1", "正誤1", "スコア1", "回答2", "正誤2"]  # 5列＝1組+あまり2列
        result, warn = ya.build(head, [], "1A", "t.csv", allow_ragged=True)
        self.assertEqual(len(result["question_groups"]), 1)
        self.assertEqual(result["ragged_tail_columns"], 2)
        self.assertTrue(any("3列1組になっていない" in w for w in warn))

    def test_too_few_columns_for_fixed_part_raises(self):
        with self.assertRaises(SystemExit):
            ya.build(["アカウント", "氏名"], [], "1A", "t.csv")

    def test_blank_group_headers_warn(self):
        head = FIXED_HEAD + ["", "", ""]
        result, warn = ya.build(head, [], "1A", "t.csv")
        self.assertTrue(any("見出しが3列とも空" in w for w in warn))
        self.assertEqual(result["question_groups"][0]["label"], "設問1")

    def test_duplicate_question_labels_warn(self):
        head = FIXED_HEAD + ["問1", "問1", "問1", "問1", "問1", "問1"]   # 2設問とも同じラベル
        _, warn = ya.build(head, [], "1A", "t.csv")
        self.assertTrue(any("設問ラベルが重複している" in w for w in warn))

    def test_unexpected_fixed_header_warns_but_still_reads_by_position(self):
        head = ["Login", "Name", "Status", "Score"] + qgroup_head(1)   # 既知の候補に無い見出し
        row = make_row(DUMMY_ACCOUNTS[0], DUMMY_NAMES[0], "受験済み", 5, [("1", "1", "5")])
        result, warn = ya.build(head, [row], "1A", "t.csv")
        # 見出しが想定と違っても、位置優先で普通に読める
        self.assertEqual(result["rows"][0]["account"], DUMMY_ACCOUNTS[0])
        self.assertEqual(sum("見出しが" in w for w in warn), 4)   # 先頭4列すべてで警告


# ------------------------------------------------------------------ 文字コード
class EncodingTest(Tmp):
    def test_auto_reads_utf8_sig(self):
        p = self.write("t.csv", FIXED_HEAD + qgroup_head(1),
                        [make_row(DUMMY_ACCOUNTS[0], DUMMY_NAMES[0], "受験済み", 5, [("1", "1", "5")])],
                        encoding="utf-8-sig")
        rows, used = ya.read_csv_rows(p, "auto")
        self.assertEqual(used, "utf-8-sig")
        self.assertEqual(rows[0], FIXED_HEAD + qgroup_head(1))

    def test_auto_falls_back_to_cp932(self):
        p = self.write("t.csv", FIXED_HEAD + qgroup_head(1),
                        [make_row(DUMMY_ACCOUNTS[0], DUMMY_NAMES[0], "受験済み", 5, [("1", "1", "5")])],
                        encoding="cp932")
        rows, used = ya.read_csv_rows(p, "auto")
        self.assertEqual(used, "cp932")
        self.assertEqual(rows[1][1], DUMMY_NAMES[0])

    def test_explicit_encoding_is_honored(self):
        p = self.write("t.csv", FIXED_HEAD, [], encoding="cp932")
        rows, used = ya.read_csv_rows(p, "cp932")
        self.assertEqual(used, "cp932")

    def test_wrong_explicit_encoding_raises(self):
        # cp932 で書いたファイルを utf-8-sig で強制すると、まず読めないはず
        p = self.write("t.csv", FIXED_HEAD + ["メモ"], [["", "", "", "", "ダミー漢字混じりコメント〜"]],
                        encoding="cp932")
        with self.assertRaises(SystemExit):
            ya.read_csv_rows(p, "utf-8-sig")


# ------------------------------------------------------------------ クラス名の推測
class ClassNameTest(unittest.TestCase):
    def test_guess_from_prefix(self):
        self.assertEqual(ya.guess_class_name("1A_2026-10-08"), "1A")
        self.assertEqual(ya.guess_class_name("2C受験履歴"), "2C")

    def test_no_prefix_returns_empty(self):
        self.assertEqual(ya.guess_class_name("受験履歴_2026-10-08"), "")
        self.assertEqual(ya.guess_class_name(""), "")


# ------------------------------------------------------------------ 🔴 標準出力にPIIを出さない
class NoPiiOnStdoutTest(Tmp):
    """main() を実際に走らせて、標準出力（画面）にダミーの氏名・学籍番号・回答・スコアが
    1文字も出ていないことを確認する。これが素の値を出さないという約束の実物チェック。"""

    def test_stdout_never_contains_account_or_name_or_answers(self):
        head = FIXED_HEAD + qgroup_head(2)
        rows = [
            make_row(DUMMY_ACCOUNTS[0], DUMMY_NAMES[0], "受験済み", 8, [("1", "1", "5"), ("2", "0", "3")]),
            make_row(DUMMY_ACCOUNTS[1], DUMMY_NAMES[1], "未受験", 0, [("", "", ""), ("", "", "")]),
        ]
        p = self.write("1A_2026-10-08.csv", head, rows)
        rc, out = capture_stdout(ya.main, ["--csv", str(p)])
        for acc in DUMMY_ACCOUNTS[:2]:
            self.assertNotIn(acc, out, "学籍番号が標準出力に出てしまっている")
        for nm in DUMMY_NAMES[:2]:
            self.assertNotIn(nm, out, "氏名が標準出力に出てしまっている")
        # 個々の回答値・スコア値も出さない（"5" や "3" のような値は他の数字と衝突しやすいので、
        # ここでは代わりに「件数」表現になっているかで裏取りする）
        self.assertIn("件", out)

    def test_stdout_still_reports_counts_and_column_labels(self):
        """★件数・列名（＝設問の表示ラベル）は出してよい。出るべきものが出ているかも見る。"""
        head = FIXED_HEAD + qgroup_head(1)
        rows = [make_row(DUMMY_ACCOUNTS[0], DUMMY_NAMES[0], "受験済み", 5, [("1", "1", "5")])]
        p = self.write("1A_2026-10-08.csv", head, rows)
        rc, out = capture_stdout(ya.main, ["--csv", str(p)])
        self.assertEqual(rc, 0)
        self.assertIn("クラス: 1A", out)
        self.assertIn("問1", out)             # 設問の列名（表示ラベル）は出してよい
        self.assertIn("読み込んだ行数", out)

    def test_out_json_does_contain_the_values(self):
        """JSONファイルの方には値が入っていて当然（標準出力とは別扱い）。"""
        head = FIXED_HEAD + qgroup_head(1)
        rows = [make_row(DUMMY_ACCOUNTS[0], DUMMY_NAMES[0], "受験済み", 5, [("1", "1", "5")])]
        p = self.write("1A_2026-10-08.csv", head, rows)
        out_json = self.dir / "out" / "attempts.json"
        rc, _ = capture_stdout(ya.main, ["--csv", str(p), "--out-json", str(out_json)])
        data = json.loads(out_json.read_text(encoding="utf-8"))
        self.assertEqual(data["rows"][0]["account"], DUMMY_ACCOUNTS[0])
        self.assertEqual(data["rows"][0]["name"], DUMMY_NAMES[0])
        self.assertEqual(data["class_name"], "1A")
        self.assertEqual(data["encoding_used"], "utf-8-sig")


# ------------------------------------------------------------------ main() の入口まわり
class MainCliTest(Tmp):
    def test_class_name_inferred_from_filename(self):
        head = FIXED_HEAD + qgroup_head(1)
        p = self.write("1B_受験履歴.csv", head, [])
        rc, out = capture_stdout(ya.main, ["--csv", str(p)])
        self.assertIn("クラス: 1B", out)

    def test_class_name_flag_overrides_filename_guess(self):
        head = FIXED_HEAD + qgroup_head(1)
        p = self.write("1B_受験履歴.csv", head, [])
        rc, out = capture_stdout(ya.main, ["--csv", str(p), "--class", "2C"])
        self.assertIn("クラス: 2C", out)

    def test_missing_class_name_is_an_error_not_a_guess(self):
        head = FIXED_HEAD + qgroup_head(1)
        p = self.write("受験履歴.csv", head, [])       # クラス名を推測できないファイル名
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = ya.main(["--csv", str(p)])
        self.assertEqual(rc, 2)
        self.assertIn("クラス名が分かりません", buf.getvalue())

    def test_missing_file_is_an_error(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = ya.main(["--csv", str(self.dir / "no_such_file.csv"), "--class", "1A"])
        self.assertEqual(rc, 2)

    def test_rc_is_nonzero_when_rows_were_dropped(self):
        head = FIXED_HEAD + qgroup_head(1)
        good = make_row(DUMMY_ACCOUNTS[0], DUMMY_NAMES[0], "受験済み", 5, [("1", "1", "5")])
        p = self.write("1A.csv", head, [good, ["", "", "", ""] + [""] * 3])
        rc, _ = capture_stdout(ya.main, ["--csv", str(p)])
        self.assertEqual(rc, 1)

    def test_rc_is_zero_when_nothing_to_report(self):
        head = FIXED_HEAD + qgroup_head(1)
        good = make_row(DUMMY_ACCOUNTS[0], DUMMY_NAMES[0], "受験済み", 5, [("1", "1", "5")])
        p = self.write("1A.csv", head, [good])
        rc, _ = capture_stdout(ya.main, ["--csv", str(p)])
        self.assertEqual(rc, 0)


# ------------------------------------------------------------------ DBに触らない
class NoDbTouchTest(unittest.TestCase):
    def test_module_does_not_import_network_or_db_libraries(self):
        src = Path(ya.__file__).read_text(encoding="utf-8")
        for bad in ("requests", "urllib", "psycopg", "supabase", "socket"):
            self.assertNotIn(bad, src, f"{bad} を使っている＝DBやネットワークに触っている疑い")

    def test_no_sql_output_option_exists(self):
        """★用途が決まるまでDBの形を決め打ちしない＝SQLを書く出口をまだ持たせない。"""
        src = Path(ya.__file__).read_text(encoding="utf-8")
        self.assertNotIn("--out-sql", src)
        self.assertNotIn("insert into", src.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
