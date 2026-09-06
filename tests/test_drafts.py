# -*- coding: utf-8 -*-
"""回答の途中保存（下書き）の回帰テスト — scg-student-portal

なぜ要るか: 校内Wi-Fiは落ちる前提で、「解いたのに消えた」を出さないための仕掛け。
壊れても画面は普通に動いてしまい、事故が起きるまで気づけないので、機械で見張る。

引数なし … コードとSQLの構造だけを見る（DB不要・いつでも走る）
--live   … デモのDBに対して、保存・読み戻し・二重送信・順序・他人の下書きを実際に試す
           ★先に db/2026-09-06_attempt_drafts.sql を流しておくこと

使い方: py -X utf8 tests\test_drafts.py [--live]
"""
import sys, io, os, re, json, time
import urllib.request, urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL = os.path.join(ROOT, "db", "2026-09-06_attempt_drafts.sql")
INDEX = os.path.join(ROOT, "src", "index.html")
I18N = os.path.join(ROOT, "src", "assets", "i18n.js")

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  ({detail})" if detail and not cond else ""))

def read(p):
    return io.open(p, encoding="utf-8").read() if os.path.exists(p) else ""

# ══════════════════════════════════════════════════════════════════
print("=== 1. SQL の作り（DB不要）===")
sql = read(SQL)
check("移行SQLがある", bool(sql), SQL)
low = sql.lower()
check("下書きの主キーが (学生, 回, 設問)＝同じ回答が二度届いても行が増えない",
      re.search(r"primary key\s*\(\s*student_id\s*,\s*quiz_set_id\s*,\s*question_id\s*\)", low) is not None)
check("★古い回答で新しい回答を上書きしないガードがある",
      re.search(r"where\s+excluded\.client_seq\s*>=\s*d\.client_seq", low) is not None)
check("RLS が有効", "enable row level security" in low)
check("★学生が下書きテーブルへ直接 書けない（insert/update/delete のポリシーを作っていない）",
      not re.search(r"for\s+(insert|update|delete)", low))
check("自分の下書きだけ読める", "student_id = auth.uid()" in low)
check("教師は読める（授業中に進み具合を見るため）", "is_teacher()" in low)
check("save_draft は security definer", re.search(r"function public\.save_draft.*?security definer", low, re.S) is not None)
check("save_draft の search_path が固定（乗っ取り対策）",
      re.search(r"function public\.save_draft.*?set search_path\s*=", low, re.S) is not None)
check("別の回の設問を混ぜて保存できない", "does not belong to this quiz set" in sql)
check("公開されていない回には保存させない", "is not open" in sql)
check("提出後に下書きを捨てる関数がある", "function public.discard_drafts" in low)
check("実行権限は authenticated だけ（anon には配らない）",
      low.count("grant execute") >= 2 and "to anon" not in low)
check("★anon から明示的に取り上げている（revoke ... from public だけでは付き直す）",
      low.count("from anon") >= 2)

# ══════════════════════════════════════════════════════════════════
print("\n=== 2. 画面側の作り（DB不要）===")
idx = read(INDEX)
check("下書きの関数がそろっている",
      all(k in idx for k in ("draftRecord", "draftFlush", "draftWriteLocal", "draftClearAll", "draftKey")))
rec = re.search(r"function draftRecord\(.*?\n\}", idx, re.S)
rec = rec.group(0) if rec else ""
check("★端末へ書くのが先、送信はあと（通信が死んでいても消えない）",
      rec.find("draftWriteLocal") != -1 and rec.find("draftWriteLocal") < rec.find("draftFlush"))
check("答えを選ぶと下書きに入る（旧: answers[...] へ直接代入 ではない）",
      'draftRecord(questions[cur].id,"a")' in idx and "answers[questions[cur].id]=\"a\"" not in idx)
check("下書きの鍵に学生の id が入る（共用端末で他人の分を拾わない）",
      re.search(r"function draftKey[\s\S]{0,240}profile[\s\S]{0,80}id", idx) is not None)
