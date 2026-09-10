# -*- coding: utf-8 -*-
"""出題順の並べ替えと、画面を離れた記録の回帰テスト — scg-student-portal

★このテストが守っているのは「機能が動くこと」だけではない。**方針が守られていること**も見ている。
  きあ方針（2026-09-06）: 小テストは到達度をはかる目安の一つで、成績には反映しない。
  だからカンニングをしても下がるのはその学生の学習効果だけ。罰として使わず、
  「この回の到達度確認は、うまく測れていないかもしれない」という目安にとどめる。
  → 個人別を出さない・学生に見せない・警告色にしない、が崩れていないかを機械で見張る。

コード・SQL の構造と、並べ替えの決まり方（Node で実行）は DB不要・常に実行。
デモのDBに対して、記録・単調増加・他人の分・未ログインを実際に試す部分は
既定ではskip。環境変数 SP_LIVE=1 か --live 引数を付けたときだけ動く。
★先に db/2026-09-06_attempt_focus.sql を流しておくこと。
DBに接続できない環境では、有効化していてもskipへ倒れる（FAILにはしない）。

使い方: py -X utf8 tests\\test_integrity.py [--live]
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
SQL     = os.path.join(ROOT, "db", "2026-09-06_attempt_focus.sql")
INDEX   = os.path.join(ROOT, "src", "index.html")
TEACHER = os.path.join(ROOT, "src", "teacher.html")

LIVE = os.environ.get("SP_LIVE") == "1" or "--live" in sys.argv

BASE = "https://egdcbxzpgwenmfabpodd.supabase.co"
ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVnZGNieHpwZ3dlbm1mYWJwb2RkIiwi"
        "cm9sZSI6ImFub24iLCJpYXQiOjE3ODgzNTcwNDYsImV4cCI6MjEwMzkzMzA0Nn0.m908C67Nh4KsYnH_LWvP4wAjOtxI79hhE-BKS1MCxX0")


def read(p):
    return io.open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def req(path, token=None, body=None, method=None):
    headers = {"apikey": ANON, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
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


class TestIntegrityStructure(unittest.TestCase):
    """出題順の並べ替え・SQLの作り・方針遵守の構造検査（DB不要・常に実行）"""

    def check(self, name, cond, detail=""):
        print(("  OK  " if cond else "  NG  ") + name + (f"  ({detail})" if detail and not cond else ""))
        with self.subTest(name=name):
            self.assertTrue(cond, detail or name)

    def test_01_shuffle_order(self):
        print("=== 1. 出題順の並べ替え（DB不要）===")
        idx = read(INDEX)
        self.check("並べ替えの関数がある", all(k in idx for k in ("seedFrom", "rngFrom", "shuffleForStudent")))
        self.check("受験の開始で実際に使っている", re.search(r"questions\s*=\s*shuffleForStudent\(", idx) is not None)
        self.check("種は「学生 + 回」の組から作る（毎回ちがう順にしない）",
              re.search(r"seedFrom\(\s*me\s*\+\s*.\|.\s*\+\s*setId\s*\)", idx) is not None)
        self.check("誰か分からない時は並べ替えない", "if(!me || list.length < 2) return list" in idx)
        self.check("★もんだい本来の番号(seq)は取得したまま＝先生の集計と結果画面がずれない",
              "select=id,seq,prompt" in idx and "x.seq===item.seq" in idx)

        # 実際に Node で動かして、決まり方を確かめる
        js = ""
        for fn in ("seedFrom", "rngFrom", "shuffleForStudent"):
            m = re.search(r"function " + fn + r"\([\s\S]*?\n\}", idx)
            if m:
                js += m.group(0) + "\n"
        js += """
var api = { profile: null };
var L = []; for (var i=0;i<10;i++) L.push({id:"q"+i, seq:i+1});
function ord(who, set){ return shuffleForStudent(L, set, who).map(function(x){return x.seq}).join(","); }
var A1 = ord("student-A","set-1"), A2 = ord("student-A","set-1");
var B1 = ord("student-B","set-1"), A3 = ord("student-A","set-2");
var seen = {}; for (var k=0;k<200;k++) seen[ord("s"+k,"set-1")] = 1;
console.log(JSON.stringify({A1:A1, A2:A2, B1:B1, A3:A3,
  sorted: A1.split(",").map(Number).sort(function(a,b){return a-b}).join(","),
  variety: Object.keys(seen).length}));
