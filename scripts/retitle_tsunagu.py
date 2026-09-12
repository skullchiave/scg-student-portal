#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""つなぐ日本語の回を、教科書の単元で分けて、課の順に並べ替える。

■ なぜ（きあ指示・2026-09-12）
  「つなぐにほんごでまとめると多すぎるので、つなぐにほんごⅠ／Ⅱ に分けてください。
    まとめテストに関しては 1-① 1-② 2-① 2-② 2-③ 3-① 3-② 3-③ まとめ1-3 4-① …
    みたいにしてください。」
  ＝**毎日のチェックテストとまとめテストを、教科書の進む順に1本に並べる。**

■ 何を書き換えるか（設問そのものには触らない）
  source_book … 'つなぐ日本語Ⅰ' / 'つなぐ日本語Ⅱ'   ← 先生の画面の「教材で絞る」がこれで分かれる
  title       … '1-①' / 'まとめ 1-3' / '（問題集）全体'
  lesson      … 学生の画面に出るバッジ＝**課そのもの**（"1課" / "1〜3課"）。
                ★title と同じ文字にしない。先生の一覧に「テスト名」と「課」が
                  並ぶので、同じ値だと1列ぶん無駄になる（2026-09-12 に一度やった）
  sort_key    … 並べるための値。'01-1' / '03-9'（まとめは範囲の最後）/ '99-0'（問題集）

■ どこから決めるか
  **出どころ（source_file / source_sheet）から機械的に**決める。手で決めない。
  巻    … source_file のフォルダに 'Ⅰ' か 'Ⅱ' が入っている
  種別  … source_file に 'まとめテスト' が入っていれば まとめ、そうでなければ 毎日
  課    … source_sheet から数字を拾う（'1-①'→1 / '①1-3 （新）'→1〜3）

■ 流儀
  ・DB へは**先生の権限**で書く（画面と同じ経路）。管理者権限は要らない
  ・--dry-run で、何がどう変わるかを全部見てから流す
  ・設問・選択肢・正解・受験記録には一切触らない

使い方:
    py -X utf8 scripts\\retitle_tsunagu.py --dry-run
    py -X utf8 scripts\\retitle_tsunagu.py
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import load_fmt_json as L  # noqa: E402
from env_creds import get_teacher_no, get_teacher_pw, NO_ENV_MSG  # noqa: E402

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def volume_of(source_file: str) -> str | None:
    """巻（Ⅰ/Ⅱ）。フォルダ名に入っている。"""
    parts = re.split(r"[\\/]", source_file or "")
    for p in parts:
        if p.strip() == "Ⅰ":
            return "Ⅰ"
        if p.strip() == "Ⅱ":
            return "Ⅱ"
    return None


def is_matome(source_file: str) -> bool:
    return "まとめテスト" in (source_file or "")


def parse_sheet(sheet: str) -> tuple[int | None, int | None, int | None]:
    """シート名から (課, 範囲の終わり, 何枚目) を取る。

        '1-①'        → (1, None, 1)
        '12-④'       → (12, None, 4)
        '①1-3 （新）' → (1, 3, None)     ※ 先頭の丸数字は通し番号なので課ではない
        '全体'        → (None, None, None)
    """
    s = (sheet or "").strip()
    if not s or "全体" in s:
        return (None, None, None)

    # まとめテスト形式: 先頭の丸数字（通し番号）を外してから「1-3」を読む
    body = s.lstrip(CIRCLED).strip()
    m = re.match(r"^\s*(\d+)\s*[-‐−–~〜]\s*(\d+)", body)
    if m:
        return (int(m.group(1)), int(m.group(2)), None)

    # 毎日のチェックテスト形式: 「12-④」
    m = re.match(r"^\s*(\d+)\s*[-‐−–]\s*([" + CIRCLED + r"])", s)
    if m:
        return (int(m.group(1)), None, CIRCLED.index(m.group(2)) + 1)

    # 「12-4」のような半角の版も一応
    m = re.match(r"^\s*(\d+)\s*[-‐−–]\s*(\d+)\s*$", s)
    if m:
        return (int(m.group(1)), None, int(m.group(2)))
    return (None, None, None)


