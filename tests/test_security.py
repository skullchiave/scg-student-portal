# -*- coding: utf-8 -*-
"""セキュリティ回帰テスト — scg-student-portal

「安全性の担保」を毎回機械的に再検証するためのテスト。スキーマやポリシーを
変更したら必ず実行すること。全部 PASS しない状態でデプロイしてはいけない。

このリポで一番重い検査なので、既定でskipにはしない：
  - 単体で実行     … python tests/test_security.py
                      → 引数なしでも常に本物のDBを叩く（従来どおり）
  - discoverで実行 … py -X utf8 -m unittest discover -s tests -p "test_*.py"
                      → 既定ではskip（他のテストに巻き込んで落とさないため）。
                        本気で回すには環境変数 SP_LIVE=1 を付ける
  DBに接続できない環境（ネットワークが無い等）では、live扱いのときも
  自動的にskipへ倒れる（FAILにはしない）。

使い方: python tests/test_security.py
依存:   標準ライブラリのみ
"""
import sys, os, json, io, unittest
import urllib.request
import urllib.error

# discoverで他のtest_*.pyと同じプロセスに同居する時、全員が無条件に
# sys.stdout を包み直すと、先に包んだ方のラッパーがGCで下敷きのbufferを
# 道連れに閉じてしまい "I/O operation on closed file" になる。
# すでにutf-8ならそのまま使う（-X utf8 実行なら通常ここに来る）。
if getattr(sys.stdout, "encoding", "").lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "https://egdcbxzpgwenmfabpodd.supabase.co"
ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVnZGNieHpwZ3dlbm1mYWJwb2RkIiwi"
        "cm9sZSI6ImFub24iLCJpYXQiOjE3ODgzNTcwNDYsImV4cCI6MjEwMzkzMzA0Nn0.m908C67Nh4KsYnH_LWvP4wAjOtxI79hhE-BKS1MCxX0")
QUIZ_SET = "c75def6b-7623-4d86-8540-0c5b081ecf7c"

# 単体実行(__main__)なら引数なしでも必ずlive。discover経由は SP_LIVE=1 か --live が要る。
RUN_LIVE = (__name__ == "__main__") or os.environ.get("SP_LIVE") == "1" or "--live" in sys.argv


def req(path, token=None, body=None, extra=None):
    headers = {"apikey": ANON, "Content-Type": "application/json"}
    if extra: headers.update(extra)
    if token: headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=20) as res:
            return res.status, json.loads(res.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "null")


def login(no, pw):
    st, body = req("/auth/v1/token?grant_type=password",
                   body={"email": f"{no}@stu.scg-portal.jp", "password": pw})
    return body.get("access_token") if st == 200 else None


