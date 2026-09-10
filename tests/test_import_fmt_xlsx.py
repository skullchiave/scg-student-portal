#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""test_import_fmt_xlsx.py — 課題登録FMT（Excel）の変換の回帰テスト（2026-09-10）

実物の Excel は使わない（手元に無いPCでも走るように、テストの中で作る）。
見ているのは次の3つ。

  ① 形を崩さずポータルの3テーブルに落ちるか
  ② おかしい入力を**黙って通さない**か（選択肢の飛び・解答の範囲外・空の問題文）
  ③ 落としたものを**黙って捨てない**か（「集計」行・画像つきの設問）

★とくに「見出しに頼らず列の位置で読む」ことを固定する。実データでは
  「④10-12」シートだけ見出しが書き換わっていた。見出しで読む作りに戻すと、
  そのシートだけ静かに壊れるため。

  py -X utf8 -m unittest discover -s tests -p "test_import_fmt_xlsx.py" -v
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import import_fmt_xlsx as fx  # noqa: E402

HEAD = ["問題番号", "問題文1", "問題文2", "添付ファイル名",
        "選択肢1", "選択肢2", "選択肢3", "選択肢4", "選択肢5",
        "解説", "解答", "カテゴリ", "配点"]


def qrow(no, t2="つぎの ぶんを えらんで ください", choices=("あ", "い", "う"), ans=1,
         t1="", image="", explain="", cat="文法", points=5):
    """FMT 1行ぶん（13列）。choices は 選択肢1〜5 の順に詰める。"""
    ch = list(choices) + [""] * (5 - len(choices))
    return [no, t1, t2, image, *ch, explain, ans, cat, points]


def make_book(path: Path, sheets: dict, head=None):
    """sheets = {シート名: [行, 行, ...]} で Excel を作る。"""
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        ws.append(list(head or HEAD))
        for r in rows:
            ws.append(list(r))
    wb.save(path)
    return path


