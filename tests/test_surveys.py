# -*- coding: utf-8 -*-
"""アンケート定義の回帰テスト — scg-student-portal

src/assets/surveys.js（学生画面と教師モニターが共有する定義）が壊れていないことを検査する。
--live を付けると、本物のDB（デモ環境）に対して「同じ学生が複数のアンケートを持てる／
再提出は上書きになる」を往復で確かめる。テスト用キー test_multi_* を負荷試験アカウント l150 で
使うので、学生画面・教師モニターには出ない。

使い方: python tests/test_surveys.py [--live]
依存:   node（定義をブラウザと同じ解釈で評価するため）、標準ライブラリ
"""
import sys, io, os, re, json, subprocess
import urllib.request, urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(ROOT, "src", "assets", "surveys.js")

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  ({detail})" if detail and not cond else ""))

print("=== アンケート定義テスト ===")
r = subprocess.run(["node", "-e",
    "const fs=require('fs');const src=fs.readFileSync(process.argv[1],'utf8');"
    "const S=new Function(src+';return SURVEYS')();process.stdout.write(JSON.stringify(S))", JS],
    capture_output=True, text=True, encoding="utf-8")
check("surveys.js が node で評価できる", r.returncode == 0, r.stderr[:200])
S = json.loads(r.stdout) if r.returncode == 0 else []
keys = [s.get("key") for s in S]
check("アンケートが4本（しんろ1・せいかつ2・がくひ1）", len(S) == 4, str(len(S)))
check("key が一意", len(set(keys)) == len(keys))
check("key は英小文字・数字・_ のみ", all(isinstance(k, str) and re.fullmatch(r"[a-z0-9_]+", k) for k in keys))
shinro = next((s for s in S if s.get("key") == "shinro_2026"), None)
check("shinro_2026 が残り、質問キーが job/field/town（既存回答と互換）",
      shinro is not None and [q["k"] for q in shinro["q"]] == ["job", "field", "town"])
for s in S:
    k = s.get("key")
    check(f"{k}: title/desc/intro/sb/color が入っている", all(s.get(x) for x in ("title", "desc", "intro", "sb", "color")))
    qk = [q.get("k") for q in s.get("q", [])]
    check(f"{k}: 質問は1〜9問・回答キーが一意", 1 <= len(qk) <= 9 and len(set(qk)) == len(qk))
    for q in s.get("q", []):
        ok = (all(x in q for x in ("k", "t", "l", "sl")) and q["t"] in ("text", "select")
              and (q["t"] != "select" or len(q.get("o", [])) >= 2)
              and all("'" not in str(q.get(x, "")) for x in ("l", "ph")))   # innerHTML の属性に入れるため
        check(f"{k}.{q.get('k')}: 形式OK（k/t/l/sl・selectは選択肢2つ以上・引用符なし）", ok)

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
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "null")
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
        st, rows = req("/rest/v1/survey_responses?select=survey_key,answers&survey_key=like.test_multi_*", tok)
        m = {r_["survey_key"]: r_["answers"] for r_ in (rows or [])}
        check("同じ学生が複数のアンケート（2キー）を持てる", isinstance(rows, list) and len(rows) == 2, str(rows)[:120])
        check("同じキーの再提出は上書き（重複行にならない）", m.get("test_multi_a") == {"x": "3"})
        st, rows = req("/rest/v1/survey_responses?select=survey_key,answers,submitted_at", tok)
        check("学生画面と同じ読み方（キー指定なし）で自分の全回答が取れる", isinstance(rows, list) and len(rows) >= 2)

print(f"\n結果: {len(passed)} PASS / {len(failed)} FAIL")
sys.exit(0 if not failed else 1)
