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
HARNESS = os.path.join(HERE, "e2e_quiz_flow.html")
CANDS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
         r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
         os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")]
chrome = next((c for c in CANDS if os.path.exists(c)), None)
if not chrome:
    print("Chrome が見つかりません（このテストはブラウザ実操作なので Chrome が必要）"); sys.exit(2)

prof = tempfile.mkdtemp(prefix="e2e-quiz-chrome-")
try:
    url = "file:///" + HARNESS.replace("\\", "/").replace(" ", "%20")
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--user-data-dir=" + prof,
                        "--allow-file-access-from-files", "--virtual-time-budget=90000", "--dump-dom", url],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
finally:
    shutil.rmtree(prof, ignore_errors=True)

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
