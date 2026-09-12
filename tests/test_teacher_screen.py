#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""test_teacher_screen.py — 先生の画面（src/teacher.html）の構造検査（2026-09-12 新規）

DB不要。src/teacher.html を文字列として読み、正規表現・部分一致だけで確かめる
（test_ruby.py の NoRawInnerHtmlTest と同じやり方）。

★何を見張っているか（本題はこちら）
  teacher.html は「机の仕事（登録・アンケート作成・お知らせ配信・点検）」を master.html から
  切り出さずに、白紙から小さく作った先生専用の画面。授業中に使うものだけしか入っていない。
  ★「入れていないこと」を検査に固定するのが肝＝あとで誰かが機能を足しても、ここが落ちて気づける。
  もし将来この検査に意図して手を入れるなら、それは「先生画面の役割を広げる」という判断そのものなので、
  先に運用の正典（ドライブ側 CLAUDE.md）で合意してから、ここを直すこと。

実行:
  py -X utf8 -m unittest discover -s tests -p "test_teacher_screen.py" -v
依存: 標準ライブラリのみ。node があれば JS 構文チェックも走る（無ければその項目だけ skip）。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
TEACHER = SRC / "teacher.html"
MASTER = SRC / "master.html"
NODE = shutil.which("node")


def read() -> str:
    return TEACHER.read_text(encoding="utf-8")


def strip_comments(src: str) -> str:
    """HTML コメントと /* */ ブロックコメントを取り除く。
    ★このファイル自身が「入れていない理由」を説明するコメント
    （例:「登録・アンケート作成・お知らせ配信・点検＝机の仕事は master.html」）を書いているため、
    コメントごと素の文字列一致で見ると、説明そのものが「入っている」と誤検出される。
    否定条件（入っていないこと）を見るテストは、必ずこちらを経由すること。"""
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    # ★行コメント（//）も落とす。2026-09-12 に、行コメントの中の説明文へ
    #   自分の検査（confirm( を探すもの）が当たって落ちた。
    #   ⚠ その時点の teacher.html にあった行コメントは、その後の編集でもう残っていない。
    #     ＝**再現しないが、再発しうる**ので、原因側（コメントを数えてしまうこと）を塞いである。
    #   URL の // を壊さないよう、**行頭が // の行だけ**を消す。
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    return src


class FileExistsTest(unittest.TestCase):
    def test_teacher_html_exists(self):
        self.assertTrue(TEACHER.exists(), "src/teacher.html が無い")

    def test_master_and_index_untouched_are_still_separate_files(self):
        """teacher.html は master.html とは別ファイル（削って作ったのではなく新規）。"""
        self.assertTrue((SRC / "index.html").exists())
        self.assertTrue(MASTER.exists())
        self.assertNotEqual(TEACHER.read_bytes(), MASTER.read_bytes())


class SmallerThanMasterTest(unittest.TestCase):
    """🔴 master.html から機能を削って作らない＝結果としてずっと短いファイルになるはず、という約束の検査。"""

    def test_teacher_is_much_shorter_than_master(self):
        t_lines = read().count("\n")
        m_lines = MASTER.read_text(encoding="utf-8").count("\n")
        self.assertLess(t_lines, m_lines * 0.7,
                         f"teacher.html（{t_lines}行）が master.html（{m_lines}行）に対して短くない。"
                         "削って作っていないか確認すること。")


class NoBannedScriptsTest(unittest.TestCase):
    """🔴 fmt-import.js（取り込み）と xlsx.js（SheetJS）は読み込まない＝取り込みは先生の仕事ではない。"""

    def test_does_not_load_fmt_import(self):
        self.assertNotIn("fmt-import.js", _script_srcs(read()))

    def test_does_not_load_xlsx(self):
        srcs = _script_srcs(read())
        self.assertFalse(any("xlsx" in s.lower() for s in srcs), srcs)

    def test_still_loads_the_shared_assets(self):
        """既存を使い回す: api.js / i18n.js / app.css / ruby.js。"""
        src = read()
        for must in ("assets/api.js", "assets/i18n.js", "assets/app.css", "assets/ruby.js"):
            self.assertIn(must, src, f"{must} を読み込んでいない")


def _script_srcs(src: str) -> list[str]:
    return re.findall(r'<script[^>]*\ssrc="([^"]+)"', src)


