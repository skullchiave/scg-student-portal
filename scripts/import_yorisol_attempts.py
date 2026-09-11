#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""import_yorisol_attempts.py — ヨリソルの受験履歴CSVを、縦持ちの中間形式(JSON)へ開く（2026-09-11）

ヨリソルの契約は 2027-02-28 で終了する。**受験履歴はそれ以降 二度と取り出せない。**
書き出す作業そのもの（ヨリソルへのログイン）はきあの手番。このスクリプトは
「書き出した CSV → 扱いやすい中間形式」の変換だけを行う。**DB へは接続しない。**

★これは `import_yorisol.py`（**設問**バンクを読む・出口側の別物）とは別。混ぜないこと。
  こちらが読むのは「誰が・どの設問に・何と答えたか」の**受験履歴**。

■ なぜ SQL を出さないか（決め打ちしない）
  受験履歴を DB の何に・どう入れるかは、まだ決まっていない
  （記録として／評価の根拠として／分析用 — 用途が決まれば落とす範囲が決まる。まだ未決）。
  ★DBの形を先に決めると、あとで用途が変わったときに作り直しになる。
  そこで、ここでは**元の情報を1つも捨てない縦持ちの中間形式（JSON）**だけを出す。
  SQL は用途が決まってから、別のスクリプトで足せばよい。
  （`import_fmt_xlsx.py` が「画像やカテゴリを、今は使わなくても JSON には必ず残す」のと同じ考え方）

■ 読む相手の形（CLAUDE.md より・実物はまだ手元に無いので、位置で読む前提を置いている）
  1ファイル ＝ 1クラス × 1回。
  列 ＝ アカウント／氏名／ステータス／合計点（先頭4列・固定）
       ＋ 設問ごとに（回答・正誤・スコア）の3列1組が繰り返す（横持ち）。
  ⚠ 「いつ」の列が無い（誰がいつ答えたかは残らない）
  ⚠ 設問IDが無い。列名（表示ラベル）だけが設問バンクとの突合の手がかりなので、
    **列名の原文を（先頭4列・設問グループとも）そのまま JSON に残す**。

  ★実物が来た時点でこの前提（先頭4列・3列1組・位置で読む）が崩れていたら、
    このスクリプトを直すこと。今はCLAUDE.mdの記述だけが根拠。

■ 縦持ち（1行 = 1 学生 × 1 設問）にする理由
  横持ちのままだと「設問が増えるたびに列が増える」形なので、あとで集計・突合をする側が
  つらい。学生1人・設問1問につき1行に開いておけば、どんな用途にも寄せやすい。

■ 黙って捨てない
  読めなかった行（列数が見出しと合わない）・空の行・設問の列が3列1組で割り切れない場合は、
  **理由つきで必ず出す**（件数と行番号だけ。値は出さない）。
  0件でも `dropped_rows: []` を書く＝「無かった」ことの証拠として残す。

■ 🔴 PII（最重要）
  このファイルには実在の学生の氏名・学籍番号が入る。
  - **標準出力（画面）には値を出さない。** 出してよいのは件数・列名・型・分布まで
    （列名＝設問の表示ラベルは「値」ではなく構造なので出してよい）
  - `--out-json` の出力には元の値がすべて入る＝**リポにコミットしない場所（tmp/ など）に置くこと**。
    `.gitignore` は `tmp/` と `*.csv` を既に除外している
  - このリポは public。実データのサンプルをテストにもドキュメントにも貼らない
    （テストはこのファイルの中で作るダミーCSVだけを使う）

■ 使い方
  py -X utf8 scripts\import_yorisol_attempts.py --csv 受験履歴_1A.csv --class 1A
      … 変換して結果だけ表示（ファイルは書かない・値は出さない）

  py -X utf8 scripts\import_yorisol_attempts.py --csv 受験履歴_1A.csv ^
      --out-json tmp\attempts_1A.json
      … クラス名をファイル名から推測できればそのまま通る（例: "1A_2026-10-08.csv" → 1A）

■ 出力（JSON。1件 = 1ファイルぶん）
  {
    "source_file": "...", "class_name": "1A", "encoding_used": "utf-8-sig"|"cp932",
    "header": [...元の見出し全列...],
    "fixed_columns": {"account": {"index":1,"header":"..."}, "name": {...}, "status": {...}, "total_score": {...}},
    "question_groups": [ {"question_index":1, "columns":[5,6,7], "headers":["...","...","..."], "label":"..."} , ... ],
    "rows": [   # ← 1行 = 1（学生 × 設問）
      {"source_row":2, "account":"...", "name":"...", "status":"...", "total_score":"...",
       "question_index":1, "question_label":"...", "question_headers":["...","...","..."],
       "answer":"...", "correct":"...", "score":"..."}, ...
    ],
    "dropped_rows": [ {"row": n, "reason": "..."} ],   # 空でも必ず書く
    "ragged_tail_columns": 0
  }
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import re
import sys
from pathlib import Path