class Tmp(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.dir = Path(self._d.name)

    def tearDown(self):
        self._d.cleanup()

    def book(self, sheets, head=None):
        return make_book(self.dir / "t.xlsx", sheets, head)

    def build(self, sheets, head=None, **kw):
        kw.setdefault("only", None)
        kw.setdefault("exclude", None)
        kw.setdefault("prefix", "")
        kw.setdefault("include_template", False)
        return fx.build(self.book(sheets, head), **kw)


# ------------------------------------------------------------------ 基本
class BasicTest(Tmp):
    def test_one_question_becomes_three_tables(self):
        sets, warn = self.build({"①1-3": [qrow(1, choices=("あ", "い", "う"), ans=2)]})
        self.assertEqual(len(sets), 1)
        q = sets[0]["questions"][0]
        self.assertEqual(q["seq"], 1)
        self.assertEqual(q["choices"], ["あ", "い", "う"])
        self.assertEqual(q["correct_idx"], 2)
        self.assertEqual(warn, [])

    def test_is_open_is_always_false(self):
        sets, _ = self.build({"①1-3": [qrow(1)]})
        self.assertIs(sets[0]["is_open"], False)

    def test_two_choices_ok(self):
        sets, warn = self.build({"①1-3": [qrow(1, choices=("あ", "い"), ans=2)]})
        self.assertEqual(sets[0]["questions"][0]["choices"], ["あ", "い"])
        self.assertEqual(warn, [])

    def test_five_choices_ok(self):
        sets, _ = self.build({"①1-3": [qrow(1, choices=tuple("あいうえお"), ans=5)]})
        self.assertEqual(len(sets[0]["questions"][0]["choices"]), 5)

    def test_zenkaku_answer_is_accepted(self):
        sets, warn = self.build({"①1-3": [qrow(1, ans="２")]})
        self.assertEqual(sets[0]["questions"][0]["correct_idx"], 2)
        self.assertEqual(warn, [])


# ------------------------------------------------------------------ 問題文
class PromptTest(Tmp):
    def test_text1_and_text2_joined_with_newline(self):
        sets, _ = self.build({"①1-3": [qrow(1, t1="つぎの ぶん", t2="ほんを＿＿。")]})
        self.assertEqual(sets[0]["questions"][0]["prompt"], "つぎの ぶん\nほんを＿＿。")

    def test_only_text2_is_fine(self):
        sets, warn = self.build({"①1-3": [qrow(1, t1="", t2="ほんを＿＿。")]})
        self.assertEqual(sets[0]["questions"][0]["prompt"], "ほんを＿＿。")
        self.assertEqual(warn, [])

    def test_only_text1_is_fine(self):
        sets, warn = self.build({"①1-3": [qrow(1, t1="ほんを＿＿。", t2="")]})
        self.assertEqual(sets[0]["questions"][0]["prompt"], "ほんを＿＿。")
        self.assertEqual(warn, [])

    def test_both_empty_is_dropped_with_warning(self):
        sets, warn = self.build({"①1-3": [qrow(1, t1="", t2=""), qrow(2)]})
        self.assertEqual(len(sets[0]["questions"]), 1)
        self.assertTrue(any("問題文1も問題文2も空" in w for w in warn))


# ------------------------------------------------------------------ 黙って通さない
class RejectTest(Tmp):
    def test_gap_in_choices_is_rejected(self):
        """選択肢1と3が埋まって2が空＝正解の番号とずれるので取り込まない。"""
        row = qrow(1)
        row[4], row[5], row[6] = "あ", "", "う"      # 選択肢1,2,3
        sets, warn = self.build({"①1-3": [row, qrow(2)]})
        self.assertEqual(len(sets[0]["questions"]), 1)
        self.assertTrue(any("飛んでいる" in w for w in warn))

    def test_answer_out_of_range_is_rejected(self):
        sets, warn = self.build({"①1-3": [qrow(1, choices=("あ", "い"), ans=3), qrow(2)]})
        self.assertEqual(len(sets[0]["questions"]), 1)
        self.assertTrue(any("選択肢は 2 個しかない" in w for w in warn))

    def test_answer_zero_is_rejected(self):
        sets, warn = self.build({"①1-3": [qrow(1, ans=0), qrow(2)]})
        self.assertEqual(len(sets[0]["questions"]), 1)
        self.assertTrue(any("解答が 0" in w for w in warn))

    def test_empty_answer_is_rejected(self):
        sets, warn = self.build({"①1-3": [qrow(1, ans=""), qrow(2)]})
        self.assertEqual(len(sets[0]["questions"]), 1)
        self.assertTrue(any("解答が空か、数字でない" in w for w in warn))

    def test_single_choice_is_rejected(self):
        sets, warn = self.build({"①1-3": [qrow(1, choices=("あ",), ans=1), qrow(2)]})
        self.assertEqual(len(sets[0]["questions"]), 1)
        self.assertTrue(any("選択肢が 1 個" in w for w in warn))

    def test_duplicate_seq_is_warned(self):
        sets, warn = self.build({"①1-3": [qrow(1), qrow(1)]})
        self.assertTrue(any("問題番号が重複" in w for w in warn))

    def test_duplicate_choice_is_kept_when_answer_is_outside(self):
        """実データの ⑩28-30 問3（選択肢2と3が同じ・正解は1）。
        出題はできるので取り込むが、問題として成立していないことは言う。"""
        sets, warn = self.build({"⑩28-30": [qrow(1, choices=("あ", "い", "い"), ans=1)]})
        self.assertEqual(len(sets[0]["questions"]), 1)
        self.assertTrue(any("選択肢が重複している" in w for w in warn))

    def test_duplicate_choice_is_dropped_when_answer_is_inside(self):
        """★同じものを選んでも片方しか正解にならない＝学生に不公平なので落とす。"""
        sets, _ = self.build({"⑩28-30": [qrow(1, choices=("あ", "い", "い"), ans=2), qrow(2)]})
        self.assertEqual([q["seq"] for q in sets[0]["questions"]], [2])
        self.assertIn("正解がその中にある", sets[0]["dropped"][0]["reason"])


# ------------------------------------------------------------------ 落としたものを JSON に残す
class DroppedTest(Tmp):
    def test_dropped_is_recorded_with_reason(self):
        sets, _ = self.build({"①1-3": [qrow(1), qrow(2, choices=("あ", "い"), ans=3)]})
        d = sets[0]["dropped"]
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["seq"], 2)
        self.assertIn("選択肢は 2 個", d[0]["reason"])

    def test_last_question_dropped_is_still_visible(self):
        """★実データ（⑩28-30 の問20）で起きた形。
        **最後の問題が落ちると番号の抜けにならない**ので、出来上がりを眺めても気づけない。
        dropped が唯一の手がかりになる。"""
        sets, _ = self.build({"⑩28-30": [qrow(1), qrow(2), qrow(3, choices=("あ", "い"), ans=3)]})
        self.assertEqual([q["seq"] for q in sets[0]["questions"]], [1, 2])   # 抜けが無いように見える
        self.assertEqual([x["seq"] for x in sets[0]["dropped"]], [3])        # ★でも記録は残る

    def test_dropped_is_empty_list_when_clean(self):
        """空でも [] を書く＝「無かった」ことの証拠になる（キーごと消さない）。"""
        sets, _ = self.build({"①1-3": [qrow(1)]})
        self.assertEqual(sets[0]["dropped"], [])

    def test_dropped_points_at_the_excel_row(self):
        sets, _ = self.build({"①1-3": [qrow(1, ans="")]})
        self.assertEqual(sets[0]["dropped"][0]["row"], 2)   # 見出しの次の行

    def test_all_dropped_sheet_is_kept_in_json(self):
        """★全問落ちたシートを捨てると、落とした理由ごと消える。回は残して記録を守る。"""
        sets, _ = self.build({"①1-3": [qrow(1, ans="")]})
        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0]["questions"], [])
        self.assertEqual(len(sets[0]["dropped"]), 1)

    def test_empty_set_makes_no_quiz_set_in_sql(self):
        """…ただし SQL には出さない。空の回が学生の一覧に並ぶため。"""
        sets, _ = self.build({"①1-3": [qrow(1, ans="")], "②4-6": [qrow(1)]})
        s = fx.to_sql(sets, "correct_idx")
        self.assertEqual(s.count("insert into quiz_sets"), 1)
        self.assertIn("-- 回 1 件", s)


