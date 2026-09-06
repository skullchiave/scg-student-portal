# -*- coding: utf-8 -*-
"""セキュリティ回帰テスト — scg-student-portal

「安全性の担保」を毎回機械的に再検証するためのテスト。スキーマやポリシーを
変更したら必ず実行すること。全部 PASS しない状態でデプロイしてはいけない。

使い方: python tests/test_security.py
依存:   標準ライブラリのみ
"""
import sys, json, io
import urllib.request
import urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "https://egdcbxzpgwenmfabpodd.supabase.co"
ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVnZGNieHpwZ3dlbm1mYWJwb2RkIiwi"
        "cm9sZSI6ImFub24iLCJpYXQiOjE3ODgzNTcwNDYsImV4cCI6MjEwMzkzMzA0Nn0.m908C67Nh4KsYnH_LWvP4wAjOtxI79hhE-BKS1MCxX0")
QUIZ_SET = "c75def6b-7623-4d86-8540-0c5b081ecf7c"

passed, failed = [], []

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

def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  ({detail})" if detail and not cond else ""))

print("=== セキュリティ回帰テスト ===")

# 0. 前提: ログイン
stok = login("s001", "sakura24")
ttok = login("t001", "sensei-scg-2026")
check("学生ログインできる", stok is not None)
check("教師ログインできる", ttok is not None)
if not stok or not ttok:
    print("前提が崩れているため中断"); sys.exit(1)

# 1. 認証まわり
check("誤ったパスワードは拒否される", login("s001", "wrong-pass") is None)
st, _ = req("/rest/v1/quiz_sets?select=id")
check("未ログインではデータを読めない", st in (200, 401) and (st == 401 or _ == []))

# 2. 正解データの遮断（正解は question_answers テーブルに分離されている）
st, body = req("/rest/v1/question_answers?select=*", stok)
check("学生は question_answers(正解テーブル)を読めない", body == [])
st, body = req("/rest/v1/questions?select=*&limit=1", stok)
check("学生は questions(問題文)を読める", st == 200 and len(body) == 1)
check("questions に正解列が存在しない（構造で保証）", body and "correct" not in body[0])
st, body = req("/rest/v1/question_answers?select=*", ttok)
check("教師は question_answers を読める", st == 200 and len(body) > 0)

# 3. 集計APIの権限
st, body = req("/rest/v1/rpc/quiz_stats", stok, {"p_quiz_set_id": QUIZ_SET})
check("学生は quiz_stats を呼べない(forbidden)", isinstance(body, dict) and body.get("error") == "forbidden")
st, body = req("/rest/v1/rpc/quiz_stats", ttok, {"p_quiz_set_id": QUIZ_SET})
check("教師は quiz_stats を呼べる", isinstance(body, dict) and "attempts" in body)

# 4. 採点の正しさ（正解は1番目/2番目が半々＝全問「1番目」なら5/10）
#    ★2026-09-06 に選択肢が2個固定でなくなり、答えは 'a'/'b' から「何番目か」へ変わった
st, qs = req(f"/rest/v1/questions?select=id&quiz_set_id=eq.{QUIZ_SET}", stok)
st, r = req("/rest/v1/rpc/submit_attempt", stok,
            {"p_quiz_set_id": QUIZ_SET, "p_answers": {q["id"]: 1 for q in qs}})
check("採点が正しい（全問「1番目」提出=5/10）", isinstance(r, dict) and r.get("score") == 5 and r.get("total") == 10)
# 範囲外の番号は「未回答」扱いにする（1問の壊れた値で提出全体を落とさない）
st, r2 = req("/rest/v1/rpc/submit_attempt", stok,
             {"p_quiz_set_id": QUIZ_SET, "p_answers": {q["id"]: 99 for q in qs}})
check("範囲外の番号は未回答あつかい（提出そのものは通る）",
      isinstance(r2, dict) and r2.get("score") == 0 and r2.get("total") == 10, str(r2)[:80])

# 5. 他人の解答は見えない
st, mine = req("/rest/v1/attempts?select=student_id", stok)
uids = {a["student_id"] for a in mine} if isinstance(mine, list) else set()
check("学生のattempts一覧に自分以外が混ざらない", len(uids) <= 1)

# 6. 書き込みの直接改ざん防止
st, _ = req("/rest/v1/attempts", stok, {"quiz_set_id": QUIZ_SET, "score": 10, "total": 10,
                                         "student_id": "00000000-0000-0000-0000-000000000000"})
check("学生は attempts に直接insertできない（満点偽造不可）", st in (401, 403))

# 7. アンケート（survey_responses）
UP = {"Prefer": "resolution=merge-duplicates"}
st, _ = req("/rest/v1/survey_responses?on_conflict=student_id,survey_key", stok,
            {"survey_key": "test_rls", "answers": {"job": "テスト"}}, UP)
check("学生はアンケートを提出できる（本人扱いで保存）", st in (200, 201))
st, _ = req("/rest/v1/survey_responses", stok,
            {"student_id": "00000000-0000-0000-0000-000000000000",
             "survey_key": "test_rls_fake", "answers": {}})
check("学生は他人名義でアンケートを出せない", st in (401, 403))
st2tok = login("s002", "sakura24")
st, rows = req("/rest/v1/survey_responses?select=student_id&survey_key=eq.test_rls", st2tok)
check("学生は他人のアンケート回答を読めない", rows == [])
st, rows = req("/rest/v1/survey_responses?select=student_id&survey_key=eq.test_rls", ttok)
check("教師は全員のアンケート回答を読める", isinstance(rows, list) and len(rows) >= 1)

print(f"\n結果: {len(passed)} PASS / {len(failed)} FAIL")
sys.exit(0 if not failed else 1)