# ★既定は utf-8-sig → cp932 の順に試す（BOM付きUTF-8・Shift_JIS の両方に当たるため）
ENCODING_TRY_ORDER = ("utf-8-sig", "cp932")

# 先頭4列（固定・位置で読む）。見出し文字列は検査だけに使う（違っていても位置優先で読み続ける）
FIXED_COLS = [
    ("account", ("アカウント", "学籍番号", "ログインID", "ID")),
    ("name", ("氏名", "名前", "学生氏名")),
    ("status", ("ステータス", "状態", "受験状況")),
    ("total_score", ("合計点", "得点", "合計", "点数")),
]
N_FIXED = len(FIXED_COLS)

# クラス名らしき先頭トークン（例: "1A_2026-10-08.csv" → "1A"）
CLASS_NAME_RE = re.compile(r"^([0-9]{1,2}[A-Za-z])")


# ---------------------------------------------------------------- 読み込み
def read_csv_rows(path: Path, encoding: str) -> tuple[list[list[str]], str]:
    """(全行のリスト, 実際に使った文字コード) を返す。1行目も含む（見出しの切り離しは呼び出し側）。"""
    raw = path.read_bytes()
    if encoding != "auto":
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as e:
            raise SystemExit(f"指定した文字コード（{encoding}）で読めない: {path}（{e}）") from e
        used = encoding
    else:
        text = used = None
        for enc in ENCODING_TRY_ORDER:
            try:
                text = raw.decode(enc)
                used = enc
                break
            except UnicodeDecodeError:
                continue
        if used is None:
            raise SystemExit(
                f"文字コードが判別できない（{' → '.join(ENCODING_TRY_ORDER)} とも失敗）: {path}")
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as e:
        raise SystemExit(f"CSVとして読めない（引用符が壊れている等）: {path}（{e}）") from e
    return rows, used


def guess_class_name(stem: str) -> str:
    """ファイル名（拡張子なし）の先頭が「数字+英字」ならクラス名とみなす。無ければ空文字。"""
    m = CLASS_NAME_RE.match(stem)
    return m.group(1) if m else ""


