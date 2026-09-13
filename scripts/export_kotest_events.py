#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""学生ポータルの小テスト結果を、学生マスタDBの「イベント」形式で書き出す（2026-09-13）。

■ なぜ画面のボタンではなくスクリプトなのか
  きあ（2026-09-13）＝「学生マスタDBは、私が作ってる**他の人に触らせない**DB。
  他人は存在を知らない前提で動いてほしい。私がスーパーマスター。
  他のマスターアカウントには、いらないですね」
  → マスター画面にあった「🗃 学生マスタDB用（イベント形式）」は**外した**。
    他のマスター（教務主任など）には意味が分からないボタンで、
    押せてしまうこと自体が台帳の存在を漏らすため。
  → 代わりに**きあだけが走らせるこのスクリプト**にした。

■ 使い方（きあ専用）
    # 何件出るか見るだけ。ファイルは書かない
    py -X utf8 scripts\export_kotest_events.py --dry-run

    # 書き出す（置き場は下の「どこへ書くか」で自動で決まる）
    py -X utf8 scripts\export_kotest_events.py

    # 置き場を手で指定する（会社PCなど）
    py -X utf8 scripts\export_kotest_events.py --out "…\マスタDB用データ\小テスト"

  このあと `build_master.py` を走らせると、「小テスト_〈教科書名〉」シートが更新される。
  ★2つを続けて走らせれば、きあから見て「自動更新」になる。