# ------------------------------------------------------------------ 作りかけ と 別形式
class UnwrittenTest(Tmp):
    def test_number_only_row_is_counted_as_unwritten(self):
        """★実データの 929 行がこれ（スピードマスターは20問の枠に7問だけ）。
        「問題文が空」の不備として数えると、本物の不備が埋もれる。"""
        blank = [8, "", "", "", "", "", "", "", "", "", "", "", 1]   # 番号と配点だけ
        sets, warn = self.build({"ルビなし": [qrow(1), blank]})
        self.assertEqual(len(sets[0]["questions"]), 1)
        self.assertEqual(sets[0]["unwritten"], [8])
        self.assertEqual(sets[0]["dropped"], [])                    # ★不備には入れない
        self.assertTrue(any("作りかけ" in w for w in warn))

    def test_partially_written_row_is_a_real_problem(self):
        """中身が一部でもあるなら、それは書きかけではなく不備として扱う。"""
        sets, _ = self.build({"①1-3": [qrow(1, t1="", t2="", choices=("あ", "い"), ans=1)]})
        self.assertEqual(len(sets[0]["dropped"]), 1)
        self.assertEqual(sets[0]["unwritten"], [])

    def test_non_fmt_sheet_is_left_alone(self):
        """★実データの「漢字練習帳 中級編 7〜13回目一覧」＝10列版の一覧表。
        位置で読むと「選択肢が0個」が140件並ぶので、そもそも触らない。"""
        head = ["回（課）", "問題番号", "問題文1", "問題文2",
                "選択肢1", "選択肢2", "選択肢3", "選択肢4", "解答"]
        sets, warn = self.build({"シート1": [["中7", 1, "", "もんだい", "", "", "", "", ""]]}, head=head)
        self.assertEqual(sets[0]["questions"], [])
        self.assertIn("error", sets[0])
        self.assertTrue(any("課題登録FMT ではない" in w for w in warn))