@unittest.skipUnless(RUN_LIVE, "discover実行時は既定でskip。単体実行(python tests/test_security.py)か SP_LIVE=1 で有効化")
class TestSecurity(unittest.TestCase):
    """本物のDB（デモ環境）を実際に叩いて安全性を検証する"""

    @classmethod
    def setUpClass(cls):
        try:
            cls.stok = login("s001", "sakura24")
            cls.ttok = login("t001", "sensei-scg-2026")
        except (urllib.error.URLError, OSError) as e:
            raise unittest.SkipTest(f"DBに接続できないためskip（{e}）")

    def check(self, name, cond, detail=""):
        print(("  ✅ " if cond else "  ❌ ") + name + (f"  ({detail})" if detail and not cond else ""))
        with self.subTest(name=name):
            self.assertTrue(cond, detail or name)

    def _require_tokens(self):
        if not self.stok or not self.ttok:
            self.skipTest("前提のログインが崩れているため中断（test_00_loginを確認）")

    def test_00_login(self):
        print("\n=== 0. 前提: ログイン ===")
        self.check("学生ログインできる", self.stok is not None)
        self.check("教師ログインできる", self.ttok is not None)

    def test_01_auth(self):
        self._require_tokens()
        print("\n=== 1. 認証まわり ===")
        self.check("誤ったパスワードは拒否される", login("s001", "wrong-pass") is None)
        st, _ = req("/rest/v1/quiz_sets?select=id")
        self.check("未ログインではデータを読めない", st in (200, 401) and (st == 401 or _ == []))

    def test_02_answer_isolation(self):
        self._require_tokens()
        print("\n=== 2. 正解データの遮断（正解は question_answers テーブルに分離されている） ===")
        st, body = req("/rest/v1/question_answers?select=*", self.stok)
        self.check("学生は question_answers(正解テーブル)を読めない", body == [])
        st, body = req("/rest/v1/questions?select=*&limit=1", self.stok)
        self.check("学生は questions(問題文)を読める", st == 200 and len(body) == 1)
        self.check("questions に正解列が存在しない（構造で保証）", body and "correct" not in body[0])
        st, body = req("/rest/v1/question_answers?select=*", self.ttok)
        self.check("教師は question_answers を読める", st == 200 and len(body) > 0)

    def test_03_stats_api(self):
        self._require_tokens()
        print("\n=== 3. 集計APIの権限 ===")
        st, body = req("/rest/v1/rpc/quiz_stats", self.stok, {"p_quiz_set_id": QUIZ_SET})
        self.check("学生は quiz_stats を呼べない(forbidden)", isinstance(body, dict) and body.get("error") == "forbidden")
        st, body = req("/rest/v1/rpc/quiz_stats", self.ttok, {"p_quiz_set_id": QUIZ_SET})
        self.check("教師は quiz_stats を呼べる", isinstance(body, dict) and "attempts" in body)

    def test_04_scoring(self):
        self._require_tokens()
        print("\n=== 4. 採点の正しさ（正解は1番目/2番目が半々＝全問「1番目」なら5/10） ===")
        # ★2026-09-06 に選択肢が2個固定でなくなり、答えは 'a'/'b' から「何番目か」へ変わった
        st, qs = req(f"/rest/v1/questions?select=id&quiz_set_id=eq.{QUIZ_SET}", self.stok)
        st, r = req("/rest/v1/rpc/submit_attempt", self.stok,
                    {"p_quiz_set_id": QUIZ_SET, "p_answers": {q["id"]: 1 for q in qs}})
        self.check("採点が正しい（全問「1番目」提出=5/10）", isinstance(r, dict) and r.get("score") == 5 and r.get("total") == 10)
        # 範囲外の番号は「未回答」扱いにする（1問の壊れた値で提出全体を落とさない）
        st, r2 = req("/rest/v1/rpc/submit_attempt", self.stok,
                     {"p_quiz_set_id": QUIZ_SET, "p_answers": {q["id"]: 99 for q in qs}})
        self.check("範囲外の番号は未回答あつかい（提出そのものは通る）",
                    isinstance(r2, dict) and r2.get("score") == 0 and r2.get("total") == 10, str(r2)[:80])

    def test_05_attempts_isolation(self):
        self._require_tokens()
        print("\n=== 5. 他人の解答は見えない ===")
        st, mine = req("/rest/v1/attempts?select=student_id", self.stok)
        uids = {a["student_id"] for a in mine} if isinstance(mine, list) else set()
        self.check("学生のattempts一覧に自分以外が混ざらない", len(uids) <= 1)

    def test_06_write_protection(self):
        self._require_tokens()
        print("\n=== 6. 書き込みの直接改ざん防止 ===")
        st, _ = req("/rest/v1/attempts", self.stok, {"quiz_set_id": QUIZ_SET, "score": 10, "total": 10,
                                                       "student_id": "00000000-0000-0000-0000-000000000000"})
        self.check("学生は attempts に直接insertできない（満点偽造不可）", st in (401, 403))

    def test_07_surveys(self):
        self._require_tokens()
        print("\n=== 7. アンケート（survey_responses） ===")
        UP = {"Prefer": "resolution=merge-duplicates"}
        st, _ = req("/rest/v1/survey_responses?on_conflict=student_id,survey_key", self.stok,
                    {"survey_key": "test_rls", "answers": {"job": "テスト"}}, UP)
        self.check("学生はアンケートを提出できる（本人扱いで保存）", st in (200, 201))
        st, _ = req("/rest/v1/survey_responses", self.stok,
                    {"student_id": "00000000-0000-0000-0000-000000000000",
                     "survey_key": "test_rls_fake", "answers": {}})
        self.check("学生は他人名義でアンケートを出せない", st in (401, 403))
        st2tok = login("s002", "sakura24")
        st, rows = req("/rest/v1/survey_responses?select=student_id&survey_key=eq.test_rls", st2tok)
        self.check("学生は他人のアンケート回答を読めない", rows == [])
        st, rows = req("/rest/v1/survey_responses?select=student_id&survey_key=eq.test_rls", self.ttok)
        self.check("教師は全員のアンケート回答を読める", isinstance(rows, list) and len(rows) >= 1)


if __name__ == "__main__":
    if "--live" in sys.argv:
        sys.argv.remove("--live")
    unittest.main(verbosity=2)
