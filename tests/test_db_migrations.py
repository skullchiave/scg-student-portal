#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""test_db_migrations.py — db/ に置いた SQL の見張り（DB不要・2026-09-10）

**DBには繋がない。** db/*.sql をテキストとして読んで、
CLAUDE.md「絶対に守ること」のうち **SQL を書いた時点で決まってしまう**ものを確かめる。

なぜ要るか＝この2つは、どちらも 2026-09-06 に実際に踏みかけた:
  ・ポリシーに `to authenticated` を書き忘れると全ロール（anon 含む）が対象になり、
    「公開中の回なら読める」が未ログインでも真になって漏れる
  ・新しい RPC に `revoke execute ... from anon` を書き忘れると、Supabase の既定権限で
    anon に execute が付き直す（`revoke all ... from public` だけでは足りない）
どちらも**流したあとに気づくと、その間ずっと開いている**。流す前に落とす。

  py -X utf8 -m unittest discover -s tests -p "test_db_migrations.py" -v
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "db"
BASELINE = "0000_baseline.sql"


def strip_comments(sql: str) -> str:
    """行コメントを落とす。★巻き戻し手順やメモはコメントで書いてあるので、
    それを「実行される SQL」と数えないため。"""
    out = []
    for line in sql.splitlines():
        i = line.find("--")
        out.append(line if i < 0 else line[:i])
    return "\n".join(out)


def migrations() -> list[Path]:
    """ベースライン以外の、日付つき SQL。"""
    return sorted(p for p in DB.glob("*.sql") if p.name != BASELINE)


# ★ここから下のルールを決めたのは 2026-09-10。それ以前のファイルは対象にしない。
#   既存を書き直さないための線引きで、「守らなくてよい」ではない。
#   ⚠ 方針を変えたら、この日付と下の KNOWN_GAPS をもう一度見ること。
RULES_SINCE = "2026-09-10"

# 2026-09-10 より前のファイルにある、いまのルールから外れている点。
#   ★「見つけていない」ではなく「見つけたうえで、直さないと決めた」もの。
#   attempt_drafts / attempt_focus のポリシーは `to public` で書かれていて、
#   表そのものも anon から revoke していない。ただし条件が student_id = auth.uid() で、
#   anon では auth.uid() が null → 比較結果も null → 1行も返らない。**穴ではない。**
#   直すと動いているものを触ることになるので、ここに書いて残す。
#   ⚠ もし将来この2つのポリシーの条件を変えるなら、同時に to authenticated を足すこと。
KNOWN_GAPS = {
    "2026-09-06_attempt_drafts.sql": ("attempt_drafts", "attempt_focus"),
    "2026-09-06_attempt_focus.sql": ("attempt_focus",),
}


def new_migrations() -> list[Path]:
    """2026-09-10 以降のファイルだけ。"""
    return [p for p in migrations() if p.name[:10] >= RULES_SINCE]


class FilesTest(unittest.TestCase):
    def test_baseline_exists(self):
        self.assertTrue((DB / BASELINE).exists(), "db/0000_baseline.sql が無い")

    def test_migrations_are_dated(self):
        """★名前の先頭が日付＝流す順番がファイル名だけで決まる。"""
        for p in migrations():
            self.assertRegex(p.name, r"^\d{4}-\d{2}-\d{2}_",
                             f"{p.name} が日付で始まっていない")


class AdditiveOnlyTest(unittest.TestCase):
    """🔴 既存テーブルの列の変更・削除はしない（追加はよい）。

    ⚠ 2026-09-06_multi_choice.sql だけは例外。選択肢を2個固定から作り直した回で、
      きあの判断のもと choice_a / choice_b を落としている。**その1本だけを許す**。
      新しく例外を増やすときは、ここに書き足すこと自体が「意識して壊す」宣言になる。
    """
    ALLOWED = {"2026-09-06_multi_choice.sql"}

    def test_no_drop_column(self):
        for p in migrations():
            if p.name in self.ALLOWED:
                continue
            body = strip_comments(p.read_text(encoding="utf-8"))
            self.assertNotRegex(body, r"(?i)\bdrop\s+column\b",
                                f"{p.name}: 列を落としている")

    def test_no_type_change(self):
        for p in migrations():
            if p.name in self.ALLOWED:
                continue
            body = strip_comments(p.read_text(encoding="utf-8"))
            self.assertNotRegex(body, r"(?i)\balter\s+column\s+\w+\s+type\b",
                                f"{p.name}: 列の型を変えている")

    def test_no_drop_table(self):
        for p in migrations():
            body = strip_comments(p.read_text(encoding="utf-8"))
            self.assertNotRegex(body, r"(?i)\bdrop\s+table\b",
                                f"{p.name}: 表を落としている")

    def test_no_delete_or_truncate(self):
        """★回答は消さない。取り消しは is_void で、行は残す。"""
        for p in migrations():
            body = strip_comments(p.read_text(encoding="utf-8"))
            self.assertNotRegex(body, r"(?i)\btruncate\b", f"{p.name}: truncate がある")
            self.assertNotRegex(body, r"(?i)^\s*delete\s+from\s+public\.",
                                f"{p.name}: 行を消している")


class TransactionTest(unittest.TestCase):
    def test_begin_and_commit_are_balanced(self):
        for p in migrations():
            body = strip_comments(p.read_text(encoding="utf-8"))
            b = len(re.findall(r"(?im)^\s*begin\s*;", body))
            c = len(re.findall(r"(?im)^\s*commit\s*;", body))
            self.assertEqual(b, c, f"{p.name}: begin {b} 件 / commit {c} 件で釣り合わない")
            self.assertGreaterEqual(b, 1, f"{p.name}: トランザクションで囲まれていない")


class PolicyTest(unittest.TestCase):
    """🔴 新しい表のポリシーには to authenticated を必ず書く。"""

    def test_every_create_policy_names_a_role(self):
        pat = re.compile(r"(?is)create\s+policy\s+(.+?)(?=;)")
        for p in new_migrations():
            body = strip_comments(p.read_text(encoding="utf-8"))
            for m in pat.finditer(body):
                stmt = " ".join(m.group(1).split())
                self.assertRegex(
                    stmt, r"(?i)\bto\s+authenticated\b",
                    f"{p.name}: to authenticated が無いポリシー → {stmt[:90]}")

    def test_known_gaps_are_still_only_the_known_ones(self):
        """★既知例外が増えていないかの見張り。
        2026-09-10 より前のファイルで to public のポリシーを持つ表が、
        KNOWN_GAPS に書いた通りであること。増えていたら例外表を見直す合図。"""
        pat = re.compile(r"(?is)create\s+policy\s+.+?on\s+public\.(\w+).+?(?=;)")
        for p in migrations():
            if p.name[:10] >= RULES_SINCE:
                continue
            body = strip_comments(p.read_text(encoding="utf-8"))
            found = {m.group(1) for m in pat.finditer(body)
                     if not re.search(r"(?i)\bto\s+authenticated\b", m.group(0))}
            self.assertLessEqual(
                found, set(KNOWN_GAPS.get(p.name, ())),
                f"{p.name}: 既知例外に無い表のポリシーが to authenticated 無しで書かれている")


class FunctionGrantTest(unittest.TestCase):
    """🔴 新しい RPC を足したら revoke execute ... from anon を必ず書く。

    `revoke all ... from public` だけでは Supabase の既定権限で anon に付き直す。
    public スキーマの関数（＝API から呼べる関数）だけを見る。
    """

    CREATE = re.compile(
        r"(?is)create\s+(?:or\s+replace\s+)?function\s+public\.(\w+)\s*\(")

    def public_functions(self, body: str) -> set[str]:
        return {m.group(1) for m in self.CREATE.finditer(body)}

    def test_anon_is_revoked_for_every_public_function(self):
        for p in migrations():
            body = strip_comments(p.read_text(encoding="utf-8"))
            for name in self.public_functions(body):
                self.assertRegex(
                    body,
                    rf"(?is)revoke\s+(?:all|execute)[^;]*\bon\s+function\s+public\.{name}\s*\([^;]*\bfrom\b[^;]*\banon\b",
                    f"{p.name}: public.{name}() に anon への revoke が無い")

    def test_authenticated_is_granted_for_every_public_function(self):
        """revoke だけして grant を忘れると、学生から呼べなくなる（逆方向の事故）。"""
        for p in migrations():
            body = strip_comments(p.read_text(encoding="utf-8"))
            for name in self.public_functions(body):
                self.assertRegex(
                    body,
                    rf"(?is)grant\s+execute\s+on\s+function\s+public\.{name}\s*\([^;]*\bto\b[^;]*\bauthenticated\b",
                    f"{p.name}: public.{name}() に authenticated への grant が無い")

    def test_hidden_helpers_are_not_exposed(self):
        """app_hidden のヘルパーは anon から呼べてはいけない（教師判定を匿名で叩けてしまう）。"""
        pat = re.compile(r"(?is)create\s+(?:or\s+replace\s+)?function\s+app_hidden\.(\w+)\s*\(")
        for p in migrations():
            body = strip_comments(p.read_text(encoding="utf-8"))
            for m in pat.finditer(body):
                name = m.group(1)
                if name.startswith("sync_"):
                    continue    # トリガ関数。API からは呼べないので revoke は要らない
                self.assertRegex(
                    body,
                    rf"(?is)revoke\s+all\s+on\s+function\s+app_hidden\.{name}\s*\([^;]*\bfrom\b[^;]*\banon\b",
                    f"{p.name}: app_hidden.{name}() に anon への revoke が無い")


class NewTableTest(unittest.TestCase):
    """新しい表は RLS を有効にして、anon から表そのものを取り上げる。"""

    CREATE = re.compile(r"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?public\.(\w+)")

    def test_new_tables_enable_rls(self):
        for p in migrations():
            body = strip_comments(p.read_text(encoding="utf-8"))
            for m in self.CREATE.finditer(body):
                name = m.group(1)
                self.assertRegex(
                    body, rf"(?is)alter\s+table\s+public\.{name}\s+enable\s+row\s+level\s+security",
                    f"{p.name}: public.{name} に RLS が入っていない")

    def test_new_tables_revoke_anon(self):
        for p in new_migrations():
            body = strip_comments(p.read_text(encoding="utf-8"))
            for m in self.CREATE.finditer(body):
                name = m.group(1)
                self.assertRegex(
                    body, rf"(?is)revoke\s+all\s+on\s+table\s+public\.{name}\s+from\s+anon",
                    f"{p.name}: public.{name} を anon から revoke していない")


class RollbackNoteTest(unittest.TestCase):
    """完了条件「流し直し→巻き戻しの手順が書いてある」の見張り。"""

    def test_every_migration_documents_rollback(self):
        for p in new_migrations():
            text = p.read_text(encoding="utf-8")
            self.assertIn("巻き戻", text, f"{p.name}: 巻き戻し手順が書かれていない")


class SecretsTest(unittest.TestCase):
    """★このリポは public。実在の学籍番号・氏名・鍵を db/ に書かない。"""

    def test_no_service_role_key(self):
        for p in DB.glob("*.sql"):
            body = p.read_text(encoding="utf-8")
            self.assertNotIn("service_role_key", body, f"{p.name}")
            # JWT の頭（eyJ...）が生で入っていないこと
            self.assertNotRegex(body, r"\beyJ[A-Za-z0-9_\-]{20,}", f"{p.name}: 鍵らしき文字列")

    def test_no_real_looking_student_numbers(self):
        """学籍番号の書式例は 999 から降順の帯を使う（001 側は実在の番号と衝突する）。"""
        bad = []
        for p in DB.glob("*.sql"):
            for m in re.finditer(r"\b26-?0?4?0?\d{2}(\d{3})\b", p.read_text(encoding="utf-8")):
                if not m.group(1).startswith("99"):
                    bad.append(f"{p.name}: {m.group(0)}")
        self.assertEqual(bad, [], "実在しうる学籍番号の書式: " + ", ".join(bad))


class FourLayersTest(unittest.TestCase):
    """2026-09-10 の4層。★設計の要点が消えていないかを見る。"""

    def setUp(self):
        p = DB / "2026-09-10_four_layers.sql"
        if not p.exists():
            self.skipTest("db/2026-09-10_four_layers.sql が無い")
        self.text = p.read_text(encoding="utf-8")
        self.body = strip_comments(self.text)

    def test_run_table_exists(self):
        self.assertRegex(self.body, r"(?is)create\s+table\s+if\s+not\s+exists\s+public\.quiz_runs")

    def test_link_table_exists(self):
        self.assertRegex(self.body,
                         r"(?is)create\s+table\s+if\s+not\s+exists\s+public\.quiz_set_questions")

    def test_existing_questions_are_backfilled(self):
        """★バックフィルが無いと、既にある回が「設問0件」になる。"""
        self.assertRegex(self.body,
                         r"(?is)insert\s+into\s+public\.quiz_set_questions[^;]*from\s+public\.questions")

    def test_targets_are_lists_not_conditions(self):
        """🔴 対象は「条件」ではなく「結果のリスト」。
        国籍・エージェント・出席率を profiles に持たせない設計の要。"""
        self.assertRegex(self.body, r"class_names\s+text\[\]")
        self.assertRegex(self.body, r"student_ids\s+uuid\[\]")
        for col in ("nationality", "agent", "attendance"):
            self.assertNotIn(col, self.body, f"profiles に {col} を持ち込んでいる")

    def test_void_keeps_the_answers(self):
        """🔴 取り消しても回答は消さない（集計から外れるだけ）。"""
        self.assertIn("is_void", self.body)
        self.assertNotRegex(self.body, r"(?is)delete\s+from\s+public\.attempts")
        self.assertNotRegex(self.body, r"(?is)delete\s+from\s+public\.attempt_answers")

    def test_quiz_run_is_one_class(self):
        """小テストの実施回は1クラス。方針を作りの制約にしてある。"""
        self.assertRegex(
            self.body,
            r"(?is)quiz_runs_one_class_check\s+check\s*\(.*?array_length\(class_names.*?<=\s*1")

    def test_new_rpc_args_have_defaults(self):
        """★既定値つきでないと、src/ を同時に直さないと壊れる。"""
        for sig in (r"p_run_id\s+uuid\s+default\s+null",
                    r"p_duration_min\s+integer\s+default\s+\d+"):
            self.assertRegex(self.body, "(?is)" + sig, f"既定値が無い: {sig}")

    def test_survey_unique_swap_is_not_executed(self):
        """🔴 段階2（一意制約の張り替え）は、src/ と同時でないと提出が壊れる。
        このファイルでは**コメントの中だけ**にあること。"""
        self.assertNotRegex(
            self.body,
            r"(?is)drop\s+constraint\s+if\s+exists\s+survey_responses_student_id_survey_key_key",
            "段階2の SQL が実行される位置にある")
        self.assertIn("survey_responses_student_id_survey_key_key", self.text,
                      "段階2の手順そのものが書かれていない")


class QuestionColumnsTest(unittest.TestCase):
    """2026-09-10 の4列。★解説の置き場が要点。"""

    def setUp(self):
        p = DB / "2026-09-10_question_columns.sql"
        if not p.exists():
            self.skipTest("db/2026-09-10_question_columns.sql が無い")
        self.body = strip_comments(p.read_text(encoding="utf-8"))

    def test_three_columns_go_to_questions(self):
        for col in ("image_name", "category", "points"):
            self.assertRegex(
                self.body,
                rf"(?is)alter\s+table\s+public\.questions\s+add\s+column\s+if\s+not\s+exists\s+{col}",
                f"questions に {col} が足されていない")

    def test_explanation_goes_to_answers(self):
        """🔴 questions に置くと、公開中の回の解説を受験前に読めてしまう。"""
        self.assertRegex(
            self.body,
            r"(?is)alter\s+table\s+public\.question_answers\s+add\s+column\s+if\s+not\s+exists\s+explanation")
        self.assertNotRegex(
            self.body,
            r"(?is)alter\s+table\s+public\.questions\s+add\s+column\s+if\s+not\s+exists\s+explanation",
            "解説を questions に置いている（学生に読める表）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
