# -*- coding: utf-8 -*-
"""選択肢が2個固定でなくなったことの回帰テスト — scg-student-portal

なぜ要るか: ヨリソルの実データは 3〜4択が主で、公開中の設問はすべて4択だった。
2択専用のままだと1問も移せない。ここが崩れると、移行そのものが止まる。

★このテストは**ダミーの設問**を自分で作って試し、最後に消す。
  本物の設問（つなぐ日本語）は許諾の確認前なので、DBに入れない。

引数なし … コード・SQL の構造と、並べ替えの決まり方（Node で実行）を見る（DB不要）
--live   … 教師アカウントでダミーの3択・4択を作り、読み取り・保存・採点を実際に試して消す
           ★先に db/2026-09-06_multi_choice.sql を流しておくこと

使い方: py -X utf8 tests\test_choices.py [--live]
"""
import sys, io, os, re, json, subprocess
import urllib.request, urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL = os.path.join(ROOT, "db", "2026-09-06_multi_choice.sql")
INDEX = os.path.join(ROOT, "src", "index.html")
IMPORTER = os.path.join(ROOT, "scripts", "import_yorisol.py")

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("  OK  " if cond else "  NG  ") + name + (f"  ({detail})" if detail and not cond else ""))

def read(p):
    return io.open(p, encoding="utf-8").read() if os.path.exists(p) else ""

sql, idx, imp = read(SQL), read(INDEX), read(IMPORTER)
low = sql.lower()

# ══════════════════════════════════════════════════════════════════
print("=== 1. 表の作り（DB不要）===")
check("移行SQLがある", bool(sql), SQL)
check("選択肢の表がある（主キーが 設問・番号）",
      re.search(r"primary key\s*\(\s*question_id\s*,\s*idx\s*\)", low) is not None)
check("番号に上限がある（際限なく増やせない）", "idx between 1 and 12" in low)
check("空の選択肢を入れられない", "length(btrim(label)) > 0" in low)
_ct = re.search(r"create table (?:if not exists )?public\.question_choices[\s\S]*?\n\);", low)
check("選択肢の表の定義が読める", _ct is not None)
check("★正解は選択肢の表に入れない（学生に見せる表と分ける）",
      _ct is not None and "correct" not in _ct.group(0))
check("★正解は実在する選択肢を指す（外部キー）",
      "question_answers_correct_idx_fkey" in low and "references public.question_choices(question_id, idx)" in low)
check("RLS が有効", "alter table public.question_choices enable row level security" in low)
check("★読み取りは to authenticated（付けないと未ログインでも選択肢が読める）",
      re.search(r'create policy "read choices of open quiz"[\s\S]{0,120}to authenticated', low) is not None)
check("教師の管理ポリシーも to authenticated",
      re.search(r'create policy "teacher manage choices"[\s\S]{0,120}to authenticated', low) is not None)
check("未ログインから表そのものを取り上げている", "revoke all on table public.question_choices from anon" in low)
check("旧2列を落としている", "drop column if exists choice_a" in low and "drop column if exists choice_b" in low)
check("提出済みの解答も番号に移している", "alter column chosen type smallint" in low)
check("★範囲外の番号は未回答あつかい（例外にせず提出を通す）", "v_chosen := null" in low)

print("\n=== 2. 画面側（DB不要）===")
check("選択肢を描き込む入れ物がある", 'id="choices"' in idx)
check("旧・固定2ボタンが残っていない", 'id="ch-a"' not in idx and 'id="ch-b"' not in idx)
check("選択肢を別表からまとめて取っている", "question_choices(idx,label)" in idx)
check("選択肢が足りない設問は出さない", "q.choices.length >= 2" in idx)
check("並べ替えの関数がある", "function choiceOrder" in idx)
check("★種は「学生 + 設問」（設問ごとに違う並び）",
      re.search(r'seedFrom\(\s*me\s*\+\s*.#.\s*\+\s*q\.id\s*\)', idx) is not None)
check("★保存するのは元の番号で、画面の位置ではない",
      "draftRecord(q.id, idx)" in idx and "// ★元の番号。画面の位置ではない" in idx)
check("結果画面も番号で正解を引く", "q.choices.find(c=>c.idx===item.correct)" in idx)
check("選んでいない状態を undefined で判定（0 と混同しない）", "chosen === undefined" in idx)

