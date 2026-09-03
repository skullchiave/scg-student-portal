# -*- coding: utf-8 -*-
"""アンケート定義＋文言ファイルの回帰テスト — scg-student-portal

src/assets/surveys.js（学生画面と管理画面が共有する定義・多言語）と src/assets/i18n.js（画面の文言）が
壊れていないことを検査する。
--live を付けると、本物のDB（デモ環境）に対して「同じ学生が複数のアンケートを持てる／
再提出は上書きになる」を往復で確かめる。テスト用キー test_multi_* を負荷試験アカウント l150 で
使うので、学生画面・管理画面には出ない。

使い方: python tests/test_surveys.py [--live]
依存:   node（定義をブラウザと同じ解釈で評価するため）、標準ライブラリ
"""
import sys, io, os, re, json, subprocess
import urllib.request, urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(ROOT, "src", "assets", "surveys.js")
I18N_JS = os.path.join(ROOT, "src", "assets", "i18n.js")
INDEX = os.path.join(ROOT, "src", "index.html")

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  ({detail})" if detail and not cond else ""))

def node_eval(path, expr):
    r = subprocess.run(["node", "-e",
        "const fs=require('fs');const src=fs.readFileSync(process.argv[1],'utf8');"
        "const v=new Function(src+';return ('+process.argv[2]+')')();process.stdout.write(JSON.stringify(v))", path, expr],
        capture_output=True, text=True, encoding="utf-8")
    return (json.loads(r.stdout) if r.returncode == 0 else None), r.stderr[:200]

def is_ml(x):   # {ja:"…", en:"…"} 型
    return isinstance(x, dict) and isinstance(x.get("ja"), str) and x["ja"] != "" and isinstance(x.get("en"), str) and x["en"] != ""

print("=== アンケート定義テスト（多言語） ===")
S, e = node_eval(JS, "SURVEYS")
check("surveys.js が node で評価できる", S is not None, e)
S = S or []
keys = [s.get("key") for s in S]
check("アンケートが4本（しんろ1・せいかつ2・がくひ1）", len(S) == 4, str(len(S)))
check("key が一意", len(set(keys)) == len(keys))
check("key は英小文字・数字・_ のみ", all(isinstance(k, str) and re.fullmatch(r"[a-z0-9_]+", k) for k in keys))
shinro = next((s for s in S if s.get("key") == "shinro_2026"), None)
check("shinro_2026 が残り、質問キーが job/field/town（既存回答と互換）",
      shinro is not None and [q["k"] for q in shinro["q"]] == ["job", "field", "town"])
for s in S:
    k = s.get("key")
    check(f"{k}: title/desc/intro が {{ja,en}}・sb/color あり", all(is_ml(s.get(x)) for x in ("title", "desc", "intro")) and s.get("sb") and s.get("color"))
    qk = [q.get("k") for q in s.get("q", [])]
    check(f"{k}: 質問は1〜9問・回答キーが一意", 1 <= len(qk) <= 9 and len(set(qk)) == len(qk))
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
        check(f"{k}.{q.get('k')}: 形式OK（{what}）", ok)

print("\n=== 文言ファイル（i18n.js）テスト ===")
I, e = node_eval(I18N_JS, "I18N")
L, _ = node_eval(I18N_JS, "LANGS")
check("i18n.js が node で評価できる", I is not None and L is not None, e)
I = I or {}; L = L or []
ja_keys = set((I.get("ja") or {}).keys())
check("日本語の文言が入っている", len(ja_keys) >= 40, str(len(ja_keys)))
for code in [l["code"] for l in L if l.get("ready")]:
    missing = sorted(ja_keys - set((I.get(code) or {}).keys()))
    check(f"{code}: 日本語と同じキーが全部ある", not missing, ",".join(missing[:8]))
html = open(INDEX, encoding="utf-8").read()
used = set(re.findall(r'data-i18n(?:-ph)?="([^"]+)"', html)) | set(re.findall(r'\bt\("([a-z0-9_.]+)"', html))
unknown = sorted(used - ja_keys)
check(f"index.html が使うキー {len(used)} 個がすべて定義済み", not unknown, ",".join(unknown[:8]))
check("旧・言語バー（白地に白文字）が残っていない", 'class="langbar"' not in html and 'class="lang"' not in html)
check("🌐 メニューの取り付け口と初期化がある", 'id="langsw"' in html and "initLang()" in html and "mountLangSwitch(" in html)

if "--live" in sys.argv:
    print("\n=== DB往復テスト（l150 / test_multi_*） ===")
    BASE = "https://egdcbxzpgwenmfabpodd.supabase.co"
    ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVnZGNieHpwZ3dlbm1mYWJwb2RkIiwi"
            "cm9sZSI6ImFub24iLCJpYXQiOjE3ODgzNTcwNDYsImV4cCI6MjEwMzkzMzA0Nn0.m908C67Nh4KsYnH_LWvP4wAjOtxI79hhE-BKS1MCxX0")
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
    st, body = req("/auth/v1/token?grant_type=password",
                   body={"email": "l150@stu.scg-portal.jp", "password": "sakura24"})
    tok = body.get("access_token") if st == 200 else None
    check("l150 でログイン", bool(tok), str(st))
    if tok:
        UP = {"Prefer": "resolution=merge-duplicates"}
        for key, ans in (("test_multi_a", {"x": "1"}), ("test_multi_b", {"x": "2"}), ("test_multi_a", {"x": "3"})):
            st, _ = req("/rest/v1/survey_responses?on_conflict=student_id,survey_key", tok,
                        {"survey_key": key, "answers": ans, "submitted_at": "2026-09-03T12:00:00Z"}, UP)
            check(f"upsert {key} {ans}", st in (200, 201), str(st))
        st, rows = req("/rest/v1/survey_responses?select=survey_key,answers&survey_key=in.(test_multi_a,test_multi_b)", tok)
        m = {r_["survey_key"]: r_["answers"] for r_ in (rows or [])}
        check("同じ学生が複数のアンケート（2キー）を持てる", isinstance(rows, list) and len(rows) == 2, str(rows)[:120])
        check("同じキーの再提出は上書き（重複行にならない）", m.get("test_multi_a") == {"x": "3"})
        st, rows = req("/rest/v1/survey_responses?select=survey_key,answers,submitted_at", tok)
        check("学生画面と同じ読み方（キー指定なし）で自分の全回答が取れる", isinstance(rows, list) and len(rows) >= 2)

print(f"\n結果: {len(passed)} PASS / {len(failed)} FAIL")
sys.exit(0 if not failed else 1)