"""
        tmp = os.path.join(ROOT, "tmp_shuffle_check.js")
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

        self.check("★同じ学生・同じ回なら いつ開いても同じ順（＝続きから が狂わない）", r["A1"] == r["A2"], r.get("A1"))
        self.check("★学生が違えば順が違う（隣を覗いても意味が無い）", r["A1"] != r["B1"])
        self.check("回が違えば順も違う", r["A1"] != r["A3"])
        self.check("問題が消えたり増えたりしない", r["sorted"] == "1,2,3,4,5,6,7,8,9,10", r.get("sorted"))
        self.check("200人ぶんで十分ばらける（100通り以上）", r["variety"] >= 100, str(r.get("variety")))

    def test_02_away_tracking_sql(self):
        print("\n=== 2. 画面を離れた記録 — 作り（DB不要）===")
        sql = read(SQL)
        low = sql.lower()
        idx = read(INDEX)
        self.check("移行SQLがある", bool(sql), SQL)
        self.check("1人1回につき1行（主キーが 学生・回）",
              re.search(r"primary key\s*\(\s*student_id\s*,\s*quiz_set_id\s*\)", low) is not None)
        self.check("★greatest で増える方向にしか動かない（二重送信・順序入れ替えで減らない）",
              "greatest(f.away_count, excluded.away_count)" in low)
        self.check("RLS が有効", "enable row level security" in low)
        self.check("★表へ直接は書けない（insert/update/delete のポリシーを作っていない）",
              not re.search(r"for\s+(insert|update|delete)", low))
        self.check("読めるのは本人と教師だけ", "student_id = auth.uid()" in low and "is_teacher()" in low)
        self.check("record_away は security definer + search_path 固定",
              re.search(r"function public\.record_away[\s\S]*?security definer[\s\S]*?set search_path", low) is not None)
        self.check("anon から明示的に取り上げている", low.count("from anon") >= 2)
        self.check("負の数を弾く", "bad counter" in sql)
        self.check("受験中だけ数える", 'const onQuiz = quizSet && !$("scr-quiz").hidden' in idx)
        self.check("届かなくても受験は続く（送信の失敗を握りつぶす）",
              re.search(r"record_away[\s\S]{0,200}catch\(\(\)=>\{\}\)", idx) is not None)

    def test_03_policy_not_punitive(self):
        print("\n=== 3. 方針（罰として使わない）が崩れていないか ===")
        sql = read(SQL)
        tea = read(TEACHER)
        idx = read(INDEX)
        # SQL の focus ブロックだけを切り出して、個人を返していないことを見る
        mfoc = re.search(r"'focus'[\s\S]*?from attempt_focus", sql)
        foc = mfoc.group(0) if mfoc else ""
        self.check("集計に focus がある", bool(foc))
        self.check("★集計SQLが個人を返していない（名前も学籍番号も学生idも入れない）",
              bool(foc) and not re.search(r"student_no|display_name|student_id", foc), foc[:120])
        self.check("★教師画面に出るのは全体の合計だけ（students と events のみ）",
              "f.students" in tea and "f.events" in tea)
        # 注記に何を差し込んでいるかだけを見る（近くにある提出フィードの描画に引っかからないよう範囲を切る）
        mnote = re.search(r'\$\("focus-note"\)\.innerHTML\s*=([\s\S]*?);\n', tea)
        note = mnote.group(1) if mnote else ""
        self.check("注記の描画が見つかる", bool(note))
        self.check("★教師画面で誰が離れたかの一覧を作っていない",
              bool(note) and not re.search(r"student_no|display_name|\.name", note), note[:120])
        self.check("★学生の画面は記録を読み戻していない（本人にも見せない）", "attempt_focus" not in idx)
        self.check("警告色にしていない（赤は告発に読める）",
              ".focusnote{" in tea and "background:#f4f6f9" in tea)
        self.check("「証拠ではない」と画面に書いてある", "不正の証拠ではありません" in tea)
        self.check("方針の理由がSQLのコメントに残っている", "成績には反映しない" in sql)
        # ★コメントは対象外（コードの中で理由を説明するのは良いこと）。見るのは学生・先生の目に入る文言だけ。
        visible = re.sub(r"<!--[\s\S]*?-->", "", tea)
        visible = re.sub(r"/\*[\s\S]*?\*/", "", visible)
        self.check("★「カンニング」を画面の文言に出していない", "カンニング" not in visible)
        self.check("★画面に出る「不正」は「不正の証拠ではありません」の1回だけ（告発の言い方をしない）",
              visible.count("不正") == 1 and "不正の証拠ではありません" in visible,
              str(visible.count("不正")))


@unittest.skipUnless(LIVE, "既定ではDB往復をskip。有効化するには環境変数 SP_LIVE=1 か --live 引数を付ける（先に db/2026-09-06_attempt_focus.sql を流すこと）")
class TestIntegrityLive(unittest.TestCase):
    """本物のDBで記録・単調増加・他人の分・未ログインを確認する"""

    def check(self, name, cond, detail=""):
        print(("  OK  " if cond else "  NG  ") + name + (f"  ({detail})" if detail and not cond else ""))
        with self.subTest(name=name):
            self.assertTrue(cond, detail or name)

    def test_01_roundtrip(self):
        print("\n=== 4. 本物のDBで往復（--live）===")
        try:
            tokA, tokB = login("l149", "sakura24"), login("l150", "sakura24")
            tokT = login("t001", "sensei-scg-2026")
        except (urllib.error.URLError, OSError) as e:
            self.skipTest(f"DBに接続できないためskip（{e}）")
            return
        self.check("検査用の学生2人でログインできる", bool(tokA) and bool(tokB))
        self.check("教師でログインできる", bool(tokT))
        if not (tokA and tokB):
            self.skipTest("学生2人のログインに失敗しているため往復テストを飛ばす")
            return

        st, sets = req("/rest/v1/quiz_sets?select=id&is_open=eq.true&limit=1", tokA)
        qs = sets[0]["id"] if st == 200 and sets else None
        self.check("公開中の回がある", bool(qs), str(st))
        if not qs:
            self.skipTest("公開中の回が無いため往復テストを飛ばす")
            return

        # ★記録は減らない作りなので、前回の実行ぶんが残っている。
        #   決め打ちの数で比べると2回目から落ちる（実際に落ちた）ので、今ある値を土台にする。
        st, cur = req(f"/rest/v1/attempt_focus?select=away_count,away_ms&quiz_set_id=eq.{qs}", tokA)
        base = cur[0]["away_count"] if cur else 0
        basems = cur[0]["away_ms"] if cur else 0

        st, r = req("/rest/v1/rpc/record_away", tokA,
                    {"p_quiz_set_id": qs, "p_away_count": base + 3, "p_away_ms": basems + 9000})
        self.check("記録できる", st == 200 and r and r.get("away_count") == base + 3, f"{st} {r}")

        st, r = req("/rest/v1/rpc/record_away", tokA,
                    {"p_quiz_set_id": qs, "p_away_count": base + 1, "p_away_ms": basems + 100})
        self.check("★小さい数が遅れて届いても減らない", bool(r) and r.get("away_count") == base + 3, str(r))

        st, r = req("/rest/v1/rpc/record_away", tokA,
                    {"p_quiz_set_id": qs, "p_away_count": base + 5, "p_away_ms": basems + 12000})
        self.check("増える方向には動く", bool(r) and r.get("away_count") == base + 5, str(r))

        st, _ = req("/rest/v1/rpc/record_away", tokA,
                    {"p_quiz_set_id": qs, "p_away_count": -1, "p_away_ms": 0})
        self.check("負の数は弾く", st >= 400, str(st))

        st, seen = req(f"/rest/v1/attempt_focus?select=away_count&quiz_set_id=eq.{qs}", tokB)
        self.check("★他の学生の記録は見えない", st == 200 and (seen or []) == [], str(seen))

        st, _ = req("/rest/v1/attempt_focus", tokA, {"quiz_set_id": qs, "away_count": 99})
        self.check("★学生は表へ直接 insert できない", st in (401, 403), str(st))

        st, _ = req("/rest/v1/rpc/record_away", None, {"p_quiz_set_id": qs, "p_away_count": 1})
        self.check("★未ログイン(anon)では記録できない", st in (401, 403, 404), str(st))

        if tokT:
            st, s = req("/rest/v1/rpc/quiz_stats", tokT, {"p_quiz_set_id": qs})
            ok = st == 200 and isinstance(s, dict) and "focus" in s
            self.check("教師の集計に全体の合計が入っている", ok, f"{st} {str(s)[:120]}")
            if ok:
                keys = sorted(s["focus"].keys())
                self.check("★集計が返すのは students と events だけ", keys == ["events", "students"], str(keys))
                self.check("集計に人数が反映されている", s["focus"]["students"] >= 1, str(s["focus"]))
        print("  --  検査で入れた記録は残ります（増える方向にしか動かない作りのため）。デモ環境なので可")


if __name__ == "__main__":
    if "--live" in sys.argv:
        sys.argv.remove("--live")
    unittest.main(verbosity=2)
