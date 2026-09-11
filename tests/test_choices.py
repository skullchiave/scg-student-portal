# -*- coding: utf-8 -*-
"""選択肢が2個固定でなくなったことの回帰テスト — scg-student-portal

なぜ要るか: ヨリソルの実データは 3〜4択が主で、公開中の設問はすべて4択だった。
2択専用のままだと1問も移せない。ここが崩れると、移行そのものが止まる。

★このテストは**ダミーの設問**を自分で作って試し、最後に消す。
  検査はダミーの設問で行う（本物を入れて消す形にしない＝消し損ねが残骸になるため）。
  ※ 設問の著作権は 2026-09-11 に決着（校長・部門長の見解）。入れられない理由は無くなったが、
    **検査はダミーで行う**方針は変えない。

コード・SQL の構造と、並べ替えの決まり方（Node で実行）は DB不要・常に実行。
DBへ往復する部分（教師アカウントでダミーの3択・4択を作り、読み取り・保存・採点を
実際に試して消す）は既定ではskip。環境変数 SP_LIVE=1 か --live 引数を付けたときだけ動く。
★先に db/2026-09-06_multi_choice.sql を流しておくこと。
DBに接続できない環境では、有効化していてもskipへ倒れる（FAILにはしない）。

使い方: py -X utf8 tests\\test_choices.py [--live]
"""
import sys, io, os, re, json, subprocess, unittest
import urllib.request, urllib.error

# discoverで他のtest_*.pyと同じプロセスに同居する時、全員が無条件に
# sys.stdout を包み直すと、先に包んだ方のラッパーがGCで下敷きのbufferを
# 道連れに閉じてしまい "I/O operation on closed file" になる。
# すでにutf-8ならそのまま使う（-X utf8 実行なら通常ここに来る）。
if getattr(sys.stdout, "encoding", "").lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL = os.path.join(ROOT, "db", "2026-09-06_multi_choice.sql")
INDEX = os.path.join(ROOT, "src", "index.html")
IMPORTER = os.path.join(ROOT, "scripts", "import_yorisol.py")

LIVE = os.environ.get("SP_LIVE") == "1" or "--live" in sys.argv

BASE = "https://egdcbxzpgwenmfabpodd.supabase.co"
ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVnZGNieHpwZ3dlbm1mYWJwb2RkIiwi"
        "cm9sZSI6ImFub24iLCJpYXQiOjE3ODgzNTcwNDYsImV4cCI6MjEwMzkzMzA0Nn0.m908C67Nh4KsYnH_LWvP4wAjOtxI79hhE-BKS1MCxX0")


def read(p):
    return io.open(p, encoding="utf-8").read() if os.path.exists(p) else ""