# ------------------------------------------------------------------ 黙って捨てない
class KeepTest(Tmp):
    def test_summary_row_is_skipped_and_reported(self):
        """実データでは各シート22行目に「集計」がある。飛ばすが、飛ばしたことは言う。"""
        summary = ["集計", "", "", "", "", "", "", "", "", "", "", "", 100]
        sets, warn = self.build({"①1-3": [qrow(1), summary]})
        self.assertEqual(len(sets[0]["questions"]), 1)
        self.assertTrue(any("集計" in w and "飛ばした行" in w for w in warn))

    def test_blank_rows_are_silent(self):
        sets, warn = self.build({"①1-3": [qrow(1), ["", "", "", "", "", "", "", "", "", "", "", "", ""]]})
        self.assertEqual(len(sets[0]["questions"]), 1)
        self.assertEqual(warn, [])

    def test_image_is_kept_but_warned(self):
        """画像は今の画面に出ないが、名前は必ず残す（後から画面を足せるように）。"""
        sets, warn = self.build({"③7-9": [qrow(1, image="7-9-⑮ゴミ出し.png")]})
        self.assertEqual(sets[0]["questions"][0]["image_name"], "7-9-⑮ゴミ出し.png")
        self.assertTrue(any("画像つきの設問" in w for w in warn))

    # ---- 配点のばらつき（2026-09-11 追加。★JS 側 fmt-import.js と対になっている） ----

    def test_uniform_points_make_no_warning(self):
        """実測 2026-09-11: 設問のある667シート中 662枚（99.3%）は全問おなじ配点。
        ここで警告を出すとほぼ全部が警告になり、本当に見てほしい5枚が埋もれる。"""
        _, warn = self.build({"①1-3": [qrow(1, points=5), qrow(2, points=5)]})
        self.assertFalse(any("配点がそろっていない" in w for w in warn))

    def test_mixed_points_are_warned_but_not_dropped(self):
        """★採点には配点を使っていないので、取り込みは止めない。作問側に見てもらうだけ。"""
        sets, warn = self.build(
            {"①1-3": [qrow(1, points=5), qrow(2, points=5), qrow(3, points=20)]})
        self.assertEqual(len(sets[0]["questions"]), 3)
        hit = [w for w in warn if "配点がそろっていない" in w]
        self.assertEqual(len(hit), 1)
        self.assertIn("20点の問だけ", hit[0])   # いちばん少ない配点を名指しする
        self.assertIn("5点が2問", hit[0])       # 内訳も出す

    def test_blank_points_do_not_count_as_mixed(self):
        """空欄は「配点が書かれていない」であって「違う配点」ではない。"""
        _, warn = self.build({"①1-3": [qrow(1, points=5), qrow(2, points="")]})
        self.assertFalse(any("配点がそろっていない" in w for w in warn))

    def test_meta_columns_are_kept(self):
        sets, _ = self.build({"①1-3": [qrow(1, cat="文法読解", points=3, explain="かいせつ")]})
        q = sets[0]["questions"][0]
        self.assertEqual((q["category"], q["points"], q["explanation"]), ("文法読解", 3, "かいせつ"))

    def test_no_image_becomes_none(self):
        sets, _ = self.build({"①1-3": [qrow(1)]})
        self.assertIsNone(sets[0]["questions"][0]["image_name"])


# ------------------------------------------------------------------ 計算結果が消えたブック
class StaleCacheTest(Tmp):
    def make_formula_book(self) -> Path:
        """openpyxl で数式を書いて保存＝**計算結果が入っていない**ブックになる。
        2026-09-10 に実際に作ってしまった状態を、そのまま再現している。"""
        wb = Workbook()
        wb.remove(wb.active)
        ws = wb.create_sheet("①1-3")
        ws.append(list(HEAD))
        for i in range(2, 5):
            ws.append([f"={i - 1}", "", "もんだい", "", "あ", "い", "", "", "", "", 1, "文法", 1])
        p = self.dir / "formula.xlsx"
        wb.save(p)
        return p

    def test_missing_cache_is_named_not_silent(self):
        _, warn = fx.build(self.make_formula_book(), None, None, "", False)
        self.assertTrue(any("計算結果が入っていない" in w for w in warn))
        self.assertTrue(any("Excel で開いて保存し直して" in w for w in warn))

    def test_missing_cache_does_not_look_like_an_empty_sheet(self):
        """★ここが肝。ただ0問になるだけだと「問題が無いシート」と見分けが付かない。"""
        sets, _ = fx.build(self.make_formula_book(), None, None, "", False)
        self.assertEqual(sets[0]["questions"], [])
        self.assertIn("error", sets[0])

    def test_normal_book_has_no_such_warning(self):
        _, warn = self.build({"①1-3": [qrow(1)]})
        self.assertFalse(any("計算結果" in w for w in warn))