def plan_for(row: dict) -> dict | None:
    """1件ぶんの「こう変える」を作る。決められなければ None。"""
    sf, sheet = row.get("source_file") or "", row.get("source_sheet") or ""
    vol = volume_of(sf)
    if not vol:
        return None
    book = "つなぐ日本語" + vol
    lesson, upto, nth = parse_sheet(sheet)

    if "全体" in sheet:
        # 他のシートに無い問題を多く含む「問題集」。1回のテストには大きすぎるので最後に置く
        return {"source_book": book, "title": "（問題集）全体",
                "lesson": "問題集", "sort_key": "99-0"}

    if is_matome(sf):
        if lesson is None or upto is None:
            return None
        # ★まとめは、その範囲の最後の課の**うしろ**に来る。3-③（03-3）の次＝03-9
        return {"source_book": book, "title": f"まとめ {lesson}-{upto}",
                "lesson": f"{lesson}〜{upto}課", "sort_key": f"{upto:02d}-9"}

    if lesson is None or nth is None:
        return None
    return {"source_book": book, "title": f"{lesson}-{CIRCLED[nth - 1]}",
            "lesson": f"{lesson}課", "sort_key": f"{lesson:02d}-{nth}"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="つなぐ日本語の回を単元で分けて課の順に並べる")
    # ★既定は付け替えた**あと**の名前。何度流しても同じ結果になる（初回は --book "001.つなぐ日本語初級"）
    ap.add_argument("--book", action="append",
                    help="いまの source_book（繰り返し指定可。既定＝つなぐ日本語Ⅰ と Ⅱ）")
    ap.add_argument("--dry-run", action="store_true", help="変えずに、何がどうなるかだけ出す")
    a = ap.parse_args(argv)

    no, pw = get_teacher_no(), get_teacher_pw()
    if not (no and pw):
        print("🔴", NO_ENV_MSG)
        return 2
    tok = L.login(no, pw)
    if not tok:
        print("🔴 先生としてログインできませんでした。")
        return 2

    import urllib.parse
    books = a.book or ["つなぐ日本語Ⅰ", "つなぐ日本語Ⅱ"]
    rows = []
    for b in books:
        st, part = L.req("/rest/v1/quiz_sets?select=id,title,lesson,source_book,source_file,source_sheet"
                         "&source_book=eq." + urllib.parse.quote(b) + "&limit=1000", token=tok)
        if st != 200 or not isinstance(part, list):
            print("🔴 読めませんでした:", b, st, str(part)[:160])
            return 2
        rows += part
    print(f"対象: {len(rows)} 件（source_book = {' / '.join(books)}）")

    plans, skipped = [], []
    for r in rows:
        p = plan_for(r)
        (plans if p else skipped).append((r, p))

    if skipped:
        print(f"\n🔴 決められなかったもの {len(skipped)} 件（人が見ること）:")
        for r, _ in skipped[:10]:
            print(f"   {r['title']!r}  sheet={r.get('source_sheet')!r}")
        print("   → シート名の形が想定と違います。parse_sheet を直すこと。")
        return 1

    plans.sort(key=lambda x: (x[1]["source_book"], x[1]["sort_key"]))
    print("\n── 並べ替えたあとの順番（これが先生の画面に出る順です）" + "─" * 12)
    cur = None
    for r, p in plans:
        if p["source_book"] != cur:
            cur = p["source_book"]
            n = sum(1 for _, q in plans if q["source_book"] == cur)
            print(f"\n■ {cur}（{n}件）")
        print(f"   {p['sort_key']}  {p['title']}")

    if a.dry_run:
        print("\n（--dry-run。書き換えていません）")
        return 0

    print("\n── 書き換えます " + "─" * 30)
    ok = ng = 0
    for r, p in plans:
        st, _ = L.req("/rest/v1/quiz_sets?id=eq." + r["id"], "PATCH", p, token=tok)
        if st in (200, 204):
            ok += 1
        else:
            ng += 1
            print(f"   🔴 {r['title']!r}: HTTP {st}")
    print(f"書き換えた: {ok} 件" + (f" ／ 失敗 {ng} 件" if ng else ""))
    return 1 if ng else 0


if __name__ == "__main__":
    raise SystemExit(main())
