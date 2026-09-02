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

def req(path, token=None, body=None):
    headers = {"apikey": ANON, "Content-Type": "application/json"}
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

# 2. 正解データの遮断
st, body = req("/rest/v1/questions?select=correct", stok)
check("学生は questions テーブル(正解列)を読めない", body == [])
st, body = req("/rest/v1/questions_public?select=*&limit=1", stok)
check("学生は questions_public を読める", st == 200 and len(body) == 1)
check("questions_public に正解列が無い", body and "correct" not in body[0])

# 3. 集計APIの権限
st, body = req("/rest/v1/rpc/quiz_stats", stok, {"p_quiz_set_id": QUIZ_SET})
check("学生は quiz_stats を呼べない(forbidden)", isinstance(body, dict) and body.get("error") == "forbidden")
st, body = req("/rest/v1/rpc/quiz_stats", ttok, {"p_quiz_set_id": QUIZ_SET})
check("教師は quiz_stats を呼べる", isinstance(body, dict) and "attempts" in body)

# 4. 採点の正しさ（正解はa/b半々=全問aなら5/10）
st, qs = req(f"/rest/v1/questions_public?select=id&quiz_set_id=eq.{QUIZ_SET}", stok)
st, r = req("/rest/v1/rpc/submit_attempt", stok,
            {"p_quiz_set_id": QUIZ_SET, "p_answers": {q["id"]: "a" for q in qs}})
check("採点が正しい（全問a提出=5/10）", isinstance(r, dict) and r.get("score") == 5 and r.get("total") == 10)

# 5. 他人の解答は見えない
st, mine = req("/rest/v1/attempts?select=student_id", stok)
uids = {a["student_id"] for a in mine} if isinstance(mine, list) else set()
check("学生のattempts一覧に自分以外が混ざらない", len(uids) <= 1)

# 6. 書き込みの直接改ざん防止
st, _ = req("/rest/v1/attempts", stok, {"quiz_set_id": QUIZ_SET, "score": 10, "total": 10,
                                         "student_id": "00000000-0000-0000-0000-000000000000"})
check("学生は attempts に直接insertできない（満点偽造不可）", st in (401, 403))

print(f"\n結果: {len(passed)} PASS / {len(failed)} FAIL")
sys.exit(0 if not failed else 1)