# ------------------------------------------------------------------ 見出しに頼らない
class HeaderTest(Tmp):
    def test_broken_header_still_reads_by_position(self):
        """「④10-12」で実際に起きていた形＝解答の見出しが消え、カテゴリが別名。"""
        broken = list(HEAD)
        broken[10] = ""            # 解答 → 空
        broken[11] = "文法読解"     # カテゴリ → 別名
        sets, warn = self.build({"④10-12": [qrow(1, ans=3)]}, head=broken)
        self.assertEqual(sets[0]["questions"][0]["correct_idx"], 3)   # ★位置で読めている
        self.assertTrue(any("見出しが" in w for w in warn))           # ★気づけるように言う

    def test_correct_header_makes_no_warning(self):
        _, warn = self.build({"①1-3": [qrow(1)]})
        self.assertFalse(any("見出し" in w for w in warn))


# ------------------------------------------------------------------ 1列ずれた版
class OffsetTest(Tmp):
    """★実データの331本を調べたら、FMT の前に1列増えている版が19シートあった
    （`課番号`＋FMT ＝ スピードマスター等／`設問`＋FMT ＝ 文法チェックテストⅠの「全体」）。
    位置で読む方針は保ったまま、**始まる列だけ**を見出しで決める。"""

    def shifted(self, first_col_name: str):
        head = [first_col_name] + list(HEAD)
        rows = [[f"L{i}"] + qrow(i, choices=("あ", "い", "う"), ans=3) for i in (1, 2)]
        return self.build({"ルビあり": rows}, head=head)

    def test_kabangou_version_is_read_correctly(self):
        sets, _ = self.shifted("課番号")
        q = sets[0]["questions"][0]
        self.assertEqual(q["seq"], 1)
        self.assertEqual(q["choices"], ["あ", "い", "う"])
        self.assertEqual(q["correct_idx"], 3)          # ★ずれていたら 3 は取れない

    def test_setsumon_version_is_read_correctly(self):
        sets, _ = self.shifted("設問")
        self.assertEqual(len(sets[0]["questions"]), 2)

    def test_offset_is_reported(self):
        _, warn = self.shifted("課番号")
        self.assertTrue(any("2 列目から始まっている" in w for w in warn))

    def test_offset_version_has_no_header_warning(self):
        """ずらして読めていれば、見出しのズレとしては警告が出ない。"""
        _, warn = self.shifted("課番号")
        self.assertFalse(any("想定は" in w for w in warn))

    def test_no_offset_when_plain(self):
        _, warn = self.build({"①1-3": [qrow(1)]})
        self.assertFalse(any("列目から始まっている" in w for w in warn))