class TestChoicesStructure(unittest.TestCase):
    """表・画面・変換スクリプトの構造検査＋並べ替えの決まり方（DB不要・常に実行）"""

    def check(self, name, cond, detail=""):
        print(("  OK  " if cond else "  NG  ") + name + (f"  ({detail})" if detail and not cond else ""))
        with self.subTest(name=name):
            self.assertTrue(cond, detail or name)

    def test_01_sql_table(self):
        print("=== 1. 表の作り（DB不要）===")
        sql = read(SQL)
        low = sql.lower()
        self.check("移行SQLがある", bool(sql), SQL)
        self.check("選択肢の表がある（主キーが 設問・番号）",
              re.search(r"primary key\s*\(\s*question_id\s*,\s*idx\s*\)", low) is not None)
        self.check("番号に上限がある（際限なく増やせない）", "idx between 1 and 12" in low)
        self.check("空の選択肢を入れられない", "length(btrim(label)) > 0" in low)
        _ct = re.search(r"create table (?:if not exists )?public\.question_choices[\s\S]*?\n\);", low)
        self.check("選択肢の表の定義が読める", _ct is not None)
        self.check("★正解は選択肢の表に入れない（学生に見せる表と分ける）",
              _ct is not None and "correct" not in _ct.group(0))
        self.check("★正解は実在する選択肢を指す（外部キー）",
              "question_answers_correct_idx_fkey" in low and "references public.question_choices(question_id, idx)" in low)
        self.check("RLS が有効", "alter table public.question_choices enable row level security" in low)
        self.check("★読み取りは to authenticated（付けないと未ログインでも選択肢が読める）",
              re.search(r'create policy "read choices of open quiz"[\s\S]{0,120}to authenticated', low) is not None)
        self.check("教師の管理ポリシーも to authenticated",
              re.search(r'create policy "teacher manage choices"[\s\S]{0,120}to authenticated', low) is not None)
        self.check("未ログインから表そのものを取り上げている", "revoke all on table public.question_choices from anon" in low)
        self.check("旧2列を落としている", "drop column if exists choice_a" in low and "drop column if exists choice_b" in low)
        self.check("提出済みの解答も番号に移している", "alter column chosen type smallint" in low)
        self.check("★範囲外の番号は未回答あつかい（例外にせず提出を通す）", "v_chosen := null" in low)

    def test_02_screen(self):
        print("\n=== 2. 画面側（DB不要）===")
        idx = read(INDEX)
        self.check("選択肢を描き込む入れ物がある", 'id="choices"' in idx)
        self.check("旧・固定2ボタンが残っていない", 'id="ch-a"' not in idx and 'id="ch-b"' not in idx)
        self.check("選択肢を別表からまとめて取っている", "question_choices(idx,label)" in idx)
        self.check("選択肢が足りない設問は出さない", "q.choices.length >= 2" in idx)
        self.check("並べ替えの関数がある", "function choiceOrder" in idx)
        self.check("★種は「学生 + 設問」（設問ごとに違う並び）",
              re.search(r'seedFrom\(\s*me\s*\+\s*.#.\s*\+\s*q\.id\s*\)', idx) is not None)
        self.check("★保存するのは元の番号で、画面の位置ではない",
              "draftRecord(q.id, idx)" in idx and "// ★元の番号。画面の位置ではない" in idx)
        self.check("結果画面も番号で正解を引く", "q.choices.find(c=>c.idx===item.correct)" in idx)
        self.check("選んでいない状態を undefined で判定（0 と混同しない）", "chosen === undefined" in idx)

    def test_03_import_script(self):
        print("\n=== 3. 変換スクリプト（DB不要）===")
        imp = read(IMPORTER)
        self.check("2個固定をやめている", "MAX_CHOICES" in imp and "choices" in imp)
        self.check("正解列の既定が correct_idx", 'DEFAULT_ANSWER_COL = "correct_idx"' in imp)
        self.check("questions に選択肢を書かない", "choice_a" not in imp and "choice_b" not in imp)
        self.check("★選択肢を入れてから正解を入れる（外部キーの順序）",
              imp.index("insert into question_choices") < imp.index("insert into question_answers("))

    def test_04_shuffle_order(self):
        # 並べ替えが決まった順になるか、Node で実際に動かす
        idx = read(INDEX)
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

        if not r:
            self.skipTest("Node で並べ替えを実行できなかった（node 未導入などの環境要因）")

        print("\n=== 4. 並べ替えの決まり方（Node で実行）===")
        self.check("★同じ学生・同じ設問なら いつ開いても同じ並び", r["A1"] == r["A2"], r.get("A1"))
        self.check("★学生が違えば並びが違う", r["A1"] != r["B1"])
        self.check("設問が違えば並びも違う", r["A1"] != r["A_q2"])
        self.check("選択肢が消えたり増えたりしない", r["sorted"] == "1,2,3,4", r.get("sorted"))
        self.check("200人ぶんで十分ばらける（10通り以上）", r["variety"] >= 10, str(r.get("variety")))


