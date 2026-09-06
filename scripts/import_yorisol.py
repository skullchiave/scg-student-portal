#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""import_yorisol.py — ヨリソルの設問バンク CSV を、学生ポータルの形へ変換する（2026-09-05）

ヨリソルの契約は 2027年2月で終了する。設問の中身は、それまでに CSV で書き出して
こちら側へ持ってくる。このスクリプトは「持ってきた CSV → ポータルの3テーブル」の変換だけを行う。
**DB へは接続しない。** 出力はファイル（JSON と SQL）で、流し込むかどうかは人が決める。

使い方:
  py -X utf8 scripts\import_yorisol.py --questions 設問.csv --answers 回答.csv
      … 変換して結果だけ表示（ファイルは書かない）
  py -X utf8 scripts\import_yorisol.py --questions 設問.csv --answers 回答.csv ^
      --out-json tmp\quiz.json --out-sql tmp\quiz.sql --title "つなぐ初級 第1回"

入力（ヨリソルの書き出し・cp932）:
  設問CSV  … システムID / 設問名 / カテゴリ名 / 設問文/説明 / 形式 ほか
  回答CSV  … 設問システムID / 設問名 / 正解(0|1) / 選択肢/ラベル / 選択肢表示順

出力（ポータルのスキーマ）:
  quiz_sets(title, lesson, is_open)          … 1件。**is_open は false** で作る（誤って学生に見せない）
  questions(quiz_set_id, seq, prompt)
  question_choices(question_id, idx, label)  … 選択肢は1問につき2〜12個（★2択固定ではない）
  question_answers(question_id, <正解列>)    … 値は「何番目が正解か」（1始まりの番号）

★選択肢の数について（2026-09-06 に判明）
  実データを書き出したら 3個=142問 / 4個=84問 / 2個=21問 で、**2択は少数派**だった。
  公開中の設問はすべて4択。2択専用のままでは1問も移せなかったので、いくつでも入る形に変えた。

★設問文の HTML について
  ヨリソルの設問文には <br /> と <span style="color:..."> が入っている。
  ポータルは prompt を textContent で描くので、タグをそのまま入れると**文字として表示されてしまう**。
  そこで <br> は改行に、それ以外のタグは外して中身だけ残す（色は失われる）。
  改行を活かすには .prompt に white-space:pre-line が要る（2026-09-05 に app.css へ入れた）。
