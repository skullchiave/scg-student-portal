#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""毎日の自動更新：小テストの点 → 学生マスタDB（2026-09-13 きあ依頼）

きあ「会社PCから、起動中に自動更新できるようにしたい。毎日」

■ やること（2段）
  ① 学生ポータルから小テストの点を書き出す（export_kotest_events.py）
     → 台帳の `マスタDB用データ\小テスト\` へ CSV を置く
  ② 台帳を作り直す（build_master.py）
     → 「小テスト_〈教科書名〉」シートが新しくなる
  ★①だけでは台帳の xlsx は変わりません。②まで走って初めて「自動更新」になります。

■ 使い方
    py -X utf8 scripts\daily_kotest_update.py --check      # 設定を確かめるだけ（走らせない）
    py -X utf8 scripts\daily_kotest_update.py --install    # 毎日 9:00 と 16:30 に登録
    py -X utf8 scripts\daily_kotest_update.py              # いま1回だけ走らせる
    py -X utf8 scripts\daily_kotest_update.py --uninstall  # 登録を消す

■ 会社PCと家PCの2台で動きます（家は予備・2026-09-13 きあ決定）
  `SCG_SITE` が無いと、何もせずに止まります。どちらのPCとして振る舞うかで時刻が変わります。
    setx SCG_SITE office    ← 会社PC： 9:00 / 16:30 / ログオン9分後
    setx SCG_SITE home      ← 家PC　： 0:00
  🔴 同じ 学生マスタDB.xlsx を2台が書くので、**時間で分けて**競合を避けています。
     会社PCには深夜のきっかけが1つも無いので、0:00に書くのは家PCだけになります。
  ★CSVのファイル名もPCごとに分けます（…_全期間_会社.csv / …_全期間_家.csv）。

■ 🔴 Claude はこのスクリプトを走らせません
  `~/.claude/pii_guard.py`（関所）が、Claude の Bash ツール経由の実行だけを止めます。
  中身を読む・直すのは止めていません。きあがタスクや手で叩く分には掛かりません。
  ★環境変数の印は Claude にも見えるので、仕切りとしては関所の側に置いてあります。

■ 🔴 ログに素のまま書きません
  build_master.py の出力には氏名が混ざることがあるので、**必ず mask_log.py を通します**。
  マスクの仕組みが見つからないときは、出力をログに書きません（捨てます）。

■ 止まったときに気づけるように
  失敗したらデスクトップに「⚠小テスト自動更新が止まっています.txt」を作ります。
  次に成功したら消します。★自動化は「止まってもエラーが出ない」のがいちばん怖いので。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import string
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# ── 置き場の決まり ────────────────────────────────────────────
ENV_SITE = "SCG_SITE"                 # どのPCとして振る舞うか（office / home）。印も兼ねる
ENV_LEDGER = "SCG_LEDGER_HOME"        # 台帳の実行フォルダを手で指すとき
LEDGER_REL = Path("claude作業場") / "0.1 分析" / "学生マスタDB"
KOTEST_SUB = Path("マスタDB用データ") / "小テスト"
TASK_NAME = r"SCG\kotest-daily-update"
LOG_KEEP = 200                        # ログはこの行数だけ残す
ALERT_NAME = "⚠小テスト自動更新が止まっています.txt"

# ── いつ走るか（2026-09-13 きあ決定）──────────────────────────────
#
# 🔴 同じ 学生マスタDB.xlsx を2台が書くので、**時間で分ける**のが競合よけ。
#    きあ＝「職場PCの設定はPCがついてる前提だから、当然朝～夕方までのハズ。
#            一方で自宅PCは常につけてるから、24時とかにすれば競合はまずまずしない」
#    会社PCには深夜のきっかけが1つも無い（既存3本も 13:00〜18:00 とログオン後）。
#    9時間離れていれば Drive の同期は完全に終わっているので、番敷やロックは要らない。
#
# ★会社だけ「ログオン後」を持つ理由: 会社PCは消えている時間が長く、
#   時刻だけだと「その時刻に起きていない日」が丸ごと抜ける
#   （2026-09-13 実例＝1週間出勤せず、会社PCの自動化3本が全部止まっていた）。
#   既存3本が ログオン後 3分/5分/7分 なので、ぶつからない9分にしてある。
#   家PCは常時ONなので、時刻だけで足りる。
SITES = {
    "office": dict(label="会社", times=["09:00", "16:30"], logon="PT9M",
                   note="朝いちばんと夕方。PCが消えていた回は起動後に取り戻す"),
    # ⏸ home は**作ったが入れていない**（2026-09-14 きあ判断「やっぱナシ」）。
    #    見送った理由＝③の配布（共有 SCGTools）は社内共有なので家から触れず、
    #    家が持てるのは台帳まで。しかも会社PCが止まっている間は台帳を見る人がいないので、
    #    実効は「会社PCが故障して戻らないとき、最新の台帳が家に残る」の1点だけだった。
    #    ★消さずに残してある＝非常時にそのまま使える。手順書の「7. 家PC編」が入口。
    "home":   dict(label="家",   times=["00:00"],          logon=None,
                   note="会社PCが消えている深夜。ここだけが書く時間帯"),
}


def site() -> str | None:
    v = (os.environ.get(ENV_SITE) or "").strip().lower()
    return v if v in SITES else None


def log_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "SCG"
    return base / "kotest_daily.log"


def alert_path() -> Path:
    return Path.home() / "Desktop" / ALERT_NAME


# ── 社用ドライブを見つける ───────────────────────────────────
def company_drive() -> Path | None:
    r"""「マイドライブ と 共有ドライブ が両方ある」レターが社用ドライブ。

    ★ドライブ文字は PC ごとに違う（家は I:、会社は H:）ので決め打ちしない。
      個人アカウントのドライブは共有ドライブを持たないので、これで見分けられる。
    """
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:/")
        try:
            if (root / "マイドライブ").is_dir() and (root / "共有ドライブ").is_dir():
                return root / "マイドライブ"
        except OSError:
            continue
    return None


def ledger_home() -> tuple[Path | None, str]:
    """台帳の**実行フォルダ**（学生マスタDB.xlsx と scripts がある場所）と、その理由。"""
    v = os.environ.get(ENV_LEDGER)
    if v:
        return Path(v), f"環境変数 {ENV_LEDGER} で指定されています"
    drive = company_drive()
    if not drive:
        return None, "社用ドライブが見つかりません（マイドライブと共有ドライブが両方あるレターが無い）"
    return drive / LEDGER_REL, "社用ドライブから組み立てました"


# ── ログ ──────────────────────────────────────────────────
def write_log(lines: list[str]) -> None:
    p = log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    old = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    p.write_text("\n".join((old + lines)[-LOG_KEEP:]) + "\n", encoding="utf-8")


def masker(home: Path):
    r"""mask_log.mask_text を探して返す。見つからなければ None。

    🔴 見つからないときは、外のプログラムの出力を**ログに書きません**。
      マスクできないまま書くと、氏名が混ざったログが残るためです。
    """
    for cand in [home / "scripts", REPO.parent / "scg-student-master-db" / "scripts"]:
        if (cand / "mask_log.py").exists():
            sys.path.insert(0, str(cand))
            try:
                import mask_log  # noqa: E402
                return mask_log.mask_text
            except Exception:
                continue
    return None


def run(cmd: list[str], mask) -> tuple[int, str]:
    """外のプログラムを走らせ、**マスク済みの短い要約**だけ返す。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=3600)
    except subprocess.TimeoutExpired:
        return 124, "1時間たっても終わらないので打ち切りました"
    except Exception as e:
        return 1, f"起動できませんでした（{type(e).__name__}）"
    out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
    tail = "\n".join(out.splitlines()[-12:])
    if mask is None:
        return r.returncode, "（マスクの仕組みが無いので、出力はログに残していません）"
    masked, _counts = mask(tail)
    return r.returncode, masked


# ── 本体 ──────────────────────────────────────────────────
def do_check(verbose: bool = True) -> int:
    """設定を確かめるだけ。**走らせない**。"""
    ok = True
    say = print if verbose else (lambda *a, **k: None)

    s = site()
    if s:
        c = SITES[s]
        say(f"OK  このPCは「{c['label']}」（{ENV_SITE}={s}）"
            f"　走る時刻: {' と '.join(c['times'])}"
            + ("　＋ログオン後" if c["logon"] else ""))
    else:
        say(f"🔴  {ENV_SITE} が設定されていません"
            f"　→ 会社PCなら  setx {ENV_SITE} office"
            f"　／家PCなら  setx {ENV_SITE} home")
    ok &= bool(s)

    home, why = ledger_home()
    say(f"台帳の場所: {home}\n  理由: {why}")
    if home is None:
        return 1
    for label, p in [("学生マスタDB.xlsx", home / "学生マスタDB.xlsx"),
                     ("build_master.py", home / "scripts" / "build_master.py"),
                     ("小テストの置き場", home / KOTEST_SUB)]:
        exists = p.exists()
        say(f"{'OK  ' if exists else '🔴  '}{label}")
        if label == "小テストの置き場" and not exists:
            say("      → 走らせたときに自動で作ります（無くてもかまいません）")
        else:
            ok &= exists

    exporter = HERE / "export_kotest_events.py"
    say(f"{'OK  ' if exporter.exists() else '🔴  '}export_kotest_events.py")
    ok &= exporter.exists()

    say(f"{'OK  ' if masker(home) else '🔴  '}mask_log.py（ログのマスク）")

    # ★「走らなかった日」は目印が出ない。だから**前回いつ成功したか**を必ず出す。
    #   失敗は気づけるが、そもそも走っていないことには気づけないため（2026-09-13）。
    last, days = last_success()
    if last is None:
        say("⚠  まだ1度も成功していません（または記録がありません）")
    else:
        mark = "OK  " if days <= 3 else "⚠  "
        say(f"{mark}前回うまくいったのは {last:%Y-%m-%d %H:%M}（{days}日前）"
            + ("　→ 会社PCが起動していない日は走りません" if days > 3 else ""))
    say(f"ログ: {log_path()}")
    return 0 if ok else 1


def last_success() -> tuple[dt.datetime | None, int]:
    """ログから、最後に成功した日時と「何日前か」を返す。"""
    p = log_path()
    if not p.exists():
        return None, -1
    for line in reversed(p.read_text(encoding="utf-8").splitlines()):
        if "✅ 終わり" in line and line.startswith("["):
            try:
                d = dt.datetime.strptime(line[1:17], "%Y-%m-%d %H:%M")
                return d, (dt.datetime.now() - d).days
            except ValueError:
                continue
    return None, -1


def do_run() -> int:
    started = dt.datetime.now()
    stamp = started.strftime("%Y-%m-%d %H:%M")

    s = site()
    if not s:
        print(f"🔴 {ENV_SITE} が無いので、何もせずに止まりました。")
        print("   このPCが「会社」なのか「家」なのかが決まっていないと、走る時間帯が決められません。")
        print(f"   会社PCなら:  setx {ENV_SITE} office　／　家PCなら:  setx {ENV_SITE} home")
        return 2
    label = SITES[s]["label"]

    home, why = ledger_home()
    if home is None or not (home / "scripts" / "build_master.py").exists():
        msg = f"台帳が見つかりません（{why}）"
        print("🔴 " + msg)
        write_log([f"[{stamp}] 🔴 {msg}"])
        raise_alert(msg)
        return 1

    # 二重に走らせない（朝の回と、起動後の取りこぼしが重なることがある）
    lock = log_path().parent / "kotest_daily.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists() and (started.timestamp() - lock.stat().st_mtime) < 3600:
        print("もう走っているようなので、今回は見送りました。")
        write_log([f"[{stamp}] 見送り（前の回がまだ走っている）"])
        return 0
    lock.write_text(stamp, encoding="utf-8")

    mask = masker(home)
    lines = [f"[{stamp}] はじめ"]
    # ★間があいていたら、それを記録に残す（会社PCが起動しなかった日は走らないため）
    prev, gap = last_success()
    if prev is not None and gap >= 3:
        lines.append(f"  ⚠ 前回うまくいったのは {gap}日前（{prev:%Y-%m-%d}）"
                     "＝そのあいだ台帳は古いままでした")
    try:
        out_dir = home / KOTEST_SUB
        out_dir.mkdir(parents=True, exist_ok=True)

        # ① ポータル → CSV
        # ★CSVのファイル名は**PCごとに分ける**。同じ名前だと、たまたま時間が重なった日に
        #   Drive がファイル競合のコピーを作る。kotest.py は複数枚を読んで
        #   「同じ（学生・教科書・回）は先に読んだほうを残す」ので、2枚あって困らない。
        code, note = run([sys.executable, "-X", "utf8", str(HERE / "export_kotest_events.py"),
                          "--out", str(out_dir), "--label", label], mask)
        lines.append(f"  ① 点の書き出し: {'OK' if code == 0 else '🔴 失敗'}（終了コード {code}）")
        lines += ["      " + x for x in note.splitlines() if x.strip()]
        if code != 0:
            raise RuntimeError("小テストの点を書き出せませんでした")

        # ② 台帳を作り直す
        code, note = run([sys.executable, "-X", "utf8",
                          str(home / "scripts" / "build_master.py")], mask)
        lines.append(f"  ② 台帳の作り直し: {'OK' if code == 0 else '🔴 失敗'}（終了コード {code}）")
        lines += ["      " + x for x in note.splitlines() if x.strip()]
        if code != 0:
            raise RuntimeError("台帳を作り直せませんでした（xlsx を開いたままだと書けません）")

        sec = int((dt.datetime.now() - started).total_seconds())
        lines.append(f"[{stamp}] ✅ 終わり（{sec}秒）")
        clear_alert()
        print("\n".join(lines))
        return 0
    except Exception as e:
        lines.append(f"[{stamp}] 🔴 {e}")
        raise_alert(str(e))
        print("\n".join(lines))
        return 1
    finally:
        write_log(lines)
        try:
            lock.unlink()
        except OSError:
            pass


def raise_alert(msg: str) -> None:
    """デスクトップに目印を置く。★止まったことに気づけないのがいちばん困るので。"""
    try:
        p = alert_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "小テストの自動更新が止まっています。\n\n"
            f"　最後に試したとき: {dt.datetime.now():%Y-%m-%d %H:%M}\n"
            f"　うまくいかなかったところ: {msg}\n\n"
            "よくある原因:\n"
            "  ・学生マスタDB.xlsx を開いたままだった（閉じてから、もう一度）\n"
            "  ・ネットにつながっていなかった\n"
            "  ・Google ドライブの同期が終わっていなかった\n\n"
            "手で走らせて確かめる:\n"
            f"  py -X utf8 \"{HERE / 'daily_kotest_update.py'}\" --check\n"
            f"  py -X utf8 \"{HERE / 'daily_kotest_update.py'}\"\n\n"
            f"くわしい記録: {log_path()}\n"
            "★次にうまくいったら、このファイルは自動で消えます。\n",
            encoding="utf-8")
    except OSError:
        pass


def clear_alert() -> None:
    try:
        alert_path().unlink()
    except OSError:
        pass


# ── タスクスケジューラへの登録 ────────────────────────────────
def logon_user() -> str:
    r"""ログオントリガーに書く「自分」（`ドメイン\ユーザー名`）。"""
    dom = os.environ.get("USERDOMAIN", "")
    user = os.environ.get("USERNAME", "")
    return f"{dom}\\{user}" if dom else user


def task_xml(s: str) -> str:
    r"""そのPCの時刻でタスクの中身を組む。**止まっていた回は、起動後に取り戻す**。

    ★schtasks のコマンド引数だけでは「利用可能になったら実行」を付けられないので、
      XML を書いて渡す。XML は UTF-16 で保存しないと schtasks が読めない。
    """
    c = SITES[s]
    exe = sys.executable
    script = HERE / "daily_kotest_update.py"
    triggers = "".join(
        f"""
    <CalendarTrigger>
      <StartBoundary>2026-01-01T{t}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>""" for t in c["times"])
    if c["logon"]:
        # ★<UserId> を書かないと「すべてのユーザーのログオン時」の意味になり、
        #   管理者でないと登録できない（会社PCで「アクセスが拒否されました」）。
        #   自分のログオン時に限れば、管理者でなくても登録できる。既存のSCGタスクも同じ形。
        triggers += f"""
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{logon_user()}</UserId>
      <Delay>{c['logon']}</Delay>
    </LogonTrigger>"""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>学生ポータルの小テストの点を、学生マスタDBへ入れる（毎日・{c['label']}PC／{c['note']}）</Description>
  </RegistrationInfo>
  <Triggers>{triggers}
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{exe}</Command>
      <Arguments>-X utf8 "{script}"</Arguments>
      <WorkingDirectory>{REPO}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def do_install() -> int:
    if do_check(verbose=True) != 0:
        print("\n🔴 設定がそろっていないので、登録しませんでした。上の🔴を直してから、もう一度。")
        return 1
    s = site()
    c = SITES[s]
    xml = Path(tempfile.gettempdir()) / "scg_kotest_task.xml"
    xml.write_text(task_xml(s), encoding="utf-16")
    r = subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml), "/F"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    xml.unlink(missing_ok=True)
    if r.returncode != 0:
        print("🔴 登録できませんでした:\n" + (r.stderr or r.stdout or "").strip()[:400])
        return 1
    print(f"✅ 登録しました: {TASK_NAME}（このPCは「{c['label']}」）")
    print(f"   毎日 {' と '.join(c['times'])}"
          + ("　＋ログオンの9分後" if c["logon"] else "")
          + f"　― {c['note']}")
    if s == "home":
        print("   ★会社PCは朝〜夕方しか動かないので、この時間に書くのは家PCだけです。")
    print("   確かめる: タスクスケジューラ →「タスク スケジューラ ライブラリ」→ SCG")
    print(f"   いますぐ試す: schtasks /Run /TN \"{TASK_NAME}\"")
    return 0


def do_uninstall() -> int:
    r = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("消せませんでした（もともと登録されていないかもしれません）")
        return 1
    print(f"✅ 消しました: {TASK_NAME}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="小テストの点を、毎日 学生マスタDB へ入れる")
    ap.add_argument("--check", action="store_true", help="設定を確かめるだけ（走らせない）")
    ap.add_argument("--install", action="store_true", help="毎日の実行に登録する")
    ap.add_argument("--uninstall", action="store_true", help="登録を消す")
    a = ap.parse_args()
    if a.check:
        return do_check()
    if a.install:
        return do_install()
    if a.uninstall:
        return do_uninstall()
    return do_run()


if __name__ == "__main__":
    sys.exit(main())