# ------------------------------------------------------------------ シートの選び方
class SheetTest(Tmp):
    def test_template_sheet_is_skipped_by_default(self):
        sets, _ = self.build({"250507から_課題登録FMT_コピーして使用": [qrow(1)], "①1-3": [qrow(1)]})
        self.assertEqual([s["sheet"] for s in sets], ["①1-3"])

    def test_template_sheet_with_flag(self):
        sets, _ = self.build({"250507から_課題登録FMT_コピーして使用": [qrow(1)], "①1-3": [qrow(1)]},
                             include_template=True)
        self.assertEqual(len(sets), 2)

    def test_only_selected_sheet(self):
        sets, _ = self.build({"①1-3": [qrow(1)], "②4-6": [qrow(1)]}, only=["②4-6"])
        self.assertEqual([s["sheet"] for s in sets], ["②4-6"])

    def test_missing_sheet_name_is_warned(self):
        _, warn = self.build({"①1-3": [qrow(1)]}, only=["⑨25-27"])
        self.assertTrue(any("指定したシートが無い" in w for w in warn))

    def test_exclude(self):
        sets, _ = self.build({"①1-3": [qrow(1)], "②4-6": [qrow(1)]}, exclude=["①1-3"])
        self.assertEqual([s["sheet"] for s in sets], ["②4-6"])

    def test_same_lesson_twice_is_warned(self):
        """実データの「①1-3」と「①1-3 （新）」。そのまま流すと二重登録になる。"""
        _, warn = self.build({"①1-3": [qrow(1)], "①1-3 （新）": [qrow(1)]})
        self.assertTrue(any("同じ範囲" in w for w in warn))

    def test_empty_sheet_is_warned(self):
        _, warn = self.build({"①1-3": []})
        self.assertTrue(any("0 件" in w for w in warn))

    def test_ruby_variants_are_found_by_content(self):
        """★実データの「ルビあり」「ルビなし」＝同じ問題のルビ違いが 284 本のブックにある。
        シート名は表記ゆれ（ルビふり／ルビ振り）があるので、**中身で見つける**。"""
        a = [qrow(1, t2="かんじを よみます", choices=("あ", "い", "う"), ans=2)]
        b = [qrow(1, t2="漢字を読みます", choices=("ア", "イ", "ウ"), ans=2)]   # ルビ無し版
        _, warn = self.build({"ルビあり": a, "ルビなし": b})
        self.assertTrue(any("同じ問題の別版" in w for w in warn))

    def test_different_tests_are_not_flagged_as_variants(self):
        """正解の並びが違えば別のテスト。むやみに疑わない。"""
        _, warn = self.build({"1-①": [qrow(1, ans=1)], "1-②": [qrow(1, ans=2)]})
        self.assertFalse(any("同じ問題の別版" in w for w in warn))

    def test_variant_blocks_sql(self):
        p = self.book({"ルビあり": [qrow(1, ans=2)], "ルビなし": [qrow(1, ans=2)]})
        out = self.dir / "o.sql"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = fx.main(["--xlsx", str(p), "--out-sql", str(out)])
        self.assertEqual(rc, 1)
        self.assertFalse(out.exists())


# ------------------------------------------------------------------ ルビ
class RubyTest(Tmp):
    """★実データのルビは `${昨日}(きのう)` という記法（2026-09-10 判明）。
    239本のブックに「ルビあり／ルビなし」があり、**きあ判断でルビあり版を採用**。
    記法のまま持っておけば、消すのも <ruby> にするのも後からできる。"""

    def test_keep_is_the_default(self):
        sets, _ = self.build({"①1-3": [qrow(1, t2="${昨日}(きのう)、まちで${会}(あ)った")]})
        self.assertEqual(sets[0]["questions"][0]["prompt"], "${昨日}(きのう)、まちで${会}(あ)った")

    def test_strip_removes_ruby(self):
        sets, _ = self.build({"①1-3": [qrow(1, t2="${昨日}(きのう)、まちで${会}(あ)った")]}, ruby="strip")
        self.assertEqual(sets[0]["questions"][0]["prompt"], "昨日、まちで会った")

    def test_html_makes_ruby_tags(self):
        sets, _ = self.build({"①1-3": [qrow(1, t2="${昨日}(きのう)")]}, ruby="html")
        self.assertEqual(sets[0]["questions"][0]["prompt"], "<ruby>昨日<rt>きのう</rt></ruby>")

    def test_choices_get_the_same_treatment(self):
        sets, _ = self.build({"①1-3": [qrow(1, choices=("${会}(あ)う", "い"), ans=1)]}, ruby="strip")
        self.assertEqual(sets[0]["questions"][0]["choices"], ["会う", "い"])

    def test_plain_text_is_untouched(self):
        for mode in ("keep", "strip", "html"):
            sets, _ = self.build({"①1-3": [qrow(1, t2="ふつうの もんだい")]}, ruby=mode)
            self.assertEqual(sets[0]["questions"][0]["prompt"], "ふつうの もんだい")