■ どこへ書くか
  ① --out があればそこ
  ② 無ければ、隣に scg-student-master-db があるか探して
     `マスタDB用データ\小テスト\` へ（＝きあのPCではここに落ちる）
  ③ それも無ければ `tmp\`（.gitignore 済み）
  どれを選んだかは**必ず画面に出す**。黙って別の場所に置かない。

■ 1つのファイルを上書きする
  毎回**全期間を丸ごと**書き出すので、前の版は要らない。
  ＝日付入りのファイルが溜まっていって「どれが新しいのか」を人が判断する、を作らない。
  ⚠ ただし**この形式でないファイルは上書きしない**（1行目の17列が合わなければ止まる）。
     手で置いたファイルを巻き込まないため。

■ 出すもの（台帳の「イベント」シートと同じ17列）
  種別=小テスト ／ 級=教科書名 ／ 回=その教科書の中で何回目か ／ 備考=テスト名
  ★同じテストを2回受けていたら**1回目**を採る（きあ「1回目のやつじゃないと、アンフェアになるよ」）。
  ★列の決まりは src/assets/fmt-import.js の EVENT_HEADERS が正本。
    ずれていないことは tests/test_event_cols_parity.py が見張る。

🔴 標準出力に氏名・学籍番号・点数を出さない（件数・教科書名・テスト名まで）。
🔴 実データにつなぐので、走らせるのは**きあ本人**。Claude は走らせない。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
from env_creds import get_master_no, get_master_pw, NO_ENV_MSG  # noqa: E402

# ── 台帳の「イベント」シートの17列。★fmt-import.js の EVENT_HEADERS と同じ並び ──
EVENT_COLS = ["正規化ID", "氏名", "種別", "時点", "級", "回", "総合", "満点", "合否",
              "聴解", "読解", "言語知識", "出席率", "授業数", "出席数", "ソース", "備考"]
EVENT_KIND = "小テスト"
EVENT_SOURCE = "学生ポータル"
NO_BOOK = "（教材なし）"
OUT_NAME = "小テスト結果_台帳イベント_全期間.csv"

# 台帳リポの置き場の候補（きあのPC）。見つからなければ tmp\ に落とす
LEDGER_DIRS = ["scg-student-master-db"]
LEDGER_SUB = Path("マスタDB用データ") / "小テスト"


# ---------------------------------------------------------------- つなぎ口
def _from_api_js() -> tuple[str, str]:
    """接続先と anon キーは `src/assets/api.js` を正本として読む（load_fmt_json.py と同じ）。

    ★ここに書き写さない。写すと2か所になり、片方だけ古くなる。
    """
    import re
    js = (REPO / "src" / "assets" / "api.js").read_text(encoding="utf-8")
    url = re.search(r"['\"](https://[a-z0-9]+\.supabase\.co)['\"]", js)
    key = re.search(r"['\"](eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)['\"]", js)
    if not url or not key:
        raise SystemExit("🔴 src/assets/api.js から接続先か anon キーを読めませんでした。")
    return url.group(1), key.group(1)


BASE, ANON = _from_api_js()
BASE = os.environ.get("SP_URL", BASE)


def req(path: str, method: str = "GET", body=None, token: str | None = None):
    r = urllib.request.Request(BASE + path,
                               data=json.dumps(body).encode("utf-8") if body is not None else None,
                               method=method)
    r.add_header("apikey", ANON)
    r.add_header("Authorization", "Bearer " + (token or ANON))
    if body is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=60) as f:
            raw = f.read().decode("utf-8")
            return f.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:300]}


def login(no: str, pw: str) -> str:
    st, body = req("/auth/v1/token?grant_type=password", "POST",
                   {"email": f"{no}@stu.scg-portal.jp", "password": pw})
    if st != 200 or not isinstance(body, dict) or not body.get("access_token"):
        raise SystemExit(f"🔴 ログインできませんでした（HTTP {st}）。.env の SP_MASTER_* を確かめてください。")
    return body["access_token"]


def get_all(path_no_paging: str, token: str, page: int = 1000) -> list:
    """1000件ずつ全部取る。★PostgREST の既定上限は1000件で、黙って切れる。"""
    out: list = []
    offset = 0
    while True:
        sep = "&" if "?" in path_no_paging else "?"
        st, rows = req(f"{path_no_paging}{sep}limit={page}&offset={offset}", token=token)
        if st != 200:
            raise SystemExit(f"🔴 取得に失敗しました（HTTP {st}）: {path_no_paging.split('?')[0]}")
        rows = rows or []
        out.extend(rows)
        if len(rows) < page:
            return out
        offset += page


# ---------------------------------------------------------------- 組み立て
def normalize_id(student_no) -> str:
    """学籍番号からハイフンを外す＝台帳の「正規化ID」。"""
    return str(student_no or "").replace("-", "").strip()


def ymd(iso: str) -> str:
    """提出日時 → YYYY-MM-DD（台帳の「時点」）。"""
    return str(iso or "")[:10]


def build_events(sets: list, profs: list, attempts: list) -> tuple[list, dict]:
    """受験記録 → イベント行（ヘッダ込み）。集計の数だけを stats に返す。

    ★fmt-import.js の rxBuild("event") と同じ決まりでそろえてある:
      ① 同じ（学生・テスト）が複数あれば**いちばん古い提出**を採る
      ② 「回」は教科書ごとに、**その回の最初の提出が早い順**で 1,2,3…
         （全学生で同じ番号になる＝台帳で横に並べたときに列がそろう）
    """
    set_by_id = {s["id"]: s for s in sets}
    prof_by_id = {p["id"]: p for p in profs}

    # ① 1回目だけ残す（attempts は submitted_at の昇順で来る前提＝先に入ったほうを残す）
    first: dict[tuple, dict] = {}
    skipped_outside = 0
    for a in attempts:
        s, p = set_by_id.get(a["quiz_set_id"]), prof_by_id.get(a["student_id"])
        if not s or not p:
            skipped_outside += 1            # 学生でない人／消えたテスト
            continue
        key = (normalize_id(p["student_no"]), a["quiz_set_id"])
        if key not in first:
            first[key] = a

    # ② 「回」＝教科書ごと、その回の最初の提出が早い順
    first_at: dict[str, str] = {}
    for a in first.values():
        qid, t = a["quiz_set_id"], a["submitted_at"]
        if qid not in first_at or t < first_at[qid]:
            first_at[qid] = t
    by_book: dict[str, list] = defaultdict(list)
    for s in sets:
        if s["id"] in first_at:
            by_book[s.get("source_book") or NO_BOOK].append(s)
    round_of: dict[str, int] = {}
    for book, lst in by_book.items():
        for i, s in enumerate(sorted(lst, key=lambda x: first_at[x["id"]]), start=1):
            round_of[s["id"]] = i

    # ③ 17列にする
    rows = [EVENT_COLS[:]]
    items = []
    for (nid, qid), a in first.items():
        s, p = set_by_id[qid], prof_by_id[a["student_id"]]
        items.append((s.get("source_book") or NO_BOOK, round_of[qid], nid,
                      p.get("display_name") or "", ymd(a["submitted_at"]),
                      a.get("score"), a.get("total"), s.get("title") or ""))
    items.sort(key=lambda x: (x[0], x[1], x[2]))
    for book, rnd, nid, name, at, score, total, title in items:
        r = [""] * len(EVENT_COLS)
        r[0], r[1], r[2], r[3] = nid, name, EVENT_KIND, at
        r[4], r[5], r[6], r[7] = book, rnd, score, total
        r[15], r[16] = EVENT_SOURCE, title
        rows.append(r)

    stats = {"イベント": len(rows) - 1,
             "教科書": len(by_book),
             "回": len(round_of),
             "しぼり外": skipped_outside,
             "重複を捨てた": max(0, len(attempts) - skipped_outside - len(first))}
    return rows, stats


# ---------------------------------------------------------------- 置き場
def pick_out_dir(explicit: str | None) -> tuple[Path, str]:
    """どこへ書くかを決め、**その理由**も返す（黙って別の場所に置かない）。"""
    if explicit:
        return Path(explicit), "--out で指定されました"
    for name in LEDGER_DIRS:
        cand = REPO.parent / name / LEDGER_SUB
        if cand.is_dir():
            return cand, f"隣に {name} があったので、台帳の取り込みフォルダへ"
    return REPO / "tmp", "台帳リポが見つからないので tmp\\ へ（.gitignore 済み）"


def check_overwrite(path: Path) -> None:
    """この形式でないファイルは上書きしない＝手で置いたものを巻き込まない。"""
    if not path.exists():
        return
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            head = next(csv.reader(f), [])
    except Exception:
        head = []
    if [c.strip() for c in head] != EVENT_COLS:
        raise SystemExit(
            f"🔴 {path.name} は同じ形式ではないので、上書きしませんでした。\n"
            "   （1行目の17列が合いません。手で置いたファイルなら、別の名前にしてください）")


def write_csv(path: Path, rows: list) -> None:
    """UTF-8（BOM付き）＋ CRLF＝Excel がそのまま開ける形。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f, lineterminator="\r\n").writerows(rows)


# ---------------------------------------------------------------- 本体
def main() -> int:
    ap = argparse.ArgumentParser(description="小テスト結果を学生マスタDBのイベント形式で書き出す")
    ap.add_argument("--out", help="書き出し先フォルダ（省略時は自動で決める）")
    ap.add_argument("--dry-run", action="store_true", help="件数を出すだけ。ファイルは書かない")
    a = ap.parse_args()

    no, pw = get_master_no(), get_master_pw()
    if not no or not pw:
        print("🔴 SP_MASTER_NO / SP_MASTER_PW がありません。" + NO_ENV_MSG)
        return 1

    print("ログインしています…")
    token = login(no, pw)

    print("読んでいます…")
    sets = get_all("/rest/v1/quiz_sets?select=id,title,source_book&order=created_at.asc", token)
    profs = get_all("/rest/v1/profiles?select=id,student_no,display_name"
                    "&role=eq.student&order=student_no.asc", token)
    attempts = get_all("/rest/v1/attempts?select=student_id,quiz_set_id,score,total,submitted_at"
                       "&order=submitted_at.asc", token)
    print(f"  テスト {len(sets)} / 学生 {len(profs)} / 受験 {len(attempts)}")

    rows, st = build_events(sets, profs, attempts)
    print(f"  → イベント {st['イベント']}件"
          f"（教科書 {st['教科書']} / 回 {st['回']}）"
          f"　2回目以降として捨てた {st['重複を捨てた']}件"
          f"　学生でない人・消えたテスト {st['しぼり外']}件")
    if st["イベント"] == 0:
        print("受験記録がありませんでした。何も書いていません。")
        return 0

    out_dir, why = pick_out_dir(a.out)
    path = out_dir / OUT_NAME
    print(f"書き出し先: {path}\n  理由: {why}")
    if a.dry_run:
        print("--dry-run なので書いていません。")
        return 0
    check_overwrite(path)
    write_csv(path, rows)
    print(f"✅ 書きました（{st['イベント']}行）。"
          "このあと build_master.py を走らせると「小テスト_〈教科書名〉」シートが更新されます。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
