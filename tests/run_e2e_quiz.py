# -*- coding: utf-8 -*-
"""学生画面の小テスト往復を、ヘッドレスChromeで実際に操作して確かめる回帰テスト。

tests/e2e_quiz_flow.html が src/index.html を iframe で開き、本物のデモDB（Supabase）に対して
  ログイン(l149) → 小テスト一覧 → 受験 → 選択肢を実際に押す → つぎへ → 提出 → 結果
を順に実行し、各段階の結果を JSON で返す。

★なぜ要るか: 2026-09-06 に選択肢が2個固定でなくなり、ボタンを**その場で描く**ようになった。
  「ボタンが出るか」「押せるか」「押したものに印が付くか」は DOM の文字列検査では見えない。
  とくに**並べ替えても取り違えない**ことは、実際に押してみないと確かめられない。
※ 提出するので attempts に l149 の記録が1件増える（負荷試験用アカウントなので授業の数字は汚さない）。

使い方: python tests/run_e2e_quiz.py
依存:   Google Chrome（Windows の標準の場所を探す）、標準ライブラリ
失敗時の見方: ❌ 行の括弧内が、その時点の画面の文言や一覧の並び
"""
import os, sys, io, re, json, html, subprocess, tempfile, shutil

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from env_creds import write_e2e_creds_js, NO_ENV_MSG
HARNESS = os.path.join(HERE, "e2e_quiz_flow.html")
CANDS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
         r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
         os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")]
chrome = next((c for c in CANDS if os.path.exists(c)), None)
if not chrome:
    print("Chrome が見つかりません（このテストはブラウザ実操作なので Chrome が必要）"); sys.exit(2)

# e2e_quiz_flow.html は file:// で開くので .env を直接読めない。
# ここで .env を読んで tmp/e2e_creds.js に書き出し、HTML側はそれを読む（値は標準出力に出さない）。
creds = write_e2e_creds_js(os.path.join(HERE, "..", "tmp", "e2e_creds.js"))
if not creds.get("studentPw"):
    print(f"🔴 {NO_ENV_MSG}"); sys.exit(2)


# 🔴 このテストは「検査用の回が公開中のままである」ことを当てにしていた（2026-09-12 に落ちた）。
#    きあがデモを触って「停止」を押しただけで、コードは正しいのに 2 PASS / 3 FAIL になる。
#    ＝**誰かが画面でボタンを押したら落ちる検査**。自分で開けて、終わったら元の状態へ戻す。
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

BASE = "https://egdcbxzpgwenmfabpodd.supabase.co"
with io.open(os.path.join(HERE, "..", "src", "assets", "api.js"), encoding="utf-8") as f:
    ANON = re.search(r'"(eyJ[\w-]+\.[\w-]+\.[\w-]+)"', f.read()).group(1)
QUIZ_SET = "c75def6b-7623-4d86-8540-0c5b081ecf7c"   # 検査用の回（tests/test_security.py と同じ）


def _req(path, token=None, body=None, method=None):
    h = {"apikey": ANON, "Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    rq = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(rq, timeout=20) as res:
            return res.status, json.loads(res.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "null")


ttok, was_open = None, None
try:
    st, b = _req("/auth/v1/token?grant_type=password",
                 body={"email": creds["teacherNo"] + "@stu.scg-portal.jp",
                       "password": creds["teacherPw"]})
    ttok = b.get("access_token") if st == 200 else None
    if ttok:
        st, rows = _req(f"/rest/v1/quiz_sets?select=is_open&id=eq.{QUIZ_SET}", ttok)
        was_open = bool(rows[0]["is_open"]) if rows else None
        if was_open is False:
            _req(f"/rest/v1/quiz_sets?id=eq.{QUIZ_SET}", ttok, {"is_open": True}, method="PATCH")
            print("ⓘ 検査用の回が停止中だったので、一時的に公開して試します（終わったら戻します）")
except Exception as e:
    print(f"⚠ 検査用の回の状態を整えられませんでした（{e}）。そのまま続けます")

prof = tempfile.mkdtemp(prefix="e2e-quiz-chrome-")
try:
    url = "file:///" + HARNESS.replace("\\", "/").replace(" ", "%20")
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--user-data-dir=" + prof,
                        "--allow-file-access-from-files", "--virtual-time-budget=90000", "--dump-dom", url],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
finally:
    shutil.rmtree(prof, ignore_errors=True)
    # ★元に戻す。検査が環境の状態を変えたままにしない
    if ttok and was_open is False:
        _req(f"/rest/v1/quiz_sets?id=eq.{QUIZ_SET}", ttok, {"is_open": False}, method="PATCH")

print("=== ブラウザ実操作テスト（小テスト往復） ===")
m = re.search(r'E2E_RESULT (\{.*?\})</pre>', r.stdout, flags=re.S)
if not m:
    print("結果が取れませんでした（Chrome の出力に E2E_RESULT が無い）"); sys.exit(1)
log = json.loads(html.unescape(m.group(1)))
ng = 0
for st in log["steps"]:
    print(("  ✅ " if st["ok"] else "  ❌ ") + st["name"] + (f"  ({st['detail']})" if st["detail"] and not st["ok"] else ""))
    ng += (not st["ok"])
if log.get("error"):
    print("  ❌ 実行エラー:", log["error"]); ng += 1
if not log.get("done"):
    print("  ❌ 最後まで到達していない"); ng += 1
print(f"\n結果: {len(log['steps']) - sum(1 for s in log['steps'] if not s['ok'])} PASS / {ng} FAIL")
sys.exit(1 if ng else 0)
