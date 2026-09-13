# -*- coding: utf-8 -*-
r"""run_shot_master.py — マスター画面を実際に開いて、見え方を画像に撮る（2026-09-13）

★なぜ要るか: きあから「ここの見た目が変」と画像で報告が来る。こちらでも**先に見られる**ようにする。
  実際、2026-09-13 にこれで撮って、**一覧の操作ボタンが縦に3段になっていた**のが分かった
  （押せるかは通るので、ふつうの検査からは見えない）。

  py -X utf8 tests\run_shot_master.py            … 一覧・Excelの選択・教材しぼり込み・確認ダイアログ
  py -X utf8 tests\run_shot_master.py xlsx       … その1枚だけ

出力先は tmp\shots\  （.gitignore 済み）。
🔴 DBは読むだけ。公開・保存・削除のボタンは押さない。
"""
import io
import os
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from env_creds import write_e2e_creds_js, NO_ENV_MSG  # noqa: E402

CANDS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
         r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
         os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")]
chrome = next((c for c in CANDS if os.path.exists(c)), None)
if not chrome:
    print("Chrome が見つかりません"); sys.exit(2)

creds = write_e2e_creds_js(os.path.join(REPO, "tmp", "e2e_creds.js"))
if not creds or not creds.get("masterPw"):
    print(NO_ENV_MSG); sys.exit(2)

# ★ハーネスは tmp\ に置いてから開く（e2e_creds.js を同じ場所から読むため）
src = os.path.join(HERE, "shot_master.html")
dst = os.path.join(REPO, "tmp", "shot_master.html")
with open(src, encoding="utf-8") as f:
    body = f.read()
with open(dst, "w", encoding="utf-8") as f:
    f.write(body)

outdir = os.path.join(REPO, "tmp", "shots")
os.makedirs(outdir, exist_ok=True)
modes = sys.argv[1:] or ["list", "xlsx", "book", "dlg"]
url = "file:///" + dst.replace("\\", "/").replace(" ", "%20")

for m in modes:
    png = os.path.join(outdir, f"master_{m}.png")
    prof = tempfile.mkdtemp(prefix="chrome-shot-")
    subprocess.run(
        [chrome, "--headless=new", "--disable-gpu", "--no-first-run",
         f"--user-data-dir={prof}", "--allow-file-access-from-files",
         "--window-size=1620,1060", "--virtual-time-budget=40000",
         f"--screenshot={png}", url + "#" + m],
        capture_output=True, timeout=180)
    ok = os.path.exists(png) and os.path.getsize(png) > 20000
    print(("  ✅ " if ok else "  🔴 ") + f"{m:6s} {png}")

print("\n★見るときは画像を開いてください。DBには何も書いていません。")
