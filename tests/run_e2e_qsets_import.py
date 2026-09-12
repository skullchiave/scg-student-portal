# -*- coding: utf-8 -*-
"""教師画面「問題の登録・解放」の取り込み〜公開往復を、ヘッドレスChromeで実際に操作して確かめる回帰テスト。

tests/e2e_qsets_import_flow.html が src/teacher.html を iframe で開き、本物のデモDB（Supabase）に対して
  教師ログイン(t001) → ①取り込み(重複シートのブロックも確認) → ②プレビュー → ③1問ずつ修正
  → ②へ戻って修正が反映されているか → ④公開 → 一覧に出るか → 片付け（消す）
を順に実行し、各段階の結果を JSON で返す。手本: run_e2e_quiz.py（学生画面の小テスト往復）。

★なぜ要るか: 取り込みルールの正しさは tests/test_qsets_import.py（Node）で確かめているが、
  「画面から実際に選ぶ・直す・公開する」動きと「公開したら本物に書き込まれ、あとで消せる」ところは
  ブラウザで実際に操作しないと確かめられない。

★書き込みについて: このテストは本物のデモDB（実在の学生情報ゼロ）に**ダミーの設問**を作り、
  最後に自分で消す（title が「🧪E2Eテストダミー」で始まる回だけを対象にする）。
  本物の教材の設問はDBに入れない。

使い方: python tests/run_e2e_qsets_import.py
依存:   Google Chrome（Windows の標準の場所を探す）、標準ライブラリ
失敗時の見方: ❌ 行の括弧内が、その時点の画面の文言や一覧の並び。
  「★ダミーを消せた」が❌の場合は、Supabaseの quiz_sets から
  title が「🧪E2Eテストダミー」で始まる行を手で確認・削除すること。
"""
import os, sys, io, re, json, html, subprocess, tempfile, shutil

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from env_creds import write_e2e_creds_js, NO_ENV_MSG
HARNESS = os.path.join(HERE, "e2e_qsets_import_flow.html")
CANDS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
         r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
         os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")]
chrome = next((c for c in CANDS if os.path.exists(c)), None)
if not chrome:
    print("Chrome が見つかりません（このテストはブラウザ実操作なので Chrome が必要）"); sys.exit(2)

# e2e_qsets_import_flow.html は file:// で開くので .env を直接読めない。
# ここで .env を読んで tmp/e2e_creds.js に書き出し、HTML側はそれを読む（値は標準出力に出さない）。
creds = write_e2e_creds_js(os.path.join(HERE, "..", "tmp", "e2e_creds.js"))
if not creds.get("teacherPw"):
    print(f"🔴 {NO_ENV_MSG}"); sys.exit(2)

prof = tempfile.mkdtemp(prefix="e2e-qsets-chrome-")
try:
    url = "file:///" + HARNESS.replace("\\", "/").replace(" ", "%20")
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--user-data-dir=" + prof,
                        "--allow-file-access-from-files", "--virtual-time-budget=120000", "--dump-dom", url],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
finally:
    shutil.rmtree(prof, ignore_errors=True)

print("=== ブラウザ実操作テスト（問題の登録・解放 往復）===")
m = re.search(r'E2E_RESULT (\{.*?\})</pre>', r.stdout, flags=re.S)
if not m:
    print("結果が取れませんでした（Chrome の出力に E2E_RESULT が無い）")
    if r.stderr.strip():
        print("  stderr:", r.stderr.strip()[:400])
    sys.exit(1)
log = json.loads(html.unescape(m.group(1)))
ng = 0
for st in log["steps"]:
    # ★片付けの行だけは、通っていても中身を必ず出す。
    #   「何件見つけて何件消したか」が見えないと、残骸が積み上がっても気づけない
    #   （2026-09-11 に、1件だけ消して検査は通る状態を実際に踏んだ）。
    show = st["detail"] and (not st["ok"] or "消せた" in st["name"])
    print(("  ✅ " if st["ok"] else "  ❌ ") + st["name"] + (f"  ({st['detail']})" if show else ""))
    ng += (not st["ok"])
if log.get("cleanupError"):
    print("  ⚠ 片付け中のエラー:", log["cleanupError"])
if log.get("error"):
    print("  ❌ 実行エラー:", log["error"]); ng += 1
if not log.get("done"):
    print("  ❌ 最後まで到達していない"); ng += 1
print(f"\n結果: {len(log['steps']) - sum(1 for s in log['steps'] if not s['ok'])} PASS / {ng} FAIL")
sys.exit(1 if ng else 0)