# ------------------------------------------------------------------ 名前
class NamingTest(unittest.TestCase):
    def test_lesson_from_sheet_name(self):
        self.assertEqual(fx.lesson_of("①1-3 （新）"), "1-3")
        self.assertEqual(fx.lesson_of("⑩28-30"), "28-30")

    def test_lesson_falls_back_to_sheet_name(self):
        """★空にしない。lesson は学生画面のバッジに出るので、空だと「Quiz」としか出ない。"""
        self.assertEqual(fx.lesson_of("1-①"), "1-①")      # チェックテストの形
        self.assertEqual(fx.lesson_of("オリエン"), "オリエン")

    def test_check_test_sheets_are_not_seen_as_duplicates(self):
        """'1-①' '1-②' '1-③' は別の回。範囲が取れないからと同一視してはいけない。"""
        d = tempfile.TemporaryDirectory()
        p = make_book(Path(d.name) / "t.xlsx",
                      {"1-①": [qrow(1)], "1-②": [qrow(1)], "1-③": [qrow(1)]})
        _, warn = fx.build(p, None, None, "", False)
        self.assertFalse(any("同じ範囲" in w for w in warn))
        d.cleanup()

    def test_title_drops_circled_number(self):
        self.assertEqual(fx.title_of("①1-3 （新）", "つなぐ まとめテスト"), "つなぐ まとめテスト 1-3 （新）")
        self.assertEqual(fx.title_of("①1-3", ""), "1-3")


# ------------------------------------------------------------------ SQL
class SqlTest(Tmp):
    def sql(self, sheets, **kw):
        sets, _ = self.build(sheets)
        return fx.to_sql(sets, kw.get("answer_col", "correct_idx"),
                         kw.get("schema", fx.SCHEMA_NEW))

    def test_three_tables_and_is_open_false(self):
        s = self.sql({"①1-3": [qrow(1, choices=("あ", "い", "う"), ans=2)]})
        self.assertIn("insert into quiz_sets(title, lesson, is_open)", s)
        self.assertIn("false", s)
        self.assertIn("insert into questions(quiz_set_id, seq, prompt", s)
        self.assertIn("insert into question_choices(question_id, idx, label)", s)
        self.assertIn("insert into question_answers(question_id, correct_idx", s)
        self.assertIn("values (v_q, 2,", s)

    def test_choices_are_numbered_from_one(self):
        s = self.sql({"①1-3": [qrow(1, choices=("あ", "い", "う"))]})
        self.assertIn("(v_q, 1, 'あ'), (v_q, 2, 'い'), (v_q, 3, 'う')", s)

    def test_quote_is_escaped(self):
        s = self.sql({"①1-3": [qrow(1, t2="It's a pen", choices=("a'b", "c"), ans=1)]})
        self.assertIn("'It''s a pen'", s)
        self.assertIn("'a''b'", s)

    def test_answer_col_can_be_changed(self):
        s = self.sql({"①1-3": [qrow(1)]}, answer_col="correct")
        self.assertIn("question_answers(question_id, correct,", s)
        self.assertIn("正解列 = correct", s)

    # ---- 足りなかった4列（2026-09-10 に db/2026-09-10_question_columns.sql で追加） ----

    def test_extra_columns_written_by_default(self):
        """★以前は JSON にしか残らず、DBに入れた時点で消えていた4つ。"""
        s = self.sql({"③7-9": [qrow(1, image="a.png", cat="文法", points=5, explain="かいせつ")]})
        self.assertIn("image_name, category, points", s)
        self.assertIn("'a.png'", s)
        self.assertIn("'文法'", s)
        self.assertIn("5", s)
        self.assertIn("'かいせつ'", s)

    def test_explanation_goes_to_answers_not_questions(self):
        """🔴 解説を questions に置くと、公開中の回の学生が受験前に読める＝正解が漏れる。
        入れ先は question_answers（教師しか読めない表）でなければならない。"""
        s = self.sql({"①1-3": [qrow(1, explain="ここが正解の理由")]})
        q_line = next(l for l in s.splitlines() if "insert into questions(" in l)
        a_line = next(l for l in s.splitlines() if "insert into question_answers(" in l)
        self.assertNotIn("explanation", q_line)
        self.assertNotIn("ここが正解の理由", q_line)
        self.assertIn("explanation", a_line)
        self.assertIn("'ここが正解の理由'", a_line)

    def test_missing_extras_become_null(self):
        """空欄は null。空文字を入れると「書かれていない」と「空と書いた」が混ざる。"""
        s = self.sql({"①1-3": [qrow(1, image="", cat="", points="", explain="")]})
        q_line = next(l for l in s.splitlines() if "insert into questions(" in l)
        a_line = next(l for l in s.splitlines() if "insert into question_answers(" in l)
        self.assertTrue(q_line.rstrip().endswith("null, null, null) returning id into v_q;"))
        self.assertIn("null);", a_line)

    def test_points_is_written_as_a_number(self):
        s = self.sql({"①1-3": [qrow(1, points=3)]})
        q_line = next(l for l in s.splitlines() if "insert into questions(" in l)
        self.assertIn(", 3)", q_line)
        self.assertNotIn("'3'", q_line)

    def test_old_schema_drops_the_four(self):
        """列を足していない相手向け。★4つは捨てられるので、その旨が SQL に書いてある。"""
        s = self.sql({"③7-9": [qrow(1, image="a.png", explain="かいせつ")]},
                     schema=fx.SCHEMA_OLD)
        self.assertNotIn("image_name", s)
        self.assertNotIn("category", s)
        self.assertNotIn("explanation", s)
        self.assertNotIn("'a.png'", s)
        self.assertIn("捨てられる", s)

    def test_schema_generation_is_recorded_in_the_sql(self):
        """どちらの世代で書き出したのかが、ファイルを見れば分かること。"""
        self.assertIn(f"スキーマ = {fx.SCHEMA_NEW}", self.sql({"①1-3": [qrow(1)]}))
        self.assertIn(f"スキーマ = {fx.SCHEMA_OLD}",
                      self.sql({"①1-3": [qrow(1)]}, schema=fx.SCHEMA_OLD))

    def test_quiz_set_questions_is_left_to_the_trigger(self):
        """②と①をつなぐ表はトリガが埋める。ここで二重に書かない。"""
        s = self.sql({"①1-3": [qrow(1)]})
        self.assertNotIn("insert into quiz_set_questions", s)

    def test_transaction_wraps_everything(self):
        """★行番号で数えない（先頭の注意書きが増えるたびに落ちるため）。
        「最初の中身の行が begin; で、最後が commit;」であることを見る。"""
        s = self.sql({"①1-3": [qrow(1)]})
        body = [l for l in s.splitlines() if l.strip() and not l.lstrip().startswith("--")]
        self.assertEqual(body[0], "begin;")
        self.assertEqual(body[-1], "commit;")
        self.assertLess(s.index("begin;"), s.index("insert into"))