"""
from __future__ import annotations

import argparse
import collections
import csv
import html
import io
import json
import re
import sys
from pathlib import Path

ENCODINGS = ("cp932", "utf-8-sig", "utf-8")
# question_answers の正解列名。ライブのスキーマと違ったらここだけ直す（--answer-col でも指定可）
# ★2026-09-06 に 'correct'（a/b）から correct_idx（何番目か）へ変わった
DEFAULT_ANSWER_COL = "correct_idx"
# 1設問あたりの選択肢の上限。question_choices の check (idx between 1 and 12) と合わせること
MAX_CHOICES = 12


# ---------------------------------------------------------------- 読み込み
def read_csv(path: Path) -> list[dict]:
    raw = path.read_bytes()
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"文字コードが判別できない: {path}")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise SystemExit(f"空のCSV: {path}")
    head = [h.strip() for h in rows[0]]
    return [dict(zip(head, r)) for r in rows[1:] if any(c.strip() for c in r)]


def need(row: dict, *names: str) -> str:
    """列名の揺れを吸収して1つ取る"""
    for n in names:
        if n in row:
            return row[n]
    raise SystemExit(f"必要な列が見つからない: {names} / 実際の列={list(row)}")


# ---------------------------------------------------------------- HTML → 文字
BR = re.compile(r"<br\s*/?>", re.I)
TAG = re.compile(r"<[^>]+>")
SPAN = re.compile(r"<span\b", re.I)


def html_to_text(s: str) -> tuple[str, int]:
    """(変換後テキスト, 外した装飾タグの数) を返す"""
    dropped = len(SPAN.findall(s))
    s = BR.sub("\n", s)
    s = TAG.sub("", s)
    s = html.unescape(s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip(), dropped


# ---------------------------------------------------------------- 変換
def build(qrows: list[dict], arows: list[dict]) -> tuple[list[dict], list[str]]:
    warn: list[str] = []
    by_q: dict[str, list[dict]] = {}
    for r in arows:
        by_q.setdefault(need(r, "設問システムID", "システムID").strip(), []).append(r)

    out = []
    for seq, r in enumerate(qrows, 1):
        sid = need(r, "システムID").strip()
        name = need(r, "設問名").strip()
        prompt, dropped = html_to_text(need(r, "設問文/説明", "設問文", "説明"))
        fmt = (r.get("形式") or "").strip()
        cat = (r.get("カテゴリ名") or "").strip()

        if fmt and fmt != "単一選択":
            warn.append(f"[{sid}] 形式が「{fmt}」＝ポータルは単一選択しか持っていない。手当てが要る")
            continue
        if not prompt:
            warn.append(f"[{sid}] 設問文が空")
        if "<" in prompt or "&" in prompt:
            warn.append(f"[{sid}] 変換後にまだ < か & が残っている（タグの取りこぼし）")

        # ★選択肢は2個固定ではない（実データは3〜4択が多い）。2〜MAX_CHOICES 個まで受ける。
        ch = by_q.get(sid, [])
        if len(ch) < 2:
            warn.append(f"[{sid}] 選択肢が {len(ch)} 個（2個以上ないと出題できない）")
            continue
        if len(ch) > MAX_CHOICES:
            warn.append(f"[{sid}] 選択肢が {len(ch)} 個（上限 {MAX_CHOICES} 個）")
            continue
        order_key = "選択肢表示順"
        if all((c.get(order_key) or "").strip().isdigit() for c in ch):
            ch.sort(key=lambda c: int(c[order_key]))
        labels = [html_to_text(need(c, "選択肢/ラベル", "選択肢", "ラベル"))[0] for c in ch]
        flags = [(c.get("正解") or "").strip() for c in ch]
        hits = [i for i, f in enumerate(flags) if f in ("1", "○", "TRUE", "true", "はい", "Y")]

        if len(hits) != 1:
            warn.append(f"[{sid}] 正解が {len(hits)} 個（ちょうど1個であること）")
            continue
        if not all(labels):
            warn.append(f"[{sid}] 空の選択肢がある")
            continue

        out.append({
            "source_id": sid,
            "name": name,
            "category": cat,
            "seq": seq,
            "prompt": prompt,
            "choices": labels,            # 表示順そのまま。番号は 1 から
            "correct_idx": hits[0] + 1,   # ★何番目が正解か（1始まり）
            "_dropped_styles": dropped,
        })
    return out, warn


# ---------------------------------------------------------------- SQL
def sq(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def to_sql(items: list[dict], title: str, lesson: str, answer_col: str) -> str:
    L = [
        "-- ヨリソル設問バンク → 学生ポータル（scripts/import_yorisol.py が生成）",
        f"-- 設問 {len(items)} 件 / 正解列 = {answer_col}",
        "-- ★ is_open = false で作る。中身を確かめてから教師画面で公開すること",
        "-- ★ 流す前に: 正解列の名前が実際のスキーマと合っているかだけ確認（--answer-col で変えられる）",
        "begin;",
        "do $$",
        "declare v_set uuid; v_q uuid;",
        "begin",
        f"  insert into quiz_sets(title, lesson, is_open) values ({sq(title)}, {sq(lesson)}, false) returning id into v_set;",
    ]
    for it in items:
        L.append(
            "  insert into questions(quiz_set_id, seq, prompt) values "
            f"(v_set, {it['seq']}, {sq(it['prompt'])}) returning id into v_q;"
        )
        vals = ", ".join(f"(v_q, {i}, {sq(lab)})" for i, lab in enumerate(it["choices"], start=1))
        L.append(f"  insert into question_choices(question_id, idx, label) values {vals};")
        # ★正解は選択肢を入れたあと（外部キーが選択肢を指しているため）
        L.append(f"  insert into question_answers(question_id, {answer_col}) values (v_q, {it['correct_idx']});")
    L += ["end $$;", "commit;", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ヨリソルの設問CSVを学生ポータルの形へ変換する（DBには触らない）")
    ap.add_argument("--questions", required=True, type=Path)
    ap.add_argument("--answers", required=True, type=Path)
    ap.add_argument("--title", default="", help="quiz_sets.title（省略時はカテゴリ名の末尾）")
    ap.add_argument("--lesson", default="", help="quiz_sets.lesson（省略時は空）")
    ap.add_argument("--answer-col", default=DEFAULT_ANSWER_COL)
    ap.add_argument("--out-json", type=Path)
    ap.add_argument("--out-sql", type=Path)
    a = ap.parse_args(argv)

    qrows = read_csv(a.questions)
    arows = read_csv(a.answers)
    items, warn = build(qrows, arows)

    cats = sorted({i["category"] for i in items if i["category"]})
    title = a.title or (cats[0].split("\\")[-1] if cats else "ヨリソル取り込み")

    print(f"設問CSV {len(qrows)} 行 / 回答CSV {len(arows)} 行 → 変換できた設問 {len(items)} 件")
    print(f"カテゴリ: {cats if cats else '（なし）'}")
    print(f"quiz_sets.title = {title!r} / lesson = {a.lesson!r} / is_open = false")
    styled = sum(1 for i in items if i["_dropped_styles"])
    if styled:
        print(f"⚠ 装飾タグ(<span>)を外した設問: {styled} 件 — 空欄の赤い色が消えます（文字は残る）")
    nl = sum(1 for i in items if "\n" in i["prompt"])
    if nl:
        print(f"改行を含む設問: {nl} 件 — .prompt の white-space:pre-line が要る（対応済み）")
    if items:
        dist = collections.Counter(len(i["choices"]) for i in items)
        print("選択肢の数: " + " / ".join(f"{k}個={v}問" for k, v in sorted(dist.items())))
    if warn:
        print(f"\n⚠ 手当てが要るもの {len(warn)} 件:")
        for w in warn:
            print("   " + w)
    else:
        print("\n検査: 問題なし（全問 単一選択・正解1つ・タグの取りこぼしなし）")

    if a.out_json:
        a.out_json.parent.mkdir(parents=True, exist_ok=True)
        a.out_json.write_text(json.dumps(
            {"title": title, "lesson": a.lesson, "is_open": False, "questions": items},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON を書いた: {a.out_json}")
    if a.out_sql:
        a.out_sql.parent.mkdir(parents=True, exist_ok=True)
        a.out_sql.write_text(to_sql(items, title, a.lesson, a.answer_col), encoding="utf-8")
        print(f"SQL を書いた: {a.out_sql}")
    if not a.out_json and not a.out_sql:
        print("\n（--out-json / --out-sql を付けるとファイルに書きます）")
    return 1 if warn else 0


if __name__ == "__main__":
    sys.exit(main())