print("\n=== 3. 変換スクリプト（DB不要）===")
check("2個固定をやめている", "MAX_CHOICES" in imp and "choices" in imp)
check("正解列の既定が correct_idx", 'DEFAULT_ANSWER_COL = "correct_idx"' in imp)
check("questions に選択肢を書かない", "choice_a" not in imp and "choice_b" not in imp)
check("★選択肢を入れてから正解を入れる（外部キーの順序）",
      imp.index("insert into question_choices") < imp.index("insert into question_answers("))

# 並べ替えが決まった順になるか、Node で実際に動かす
js = ""
for fn in ("seedFrom", "rngFrom"):
    m = re.search(r"function " + fn + r"\([\s\S]*?\n\}", idx)
    if m:
        js += m.group(0) + "\n"
m = re.search(r"function choiceOrder\([\s\S]*?\n\}", idx)
if m:
    js += m.group(0) + "\n"
js += """
var api = { profile: null };
var Q = { id:"q-1", choices:[{idx:1},{idx:2},{idx:3},{idx:4}] };
var Q2 = { id:"q-2", choices:[{idx:1},{idx:2},{idx:3},{idx:4}] };
function ord(o, who){ api.profile = {id: who}; return choiceOrder(o).join(","); }
var A1 = ord(Q,"stu-A"), A2 = ord(Q,"stu-A"), B1 = ord(Q,"stu-B"), A_q2 = ord(Q2,"stu-A");
var seen = {}; for (var k=0;k<200;k++) seen[ord(Q,"s"+k)] = 1;
console.log(JSON.stringify({A1:A1, A2:A2, B1:B1, A_q2:A_q2,
  sorted: A1.split(",").map(Number).sort().join(","), variety:Object.keys(seen).length}));
"""
tmp = os.path.join(ROOT, "tmp_choice_check.js")
io.open(tmp, "w", encoding="utf-8").write(js)
r = {}
try:
    out = subprocess.run(["node", tmp], capture_output=True, text=True, timeout=60)
    if out.stdout.strip():
        r = json.loads(out.stdout.strip().splitlines()[-1])
    else:
        print("  --  Node の出力が空:", out.stderr.strip()[:200])
except Exception as e:
    print("  --  Node で実行できなかった:", e)
finally:
    if os.path.exists(tmp):
        os.remove(tmp)

if r:
    print("\n=== 4. 並べ替えの決まり方（Node で実行）===")
    check("★同じ学生・同じ設問なら いつ開いても同じ並び", r["A1"] == r["A2"], r.get("A1"))
    check("★学生が違えば並びが違う", r["A1"] != r["B1"])
    check("設問が違えば並びも違う", r["A1"] != r["A_q2"])
    check("選択肢が消えたり増えたりしない", r["sorted"] == "1,2,3,4", r.get("sorted"))
    check("200人ぶんで十分ばらける（10通り以上）", r["variety"] >= 10, str(r.get("variety")))