# ------------------------------------------------------------------ main（入口）
class MainTest(Tmp):
    def run_main(self, argv) -> tuple[int, str]:
        """★画面出力は受け止めてから返す。
        素のまま呼ぶと、同じ実行で先に走った別のテストが標準出力を閉じていた場合に
        print で落ちる。テストが実行の順番に左右されないようにする。
        ※ その原因（モジュール読み込み時に sys.exit する書き方・stdout の二重ラップ）は
          2026-09-10 に解消済み。この受け止め自体は無害なので残してある。"""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = fx.main(argv)
        return rc, buf.getvalue()

    def test_duplicate_lesson_refuses_to_write_sql(self):
        """★二重登録は起きてからでは戻せないので、SQL を書かずに止める。"""
        p = self.book({"①1-3": [qrow(1)], "①1-3 （新）": [qrow(1)]})
        out = self.dir / "o.sql"
        rc, msg = self.run_main(["--xlsx", str(p), "--out-sql", str(out)])
        self.assertEqual(rc, 1)
        self.assertFalse(out.exists())
        self.assertIn("SQL は書きませんでした", msg)

    def test_duplicate_lesson_can_be_forced(self):
        p = self.book({"①1-3": [qrow(1)], "①1-3 （新）": [qrow(1)]})
        out = self.dir / "o.sql"
        self.run_main(["--xlsx", str(p), "--out-sql", str(out), "--allow-duplicate-lesson"])
        self.assertTrue(out.exists())

    def test_json_keeps_image_name(self):
        p = self.book({"③7-9": [qrow(1, image="7-9-⑮ゴミ出し.png")]})
        out = self.dir / "o.json"
        self.run_main(["--xlsx", str(p), "--out-json", str(out)])
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["sets"][0]["questions"][0]["image_name"], "7-9-⑮ゴミ出し.png")

    def test_missing_file_returns_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fx.main(["--xlsx", str(self.dir / "no.xlsx")]), 2)

    def test_clean_book_returns_0(self):
        p = self.book({"①1-3": [qrow(1), qrow(2)]})
        rc, _ = self.run_main(["--xlsx", str(p)])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