check("ログアウトで下書きを消す", "draftClearAll(); api.logout()" in idx)
check("提出できたら下書きを捨てる", "discard_drafts" in idx and "draftClearLocal(quizSet.id)" in idx)
check("提出の前に未送信ぶんを送り切る",
      re.search(r"await draftFlush\(\);[\s\S]{0,200}submit_attempt", idx) is not None)
check("通信が戻ったら自動で送る", 'addEventListener("online"' in idx and "visibilitychange" in idx)
check("続きから再開する（サーバーの下書きを読む）", "/rest/v1/attempt_drafts?select=" in idx)
check("下書きが読めなくても受験は始められる（読み込み失敗を握りつぶす）",
      re.search(r"attempt_drafts[\s\S]{0,200}catch\(e\)\{\s*srv\s*=\s*\[\]", idx) is not None)
check("未回答の最初の問題へ戻る", "firstBlank" in idx)
check("保存の表示が提出と別の言葉になっている（q.sv.* を使う）", "q.sv.saved" in idx and "q.sv.pend" in idx)

print("\n=== 3. 文言（DB不要）===")
i18 = read(I18N)
for k in ("q.sv.saving", "q.sv.saved", "q.sv.pend", "q.sv.resumed"):
    check(f"{k} が日本語と英語の両方にある", i18.count('"' + k + '"') >= 2)
check("学生向けの文言がやさしい日本語（漢字だけの塊にしない）", "ほぞん" in i18)