class DoesNotIncludeDeskWorkTest(unittest.TestCase):
    """入れないもの（机の仕事＝master.html の役割）が入っていないことを見張る。
    ★ここが本題。あとで機能が足されて意味が消えないよう、否定条件を検査に固定する。"""

    def setUp(self):
        self.src = strip_comments(read())

    # ---- 問題の登録・解放（取り込み・公開/停止・削除） ----
    def test_no_excel_import_ui(self):
        for bad in ("Excelから取り込む", "課題登録FMT", "qs-file", "loadWorkbook", "publishSet"):
            self.assertNotIn(bad, self.src, f"取り込みの部品が入っている: {bad}")

    def test_no_publish_stop_toggle(self):
        for bad in ("delete_quiz_set", "FmtImport.db.setOpen", "qs-toggle", "qs-del",
                    "公開をやめる", "この回を消します"):
            self.assertNotIn(bad, self.src, f"公開/停止/削除の部品が入っている: {bad}")

    # ---- アンケート（回答一覧・作成） ----
    def test_no_survey_features(self):
        for bad in ("SURVEYS", "surveys.js", "openSurveyRoundDialog", "start_survey_round",
                    "sv-pick", "sv-list", "sv-rounds-list", "アンケート"):
            self.assertNotIn(bad, self.src, f"アンケートの部品が入っている: {bad}")

    # ---- 学生アカウント・お知らせ配信・点検/バックアップ ----
    def test_no_student_account_admin(self):
        self.assertNotIn("学生アカウント", self.src)

    def test_no_notice_broadcast(self):
        self.assertNotIn("お知らせ配信", self.src)

    def test_no_ops_inspection(self):
        for bad in ("点検・バックアップ", "get_advisors"):
            self.assertNotIn(bad, self.src, f"点検・バックアップの部品が入っている: {bad}")

    # ---- 「これから作る画面（イメージ）」の類 ----
    def test_no_mock_screens(self):
        for bad in ("これから作る画面", "mockflag", "<span class=\"soon\">"):
            self.assertNotIn(bad, self.src, f"イメージ画面の部品が入っている: {bad}")

    # ---- 一覧に編集・公開・停止・削除ボタンを置かない（「はじめる」だけ） ----
    def test_select_list_has_no_edit_publish_delete_buttons(self):
        for bad_class in ("qs-toggle", "qs-del", "qs-start"):
            self.assertNotIn(bad_class, self.src, f"master.html 由来のボタンclassが残っている: {bad_class}")


class RequiredFeaturesTest(unittest.TestCase):
    """入れるものが実際に入っていることの検査。"""

    def setUp(self):
        self.src = read()

    def test_today_view_has_end_and_void(self):
        """📅今日: おわる・取り消す（renderTodayRuns 相当）。"""
        self.assertIn("close_quiz_run", self.src)
        self.assertIn("void_quiz_run", self.src)
        self.assertIn("おわる", self.src)
        self.assertIn("取り消す", self.src)
        self.assertIn("today-runs", self.src)

    def test_select_view_has_filter_search_count_more(self):
        """▶ テストを選んではじめる: 教材で絞る・テスト名で検索・件数表示・もっと見る。"""
        self.assertIn("sel-filter-book", self.src)
        self.assertIn("sel-filter-q", self.src)
        self.assertIn("sel-filter-note", self.src)
        self.assertIn("sel-btn-more", self.src)
        self.assertIn("source_book", self.src)

    def test_select_view_can_start_a_run(self):
        """選ぶ → クラスと時間を決める → はじめる。"""
        self.assertIn("openRunDialog", self.src)
        self.assertIn("start_quiz_run", self.src)
        self.assertIn("run_target_count", self.src)
        self.assertIn("run-class", self.src)
        self.assertIn("run-dur", self.src)

    def test_starting_jumps_to_today_with_marker(self):
        """はじめたら「📅今日」へ移り、その回に目印を出す（master.html と同じ動き）。"""
        self.assertIn('setView("today")', self.src)
        self.assertIn("justStartedRunId", self.src)
        self.assertIn("just-started", self.src)

    def test_quiz_live_stats(self):
        """📝小テスト ライブ集計: 提出数・平均点・設問別正答率・提出フィード。"""
        self.assertIn("quiz_stats", self.src)
        self.assertIn('id="st-count"', self.src)
        self.assertIn('id="st-avg"', self.src)
        self.assertIn('id="qrates"', self.src)
        self.assertIn('id="feed"', self.src)

    def test_csv_export_is_inside_quiz_view(self):
        """結果の書き出し（CSV）はライブ集計の中。個票と問題ごとの2種類・範囲の選択つき。"""
        view_quiz = re.search(r'id="view-quiz".*?(?=\n    <!--|\n  </section>)', self.src, re.S)
        self.assertIsNotNone(view_quiz, "view-quiz の範囲が見つからない")
        block = view_quiz.group(0)
        self.assertIn("csv-btn-student", block)
        self.assertIn("csv-btn-question", block)
        self.assertIn("csv-run-pick", block)
        self.assertIn("BOM", self.src)

    def test_qr_button_shows_student_url(self):
        """🔢学生用QRを表示。"""
        self.assertIn("qrcodejs", self.src)
        self.assertIn("btn-qr", self.src)
        self.assertIn("QRCode(", self.src)