@unittest.skipUnless(LIVE, "既定ではDB往復をskip。有効化するには環境変数 SP_LIVE=1 か --live 引数を付ける（先に db/2026-09-06_multi_choice.sql を流すこと）")
class TestChoicesLive(unittest.TestCase):
    """本物のDBでダミーの3択・4択を作って読み取り・保存・採点を確認する（後片付けまで含む）"""

    def check(self, name, cond, detail=""):
        print(("  OK  " if cond else "  NG  ") + name + (f"  ({detail})" if detail and not cond else ""))
        with self.subTest(name=name):
            self.assertTrue(cond, detail or name)

    def test_01_roundtrip(self):
        print("\n=== 5. 本物のDBで往復（--live・ダミー設問を作って消す）===")

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

        try:
            ttok = login("t001", "sensei-scg-2026")
            stok = login("l149", "sakura24")
        except (urllib.error.URLError, OSError) as e:
            self.skipTest(f"DBに接続できないためskip（{e}）")
            return
        self.check("教師・学生でログインできる", bool(ttok) and bool(stok))

        set_id = None
        if ttok and stok:
            st, s = req("/rest/v1/quiz_sets", ttok,
                        {"title": "検査用ダミー（自動で消えます）", "lesson": "test", "is_open": True},
                        extra={"Prefer": "return=representation"})
            set_id = s[0]["id"] if st in (200, 201) and s else None
            self.check("ダミーの回を作れる", bool(set_id), f"{st} {s}")

        if not set_id:
            self.skipTest("ダミーの回を作れなかったため以降を飛ばす（教師ログイン等の前提を確認）")
            return

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
            self.check("4択・3択の設問を作れる", len(qids) == 2)

            st, got = req(f"/rest/v1/questions?select=id,seq,question_choices(idx,label)"
                          f"&quiz_set_id=eq.{set_id}&order=seq", stok)
            counts = sorted(len(g["question_choices"]) for g in (got or []))
            self.check("★学生が4択・3択をそのまま読める", counts == [3, 4], str(counts))

            st, leak = req(f"/rest/v1/question_answers?select=correct_idx"
                           f"&question_id=eq.{qids[0][0]}", stok)
            self.check("★学生に正解は見えない", st == 200 and (leak or []) == [], str(leak))

            st, anon_c = req(f"/rest/v1/question_choices?select=idx&question_id=eq.{qids[0][0]}")
            self.check("★未ログインでは選択肢を読めない", st in (401, 403) or (anon_c or []) == [], f"{st} {anon_c}")

            # ---- 途中保存（範囲の検査つき）----
            q4 = qids[0][0]
            st, r4 = req("/rest/v1/rpc/save_draft", stok,
                         {"p_quiz_set_id": set_id, "p_question_id": q4, "p_chosen": 4, "p_client_seq": 1})
            self.check("4番目を保存できる（2択では不可能だった）", st == 200 and r4 and r4.get("ok"), f"{st} {r4}")
            st, _ = req("/rest/v1/rpc/save_draft", stok,
                        {"p_quiz_set_id": set_id, "p_question_id": q4, "p_chosen": 5, "p_client_seq": 2})
            self.check("★存在しない番号は弾く（4択に5番目は無い）", st >= 400, str(st))
            q3 = qids[1][0]
            st, _ = req("/rest/v1/rpc/save_draft", stok,
                        {"p_quiz_set_id": set_id, "p_question_id": q3, "p_chosen": 4, "p_client_seq": 1})
            self.check("★設問ごとに範囲を見ている（3択に4番目は無い）", st >= 400, str(st))

            # ---- 採点 ----
            st, res = req("/rest/v1/rpc/submit_attempt", stok,
                          {"p_quiz_set_id": set_id, "p_answers": {q4: 4, q3: 3}, "p_duration_ms": 1000})
            self.check("★4択・3択が正しく採点される（両方正解=2/2）",
                  isinstance(res, dict) and res.get("score") == 2 and res.get("total") == 2, str(res)[:100])
            st, res2 = req("/rest/v1/rpc/submit_attempt", stok,
                           {"p_quiz_set_id": set_id, "p_answers": {q4: 1, q3: 3}, "p_duration_ms": 1000})
            self.check("外した分は加点されない（1/2）",
                  isinstance(res2, dict) and res2.get("score") == 1, str(res2)[:100])

            # ---- 学生は選択肢を書き換えられない ----
            st, _ = req("/rest/v1/question_choices", stok,
                        {"question_id": q4, "idx": 9, "label": "わりこみ"})
            self.check("★学生は選択肢を追加できない", st in (401, 403), str(st))
            # ★PATCH は「拒否」でも「0行に当たった」でも 204 を返すので、
            #   状態コードでは判定できない。実際に値が変わっていないかを読み戻して見る。
            st, _ = req(f"/rest/v1/question_choices?question_id=eq.{q4}&idx=eq.1", stok,
                        {"label": "書き換え"}, method="PATCH")
            st2, after = req(f"/rest/v1/question_choices?select=label"
                             f"&question_id=eq.{q4}&idx=eq.1", ttok)
            self.check("★学生が書き換えても中身は変わらない",
                  st2 == 200 and after and after[0]["label"] == "えらぶ1", f"{st} → {after}")
        finally:
            # ---- 片付け（回を消せば設問・選択肢・解答も連鎖で消える）----
            req(f"/rest/v1/quiz_sets?id=eq.{set_id}", ttok, method="DELETE")
            st, left = req(f"/rest/v1/quiz_sets?select=id&id=eq.{set_id}", ttok)
            self.check("ダミーを消せた（残さない）", (left or []) == [], str(left))


if __name__ == "__main__":
    if "--live" in sys.argv:
        sys.argv.remove("--live")
    unittest.main(verbosity=2)