# ══════════════════════════════════════════════════════════════════
if "--live" in sys.argv:
    print("\n=== 4. 本物のDBで往復（--live）===")
    BASE = "https://egdcbxzpgwenmfabpodd.supabase.co"
    ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVnZGNieHpwZ3dlbm1mYWJwb2RkIiwi"
            "cm9sZSI6ImFub24iLCJpYXQiOjE3ODgzNTcwNDYsImV4cCI6MjEwMzkzMzA0Nn0.m908C67Nh4KsYnH_LWvP4wAjOtxI79hhE-BKS1MCxX0")
    def req(path, token=None, body=None, method=None, extra=None):
        headers = {"apikey": ANON, "Content-Type": "application/json"}
        if extra: headers.update(extra)
        if token: headers["Authorization"] = "Bearer " + token
        data = json.dumps(body).encode() if body is not None else None
        rq = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(rq, timeout=20) as res:
                raw = res.read().decode()
                return res.status, (json.loads(raw) if raw.strip() else None)
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            return e.code, (json.loads(raw) if raw.strip() else None)

    def login(no, pw="sakura24"):
        st, b = req("/auth/v1/token?grant_type=password",
                    body={"email": f"{no}@stu.scg-portal.jp", "password": pw})
        return b.get("access_token") if st == 200 and b else None

    # 負荷試験用の2人を使う（学生画面の一覧には出ない）
    tokA, tokB = login("l149"), login("l150")
    check("検査用の学生2人でログインできる", bool(tokA) and bool(tokB))
    if tokA and tokB:
        st, sets = req("/rest/v1/quiz_sets?select=id&is_open=eq.true&limit=1", tokA)
        qs = sets[0]["id"] if st == 200 and sets else None
        check("公開中の回がある", bool(qs), str(st))
        st, qlist = req(f"/rest/v1/questions?select=id&quiz_set_id=eq.{qs}&order=seq&limit=2", tokA)
        qids = [q["id"] for q in (qlist or [])]
        check("設問が2問以上取れる", len(qids) >= 2)

        if qs and len(qids) >= 2:
            req("/rest/v1/rpc/discard_drafts", tokA, {"p_quiz_set_id": qs})   # 前回の残りを掃除
            req("/rest/v1/rpc/discard_drafts", tokB, {"p_quiz_set_id": qs})

            st, r = req("/rest/v1/rpc/save_draft", tokA,
                        {"p_quiz_set_id": qs, "p_question_id": qids[0], "p_chosen": "a", "p_client_seq": 1})
            check("1問ぶん保存できる", st == 200 and r and r.get("ok") is True, f"{st} {r}")

            st, back = req(f"/rest/v1/attempt_drafts?select=question_id,chosen,client_seq&quiz_set_id=eq.{qs}", tokA)
            check("自分の下書きを読み戻せる", st == 200 and len(back or []) == 1 and back[0]["chosen"] == "a", str(back))

            # 二重送信: 同じものを2回
            req("/rest/v1/rpc/save_draft", tokA,
                {"p_quiz_set_id": qs, "p_question_id": qids[0], "p_chosen": "a", "p_client_seq": 1})
            st, back = req(f"/rest/v1/attempt_drafts?select=question_id&quiz_set_id=eq.{qs}", tokA)
            check("★同じ回答が二度届いても行が増えない", len(back or []) == 1, str(len(back or [])))

            # 新しい回答 → そのあと古い回答が遅れて届く
            req("/rest/v1/rpc/save_draft", tokA,
                {"p_quiz_set_id": qs, "p_question_id": qids[0], "p_chosen": "b", "p_client_seq": 5})
            req("/rest/v1/rpc/save_draft", tokA,
                {"p_quiz_set_id": qs, "p_question_id": qids[0], "p_chosen": "a", "p_client_seq": 2})
            st, back = req(f"/rest/v1/attempt_drafts?select=chosen,client_seq&quiz_set_id=eq.{qs}", tokA)
            check("★遅れて届いた古い回答で新しい回答が消えない",
                  back and back[0]["chosen"] == "b" and back[0]["client_seq"] == 5, str(back))

            # 他人の下書きは見えない
            st, seen = req(f"/rest/v1/attempt_drafts?select=question_id&quiz_set_id=eq.{qs}", tokB)
            check("★他の学生の下書きは見えない", st == 200 and (seen or []) == [], str(seen))

            # テーブルへ直接書けない
            st, _ = req("/rest/v1/attempt_drafts", tokA,
                        {"quiz_set_id": qs, "question_id": qids[1], "chosen": "a"})
            check("★学生はテーブルへ直接 insert できない", st in (401, 403), str(st))

            # 別の回の設問を混ぜられない
            st, other = req(f"/rest/v1/questions?select=id&quiz_set_id=neq.{qs}&limit=1", tokA)
            if other:
                st, _ = req("/rest/v1/rpc/save_draft", tokA,
                            {"p_quiz_set_id": qs, "p_question_id": other[0]["id"], "p_chosen": "a", "p_client_seq": 1})
                check("★別の回の設問は保存できない", st >= 400, str(st))
            else:
                print("  －  別の回が無いので「混ぜられない」検査は飛ばした")

            # 未ログインでは呼べない
            st, _ = req("/rest/v1/rpc/save_draft", None,
                        {"p_quiz_set_id": qs, "p_question_id": qids[0], "p_chosen": "a", "p_client_seq": 1})
            check("★未ログイン(anon)では保存できない", st in (401, 403, 404), str(st))
            st, _ = req("/rest/v1/rpc/discard_drafts", None, {"p_quiz_set_id": qs})
            check("★未ログイン(anon)では下書きを消せない", st in (401, 403, 404), str(st))

            # 片付け
            st, n = req("/rest/v1/rpc/discard_drafts", tokA, {"p_quiz_set_id": qs})
            check("提出後の片付けで下書きが消える", st == 200 and isinstance(n, int) and n >= 1, f"{st} {n}")
            st, back = req(f"/rest/v1/attempt_drafts?select=question_id&quiz_set_id=eq.{qs}", tokA)
            check("消えたことを読み戻しで確かめた", (back or []) == [], str(back))
else:
    print("\n（--live を付けると本物のDBで往復して確かめます。先に db\\2026-09-06_attempt_drafts.sql を流すこと）")

print(f"\n結果: {len(passed)} OK / {len(failed)} NG")
if failed:
    print("⛔ 失敗:", *["  - " + f for f in failed], sep="\n")
sys.exit(1 if failed else 0)