class RoleGateTest(unittest.TestCase):
    """role による門番。★案内であって権限ではない（RLSが権限を持つ）ことも含めて確認する。"""

    def setUp(self):
        self.src = read()

    def test_teacher_role_is_accepted(self):
        self.assertIn('p.role!=="teacher" && p.role!=="master"', self.src)

    def test_master_role_gets_a_notice_not_a_block(self):
        self.assertIn("master-notice", self.src)
        self.assertIn("master.html", self.src)
        # ログイン成功後、teacher/master どちらでもない場合だけを断る形になっていること
        # （= master 単独を締め出す分岐が別に無いこと）。
        self.assertIn('p.role!=="teacher" && p.role!=="master"', self.src)
        self.assertIn("applyRoleNotice(p.role)", self.src)

    def test_other_roles_are_rejected_and_pointed_to_index(self):
        self.assertIn("api.logout()", self.src)
        self.assertIn("index.html", self.src)

    def test_session_resume_accepts_both_roles(self):
        """自動ログイン維持（リロード時）も teacher と master の両方を通すこと。
        ★master.html 側は role==='teacher' しか見ていない、資産の非対称に注意
          （このテストは teacher.html 自身の資産についてのものなので、それとは別）。"""
        m = re.search(r"\(async \(\)=>\{\s*if\(api\.token.*?\}\)\(\);", self.src, re.S)
        self.assertIsNotNone(m, "自動ログイン維持のブロックが見つからない")
        block = m.group(0)
        self.assertIn('"teacher"', block)
        self.assertIn('"master"', block)


class NoRawConfirmTest(unittest.TestCase):
    """confirm() を使わない。自前の <dialog>（askDialog）で確認する（master.html と同じ方針）。"""

    def test_no_bare_confirm_call(self):
        src = strip_comments(read())
        # window.confirm / confirm( のどちらの書き方も禁止
        self.assertNotRegex(src, r"(?<!ask)[Cc]onfirm\(")

    def test_uses_ask_dialog(self):
        src = read()
        self.assertIn("function askDialog", src)
        self.assertIn("askDialog({", src)


class NoRawInnerHtmlOfUntrustedTextTest(unittest.TestCase):
    """設問文・選択肢を扱わない画面だが、名前・クラス名など人が入力した値を
    innerHTML の属性値へ差し込む箇所は escHtml を通すこと（ruby.js の escHtml）。"""

    def test_escHtml_used_for_option_values(self):
        src = read()
        self.assertIn("escHtml(", src)

    def test_ruby_js_loaded_before_use(self):
        src = read()
        self.assertLess(src.index("assets/ruby.js"), src.index("escHtml("))


@unittest.skipUnless(NODE, "node が無いので skip")
class JsSyntaxTest(unittest.TestCase):
    def test_inline_script_is_valid_js(self):
        src = read()
        m = re.search(r"<script>(.*)</script>\s*</body>", src, re.S)
        self.assertIsNotNone(m, "本文の <script> が見つからない")
        # new Function(body) は構文解析だけ行い、実行はしない（document 等が無い node でも安全に検査できる）。
        p = subprocess.run([NODE, "-e", "new Function(require('fs').readFileSync(0,'utf8'))"],
                           input=m.group(1), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr[:800])


if __name__ == "__main__":
    unittest.main(verbosity=2)