# ---------------------------------------------------------------- 変換
def build(header: list[str], data_rows: list[list[str]], class_name: str, source_name: str,
          allow_ragged: bool = False) -> tuple[dict, list[str]]:
    """(中間形式の dict, 警告のリスト) を返す。DBには触らない。"""
    warn: list[str] = []
    n_cols = len(header)
    if n_cols < N_FIXED:
        raise SystemExit(f"見出しが {n_cols} 列しかない（固定4列ぶんも無い）: {source_name}")

    n_extra = n_cols - N_FIXED
    n_groups, rem = divmod(n_extra, 3)
    ragged_tail = 0
    if rem:
        msg = (f"設問の列が3列1組になっていない（固定{N_FIXED}列を除いた{n_extra}列が3の倍数でない。"
               f"あまり{rem}列）")
        if not allow_ragged:
            raise SystemExit(
                "🔴 " + msg + f"。{source_name}"
                "\n   --allow-ragged-columns を付けると、割り切れる分だけ読んで末尾を捨てます（要確認）。")
        warn.append("⚠ " + msg + f"＝末尾の{rem}列は読まずに捨てました（--allow-ragged-columns）")
        ragged_tail = rem

    # 見出しの検査。★位置で読むので、ここは気づくためだけ（違っていても読み続ける）
    for i, (key, cands) in enumerate(FIXED_COLS):
        got = header[i].strip()
        if got not in cands:
            warn.append(f"{i + 1}列目の見出しが「{got or '(空)'}」＝想定は {list(cands)}"
                        f"（位置で読むので取り込みは続ける）")

    question_groups: list[dict] = []
    for g in range(n_groups):
        base = N_FIXED + g * 3
        headers3 = [header[base], header[base + 1], header[base + 2]]
        label = next((h for h in headers3 if h.strip()), f"設問{g + 1}")
        if not any(h.strip() for h in headers3):
            warn.append(f"設問{g + 1}（列{base + 1}〜{base + 3}）: 見出しが3列とも空"
                        f"＝設問バンクとの突合の手がかりが無い")
        question_groups.append({
            "question_index": g + 1,
            "columns": [base + 1, base + 2, base + 3],   # 1始まり（人が見る列番号と合わせる）
            "headers": headers3,
            "label": label,
        })

    # ★列名だけでは設問バンクと一意に突合できない懸念を先に出す（値ではなく列名の比較）
    dup_labels = sorted(l for l, c in collections.Counter(
        qg["label"] for qg in question_groups).items() if c > 1)
    if dup_labels:
        warn.append(f"設問ラベルが重複している（{len(dup_labels)}種・例: {dup_labels[:5]}）"
                    f"＝列名だけでは設問バンクと一意に突合できない可能性")

    out_rows: list[dict] = []
    dropped_rows: list[dict] = []
    n_empty = n_mismatch = 0
    for r_i, row in enumerate(data_rows, start=2):   # 2行目から（1行目は見出し）
        if not any(c.strip() for c in row):
            n_empty += 1
            dropped_rows.append({"row": r_i, "reason": "空の行"})
            continue
        if len(row) != n_cols:
            n_mismatch += 1
            dropped_rows.append({"row": r_i,
                "reason": f"列数が見出しと合わない（見出し{n_cols}列・この行{len(row)}列）"})
            continue

        account, name, status, total_score = (
            row[0].strip(), row[1].strip(), row[2].strip(), row[3].strip())
        for qg in question_groups:
            b = qg["columns"][0] - 1
            out_rows.append({
                "source_row": r_i,
                "account": account, "name": name, "status": status, "total_score": total_score,
                "question_index": qg["question_index"], "question_label": qg["label"],
                "question_headers": qg["headers"],
                "answer": row[b], "correct": row[b + 1], "score": row[b + 2],
            })

    if n_empty:
        warn.append(f"空の行: {n_empty}件")
    if n_mismatch:
        warn.append(f"列数が合わない行: {n_mismatch}件")

    result = {
        "source_file": source_name,
        "class_name": class_name,
        "header": header,
        "fixed_columns": {key: {"index": i + 1, "header": header[i]}
                           for i, (key, _) in enumerate(FIXED_COLS)},
        "question_groups": question_groups,
        "rows": out_rows,
        "dropped_rows": dropped_rows,       # ★0件でも書く＝「無かった」ことの証拠
        "ragged_tail_columns": ragged_tail,
    }
    return result, warn


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="ヨリソルの受験履歴CSVを、縦持ちの中間形式(JSON)へ変換する（DBには触らない）")
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--class", dest="class_name", default="",
                    help="クラス名（例: 1A）。省略時はファイル名の先頭から推測を試みる")
    ap.add_argument("--encoding", choices=("auto",) + ENCODING_TRY_ORDER, default="auto",
                    help="文字コード。既定 auto は " + " → ".join(ENCODING_TRY_ORDER) + " の順に試す")
    ap.add_argument("--allow-ragged-columns", action="store_true",
                    help="設問の列が3列1組で割り切れなくても、割り切れる分だけ読んで残りを捨てる（既定は止める）")
    ap.add_argument("--out-json", type=Path)
    a = ap.parse_args(argv)

    if not a.csv.exists():
        print(f"ファイルが無い: {a.csv}", file=sys.stderr)
        return 2

    rows_raw, used_enc = read_csv_rows(a.csv, a.encoding)
    if not rows_raw:
        print(f"空のCSV: {a.csv}", file=sys.stderr)
        return 2
    header, data_rows = [h.strip() for h in rows_raw[0]], rows_raw[1:]

    class_name = a.class_name or guess_class_name(a.csv.stem)
    if not class_name:
        print("クラス名が分かりません。--class で指定してください（例: --class 1A）", file=sys.stderr)
        return 2

    result, warn = build(header, data_rows, class_name, a.csv.name, a.allow_ragged_columns)

    # ★標準出力には値を出さない。出してよいのは件数・列名・型・分布まで。
    n_students = len({r["source_row"] for r in result["rows"]})
    n_numeric_score = sum(1 for r in result["rows"] if re.fullmatch(r"-?\d+(\.\d+)?", r["score"] or ""))
    status_dist = collections.Counter(r["status"] for r in result["rows"])

    print(f"{a.csv.name}（文字コード: {used_enc}）")
    print(f"クラス: {class_name}")
    print(f"読み込んだ行数: {len(data_rows)}件（見出しを除く）／学生の行として読めた: {n_students}件")
    print(f"設問（列グループ）: {len(result['question_groups'])}件"
          f"（{'／'.join(qg['label'] for qg in result['question_groups'][:5])}"
          f"{' ほか' if len(result['question_groups']) > 5 else ''}）")
    print(f"生成した（学生×設問）行: {len(result['rows'])}件"
          f"（うちスコアが数値に見えるもの: {n_numeric_score}件）")
    if status_dist:
        print("ステータスの分布: " + " / ".join(f"{k or '(空)'}={v}件" for k, v in status_dist.most_common()))

    if result["dropped_rows"]:
        print(f"\n⚠ 読めなかった／空の行 {len(result['dropped_rows'])}件:")
        for d in result["dropped_rows"]:
            print(f"   {d['row']}行目: {d['reason']}")
    else:
        print("\n読めなかった行・空の行: 0件")

    if warn:
        print(f"\n⚠ 目を通すこと {len(warn)}件:")
        for w in warn:
            print("   " + w)
    else:
        print("\n検査: 問題なし")

    if a.out_json:
        a.out_json.parent.mkdir(parents=True, exist_ok=True)
        result["encoding_used"] = used_enc
        a.out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON を書いた: {a.out_json}")
        print("🔴 この JSON には実在の学生の氏名・学籍番号が入ります。リポにコミットしない場所に置くこと"
              "（tmp/ は .gitignore 済み）")
    else:
        print("\n（--out-json を付けるとファイルに書きます）")

    return 1 if (warn or result["dropped_rows"]) else 0


if __name__ == "__main__":
    sys.exit(main())
