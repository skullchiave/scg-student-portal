# -*- coding: utf-8 -*-
"""アンケート定義＋文言ファイルの回帰テスト — scg-student-portal

src/assets/surveys.js（学生画面と管理画面が共有する定義・多言語）と src/assets/i18n.js（画面の文言）が
壊れていないことを検査する（DB不要・常に実行）。

本物のDB（デモ環境）に対して「同じ学生が複数のアンケートを持てる／再提出は上書きになる」を
往復で確かめる部分は、既定ではskip。環境変数 SP_LIVE=1 か --live 引数を付けたときだけ動く。
テスト用キー test_multi_* を負荷試験アカウント l150 で使うので、学生画面・管理画面には出ない。
DBに接続できない環境では、有効化していてもskipへ倒れる（FAILにはしない）。

使い方: python tests/test_surveys.py [--live]
依存:   node（定義をブラウザと同じ解釈で評価するため）、標準ライブラリ
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
JS = os.path.join(ROOT, "src", "assets", "surveys.js")
I18N_JS = os.path.join(ROOT, "src", "assets", "i18n.js")
INDEX = os.path.join(ROOT, "src", "index.html")

LIVE = os.environ.get("SP_LIVE") == "1" or "--live" in sys.argv

BASE = "https://egdcbxzpgwenmfabpodd.supabase.co"
ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVnZGNieHpwZ3dlbm1mYWJwb2RkIiwi"
        "cm9sZSI6ImFub24iLCJpYXQiOjE3ODgzNTcwNDYsImV4cCI6MjEwMzkzMzA0Nn0.m908C67Nh4KsYnH_LWvP4wAjOtxI79hhE-BKS1MCxX0")


def node_eval(path, expr):
    r = subprocess.run(["node", "-e",
        "const fs=require('fs');const src=fs.readFileSync(process.argv[1],'utf8');"
        "const v=new Function(src+';return ('+process.argv[2]+')')();process.stdout.write(JSON.stringify(v))", path, expr],
        capture_output=True, text=True, encoding="utf-8")
    return (json.loads(r.stdout) if r.returncode == 0 else None), r.stderr[:200]


def is_ml(x):   # {ja:"…", en:"…"} 型
    return isinstance(x, dict) and isinstance(x.get("ja"), str) and x["ja"] != "" and isinstance(x.get("en"), str) and x["en"] != ""


def req(path, token=None, body=None, extra=None):
    headers = {"apikey": ANON, "Content-Type": "application/json"}
    if extra: headers.update(extra)
    if token: headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    rq = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(rq, timeout=20) as res:
            return res.status, json.loads(res.read().decode() or "null")
    except urllib.error.HTTPError as e2:
        return e2.code, json.loads(e2.read().decode() or "null")


def login(no, pw):
    st, body = req("/auth/v1/token?grant_type=password",
                   body={"email": f"{no}@stu.scg-portal.jp", "password": pw})
    return body.get("access_token") if st == 200 and body else None


class TestSurveysStructure(unittest.TestCase):
    """surveys.js / i18n.js の構造検査（DB不要・常に実行）"""

    @classmethod
    def setUpClass(cls):
        cls.S_raw, cls.s_err = node_eval(JS, "SURVEYS")
        cls.S = cls.S_raw or []
        cls.I_raw, cls.i_err = node_eval(I18N_JS, "I18N")
        cls.L_raw, _ = node_eval(I18N_JS, "LANGS")
        cls.I = cls.I_raw or {}
        cls.L = cls.L_raw or []
        cls.html = open(INDEX, encoding="utf-8").read()

    def check(self, name, cond, detail=""):
        print(("  ✅ " if cond else "  ❌ ") + name + (f"  ({detail})" if detail and not cond else ""))
        with self.subTest(name=name):
            self.assertTrue(cond, detail or name)

    def test_01_surveys_definition(self):
        print("=== アンケート定義テスト（多言語） ===")
        S = self.S
        self.check("surveys.js が node で評価できる", self.S_raw is not None, self.s_err)
        keys = [s.get("key") for s in S]
        self.check("アンケートが4本（しんろ1・せいかつ2・がくひ1）", len(S) == 4, str(len(S)))
        self.check("key が一意", len(set(keys)) == len(keys))
        self.check("key は英小文字・数字・_ のみ", all(isinstance(k, str) and re.fullmatch(r"[a-z0-9_]+", k) for k in keys))
        shinro = next((s for s in S if s.get("key") == "shinro_2026"), None)
        self.check("shinro_2026 が残り、質問キーが job/field/town（既存回答と互換）",
                    shinro is not None and [q["k"] for q in shinro["q"]] == ["job", "field", "town"])

    def test_02_surveys_detail(self):
        for s in self.S:
            k = s.get("key")
            self.check(f"{k}: title/desc/intro が {{ja,en}}・sb/color あり",
                        all(is_ml(s.get(x)) for x in ("title", "desc", "intro")) and bool(s.get("sb")) and bool(s.get("color")))
            qk = [q.get("k") for q in s.get("q", [])]
            self.check(f"{k}: 質問は1〜9問・回答キーが一意", 1 <= len(qk) <= 9 and len(set(qk)) == len(qk))
            for q in s.get("q", []):
                base = all(x in q for x in ("k", "t", "l", "sl")) and q["t"] in ("text", "select") and is_ml(q["l"]) and isinstance(q["sl"], str)
                if q.get("t") == "select":
                    o = q.get("o", [])
                    vs = [x.get("v") for x in o]
                    ok = base and len(o) >= 2 and all(is_ml(x) and isinstance(x.get("v"), str) and re.fullmatch(r"[a-z0-9_]+", x["v"]) for x in o) and len(set(vs)) == len(vs)
                    what = "選択肢2つ以上・v は英小文字/数字/_・一意・{ja,en}"
                else:
                    ok = base and is_ml(q.get("ph")) and "'" not in q["ph"]["ja"] + q["ph"]["en"]   # placeholder は属性に入れるので引用符なし
                    what = "ph は {ja,en}・引用符なし"
                self.check(f"{k}.{q.get('k')}: 形式OK（{what}）", ok)

    def test_03_i18n(self):
        print("\n=== 文言ファイル（i18n.js）テスト ===")
        self.check("i18n.js が node で評価できる", self.I_raw is not None and self.L_raw is not None, self.i_err)
        ja_keys = set((self.I.get("ja") or {}).keys())
        self.check("日本語の文言が入っている", len(ja_keys) >= 40, str(len(ja_keys)))
        for code in [l["code"] for l in self.L if l.get("ready")]:
            missing = sorted(ja_keys - set((self.I.get(code) or {}).keys()))
            self.check(f"{code}: 日本語と同じキーが全部ある", not missing, ",".join(missing[:8]))
        used = set(re.findall(r'data-i18n(?:-ph)?="([^"]+)"', self.html)) | set(re.findall(r'\bt\("([a-z0-9_.]+)"', self.html))
        # t("ex.g." + g) のようにキーを動的に組み立てている箇所は、前半だけが取れて必ず "." で終わる。
        # 実キー（ex.g.1年生 など）は i18n.js 側にあり、そちらは上の「ja/en で同じキーが全部ある」検査が見る。
        # ここで弾かないと、実在するキーを「未定義」と誤検知して落ちる（2026-09-06）。
        used = {k for k in used if not k.endswith(".")}
        unknown = sorted(used - ja_keys)
        self.check(f"index.html が使うキー {len(used)} 個がすべて定義済み", not unknown, ",".join(unknown[:8]))
        self.check("旧・言語バー（白地に白文字）が残っていない", 'class="langbar"' not in self.html and 'class="lang"' not in self.html)
        self.check("🌐 メニューの取り付け口と初期化がある", 'id="langsw"' in self.html and "initLang()" in self.html and "mountLangSwitch(" in self.html)


@unittest.skipUnless(LIVE, "既定ではDB往復をskip。有効化するには環境変数 SP_LIVE=1 か --live 引数を付ける")
class TestSurveysLive(unittest.TestCase):
    """本物のDB（デモ環境）でアンケートの多重保持・上書きを確認する"""

    @classmethod
    def setUpClass(cls):
        try:
            cls.tok = login("l150", "sakura24")
        except (urllib.error.URLError, OSError) as e:
            raise unittest.SkipTest(f"DBに接続できないためskip（{e}）")

    def check(self, name, cond, detail=""):
        print(("  ✅ " if cond else "  ❌ ") + name + (f"  ({detail})" if detail and not cond else ""))
        with self.subTest(name=name):
            self.assertTrue(cond, detail or name)

    def test_01_login(self):
        print("\n=== DB往復テスト（l150 / 検査用の回） ===")
        self.check("l150 でログイン", bool(self.tok))

    def test_02_round_roundtrip(self):
        """★月次化の本体＝**同じアンケートでも、回が違えば別の行になる**。

        2026-09-11 の段階2 まで、一意は (student_id, survey_key) だった＝再提出は上書きで、
        毎月集めても最新1件しか残らなかった。いまは (student_id, round_id)。

        ⚠ 検査用の回（survey_key='test_ui' の「検査用」「検査用2」）は
          db/2026-09-11_survey_rounds_phase2.sql が常設で作る。**毎回そこへ上書きする**ので
          行は増えない。以前は毎回ちがう survey_key を作っていて9件たまっていた
          （survey_responses には消す口が無いので、溜めない作りにするのが唯一の直し方）。
        """
        if not self.tok:
            self.skipTest("l150 のログインに失敗しているため往復テストを飛ばす")

        st, rounds = req("/rest/v1/survey_rounds?select=id,title&survey_key=eq.test_ui&order=title", self.tok)
        if not isinstance(rounds, list) or len(rounds) < 2:
            self.skipTest("検査用の回がまだ無い（db/2026-09-11_survey_rounds_phase2.sql を流す前）")
        r1, r2 = rounds[0]["id"], rounds[1]["id"]

        UP = {"Prefer": "resolution=merge-duplicates"}
        def put(round_id, ans):
            return req("/rest/v1/survey_responses?on_conflict=student_id,round_id", self.tok,
                       {"round_id": round_id, "survey_key": "test_ui", "answers": ans,
                        "submitted_at": "2026-09-11T12:00:00Z"}, UP)[0]

        self.check("1本目の回に出せる", put(r1, {"x": "1"}) in (200, 201))
        self.check("2本目の回にも出せる", put(r2, {"x": "2"}) in (200, 201))
        self.check("1本目に出し直せる", put(r1, {"x": "3"}) in (200, 201))

        st, rows = req("/rest/v1/survey_responses?select=round_id,answers&survey_key=eq.test_ui", self.tok)
        by = {r_["round_id"]: r_["answers"] for r_ in (rows or [])}
        self.check("★同じアンケートでも回が違えば別の行になる（＝毎月ためられる）",
                   isinstance(rows, list) and len(rows) == 2, str(rows)[:140])
        self.check("同じ回への出し直しは上書き（行が増えない）", by.get(r1) == {"x": "3"})
        self.check("別の回の答えは上書きされていない", by.get(r2) == {"x": "2"})

        st, rows = req("/rest/v1/survey_responses?select=round_id,survey_key,answers,submitted_at", self.tok)
        self.check("学生画面と同じ読み方（キー指定なし）で自分の全回答が取れる",
                   isinstance(rows, list) and len(rows) >= 2)

    def test_03_open_rounds_rpc(self):
        """学生が「いま自分に開いている回」を取れること（画面はこれを使って一覧を作る）。"""
        if not self.tok:
            self.skipTest("l150 のログインに失敗しているため飛ばす")
        st, got = req("/rest/v1/rpc/my_open_survey_rounds", self.tok, {})
        if st == 404:
            self.skipTest("my_open_survey_rounds がまだ無い（段階2 を流す前）")
        self.check("my_open_survey_rounds が配列を返す", isinstance(got, list), str(st))
        if isinstance(got, list) and got:
            keys = set(got[0].keys())
            self.check("回に round_id / survey_key / title がある",
                       {"round_id", "survey_key", "title"} <= keys, str(sorted(keys)))


if __name__ == "__main__":
    if "--live" in sys.argv:
        sys.argv.remove("--live")
    unittest.main(verbosity=2)