# ══════════════════════════════════════════════════════════════════
if "--live" in sys.argv:
    print("\n=== 5. 本物のDBで往復（--live・ダミー設問を作って消す）===")
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

    def login(no, pw):
        st, b = req("/auth/v1/token?grant_type=password",
                    body={"email": f"{no}@stu.scg-portal.jp", "password": pw})
        return b.get("access_token") if st == 200 and b else None

    ttok = login("t001", "sensei-scg-2026")
    stok = login("l149", "sakura24")
    check("教師・学生でログインできる", bool(ttok) and bool(stok))

    set_id = None
    if ttok and stok:
        # ---- ダミーの回を作る（4択1問・3択1問）----
        st, s = req("/rest/v1/quiz_sets", ttok,
                    {"title": "検査用ダミー（自動で消えます）", "lesson": "test", "is_open": True},
                    extra={"Prefer": "return=representation"})
        set_id = s[0]["id"] if st in (200, 201) and s else None
        check("ダミーの回を作れる", bool(set_id), f"{st} {s}")

    if set_id:
        try:
            qids = []
            for seq, n in ((1, 4), (2, 3)):
                st, q = req("/rest/v1/questions", ttok,
                            {"quiz_set_id": set_id, "seq": seq, "prompt": f"ダミー設問{seq}"},
                            extra={"Prefer": "return=representation"})
                qid = q[0]["id"]; qids.append((qid, n))
                req("/rest/v1/question_choices", ttok,
                    [{"question_id": qid, "idx": i, "label": f"えらぶ{i}"} for i in range(1, n + 1)])
                req("/rest/v1/question_answers", ttok, {"question_id": qid, "correct_idx": n})
            check("4択・3択の設問を作れる", len(qids) == 2)

            st, got = req(f"/rest/v1/questions?select=id,seq,question_choices(idx,label)"
                          f"&quiz_set_id=eq.{set_id}&order=seq", stok)
            counts = sorted(len(g["question_choices"]) for g in (got or []))
            check("★学生が4択・3択をそのまま読める", counts == [3, 4], str(counts))

            st, leak = req(f"/rest/v1/question_answers?select=correct_idx"
                           f"&question_id=eq.{qids[0][0]}", stok)
            check("★学生に正解は見えない", st == 200 and (leak or []) == [], str(leak))

            st, anon_c = req(f"/rest/v1/question_choices?select=idx&question_id=eq.{qids[0][0]}")
            check("★未ログインでは選択肢を読めない", st in (401, 403) or (anon_c or []) == [], f"{st} {anon_c}")

            # ---- 途中保存（範囲の検査つき）----
            q4 = qids[0][0]
            st, r4 = req("/rest/v1/rpc/save_draft", stok,
                         {"p_quiz_set_id": set_id, "p_question_id": q4, "p_chosen": 4, "p_client_seq": 1})
            check("4番目を保存できる（2択では不可能だった）", st == 200 and r4 and r4.get("ok"), f"{st} {r4}")
            st, _ = req("/rest/v1/rpc/save_draft", stok,
                        {"p_quiz_set_id": set_id, "p_question_id": q4, "p_chosen": 5, "p_client_seq": 2})
            check("★存在しない番号は弾く（4択に5番目は無い）", st >= 400, str(st))
            q3 = qids[1][0]
            st, _ = req("/rest/v1/rpc/save_draft", stok,
                        {"p_quiz_set_id": set_id, "p_question_id": q3, "p_chosen": 4, "p_client_seq": 1})
            check("★設問ごとに範囲を見ている（3択に4番目は無い）", st >= 400, str(st))

            # ---- 採点 ----
            st, res = req("/rest/v1/rpc/submit_attempt", stok,
                          {"p_quiz_set_id": set_id, "p_answers": {q4: 4, q3: 3}, "p_duration_ms": 1000})
            check("★4択・3択が正しく採点される（両方正解=2/2）",
                  isinstance(res, dict) and res.get("score") == 2 and res.get("total") == 2, str(res)[:100])
            st, res2 = req("/rest/v1/rpc/submit_attempt", stok,
                           {"p_quiz_set_id": set_id, "p_answers": {q4: 1, q3: 3}, "p_duration_ms": 1000})
            check("外した分は加点されない（1/2）",
                  isinstance(res2, dict) and res2.get("score") == 1, str(res2)[:100])

            # ---- 学生は選択肢を書き換えられない ----
            st, _ = req("/rest/v1/question_choices", stok,
                        {"question_id": q4, "idx": 9, "label": "わりこみ"})
            check("★学生は選択肢を追加できない", st in (401, 403), str(st))
            # ★PATCH は「拒否」でも「0行に当たった」でも 204 を返すので、
            #   状態コードでは判定できない。実際に値が変わっていないかを読み戻して見る。
            st, _ = req(f"/rest/v1/question_choices?question_id=eq.{q4}&idx=eq.1", stok,
                        {"label": "書き換え"}, method="PATCH")
            st2, after = req(f"/rest/v1/question_choices?select=label"
                             f"&question_id=eq.{q4}&idx=eq.1", ttok)
            check("★学生が書き換えても中身は変わらない",
                  st2 == 200 and after and after[0]["label"] == "えらぶ1", f"{st} → {after}")
        finally:
            # ---- 片付け（回を消せば設問・選択肢・解答も連鎖で消える）----
            req(f"/rest/v1/quiz_sets?id=eq.{set_id}", ttok, method="DELETE")
            st, left = req(f"/rest/v1/quiz_sets?select=id&id=eq.{set_id}", ttok)
            check("ダミーを消せた（残さない）", (left or []) == [], str(left))
else:
    print("\n（--live を付けるとダミー設問を作って本物のDBで試します。"
          "先に db\\2026-09-06_multi_choice.sql を流すこと）")

print(f"\n結果: {len(passed)} OK / {len(failed)} NG")
if failed:
    print("失敗:", *["  - " + f for f in failed], sep="\n")
sys.exit(1 if failed else 0)
