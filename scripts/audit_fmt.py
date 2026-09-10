#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""audit_fmt.py — 教材フォルダの課題登録FMT Excelを全部検査し、不備一覧HTMLを作る（2026-09-10）

`scratch/20260910-fmt-preview/audit_all.py`（検査 → JSON）と `make_report.py`（JSON → HTML）
の2段だった試作を、**1コマンドで通る形**に昇格したもの。2027年2月に作問側が不備を直した
あと、もう一度これを回して再検査する。**DBには絶対に触らない。読むだけ。**

  py -X utf8 scripts\audit_fmt.py
      … 既定の教材フォルダを検査し、tmp\教材の不備一覧.html と同名の .json を書く

  py -X utf8 scripts\audit_fmt.py --dir "...\教材フォルダ" --out tmp\report.html
      … 会社PCなど、フォルダの場所が違うとき

■ 母数の考え方（audit_all.py を引き継ぐ）
  母数 = Excel にあった「問題番号のある行」の総数（取り込めた + 不備で落ちた + まだ書かれていない）。
  取り込めた分だけを母数にすると、落ちた分が分母から消えて率が甘くなる。

■ 直してもらうもの と ただの記録 を混ぜない（KINDS）
  🔴 = 作問側に直してもらうもの／ⓘ・★ = 記録として残すだけ（対応不要）。
  この分類は上から順にマッチするので、**順番を変えない**こと。

■ .xls（旧形式）について
  openpyxl は .xls を読めないので、`*.xlsx` の検査対象には最初から入らない。
  黙って抜け落ちさせないよう、別枠（old_xls_files）で件数だけ数えて報告に出す。

  py -X utf8 -m unittest discover -s tests -p "test_audit_fmt.py" -v
"""
from __future__ import annotations

import argparse
import collections
import html
import json
import re
import sys
import time
import traceback
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_fmt_xlsx as fx  # noqa: E402

# ---------------------------------------------------------------- 既定値
DEFAULT_BASE = Path(
    r"I:\マイドライブ\claude作業場\0.2 claude-work\【学生ポータル】 Student Portal\Googleドライブ教材フォルダ")
DEFAULT_OUT = Path("tmp") / "教材の不備一覧.html"
# きあ判断（2026-09-10）＝もう使わないテキスト。--include-skipped で解除できる
SKIP_DIRS = ["009.JapanGo_語学留学生のための日本語"]
# 問題ファイルではないので検査に混ぜない
EXCLUDE_NAMES = {"000. コンテンツ移行進捗管理.xlsx"}

# warn の文言 → 分類。★「直してもらうもの」と「ただの記録」を混ぜない
# ★順番に意味がある（上から順にマッチ）。「作りかけ」と「不備」を混ぜないこと
KINDS = [
    ("課題登録FMT ではない", "ⓘ FMTでないシート（触らない）", False),
    ("作りかけ", "ⓘ まだ書かれていない問題（作りかけ）", False),
    ("計算結果が入っていない", "🔴 ブックが壊れている（計算結果なし）", True),
    ("選択肢が重複している", "🔴 選択肢の重複", True),
    ("問題番号が重複", "🔴 問題番号の重複", True),
    ("同じ問題の別版", "★ ルビ違いなど同じ問題の別版", False),
    ("画像つきの設問", "ⓘ 画像つき", False),
    ("列目から始まっている", "ⓘ 1列ずれの版（対応済み）", False),
    ("見出しが", "ⓘ 見出しのズレ（位置で読んだ）", False),
    ("飛ばした行", "ⓘ 集計行を飛ばした", False),
    ("取り込めた設問が 0 件", "ⓘ 1問も取り込めなかったシート", False),
    ("同じ範囲", "ⓘ 同じ範囲のシートが複数", False),
    ("解答が", "🔴 設問の不備（解答）", True),
    ("選択肢が", "🔴 設問の不備（選択肢）", True),
    ("問題文", "🔴 設問の不備（問題文）", True),
]

SHEET_KINDS = ("ブックが壊れている", "FMTでないシート", "1問も取り込めなかった",
               "1列ずれ", "見出しのズレ", "集計行", "まだ書かれていない",
               "同じ問題の別版", "同じ範囲")


def kind_of(w: str) -> tuple[str, bool]:
    for key, label, need in KINDS:
        if key in w:
            return label, need
    return "ⓘ その他", False


def pct(n: int, d: int) -> str:
    return f"{n / d * 100:5.1f}%" if d else "    -"


# ---------------------------------------------------------------- 走査
def find_xlsx(base: Path, skip_dirs: list[str]) -> list[Path]:
    return sorted(p for p in base.rglob("*.xlsx")
                  if p.is_file() and not any(d in p.parts for d in skip_dirs)
                  and not p.name.startswith("~$") and p.name not in EXCLUDE_NAMES)


def find_old_xls(base: Path, skip_dirs: list[str]) -> list[Path]:
    """*.xls（旧形式）は openpyxl で開けないので検査対象に入らない。黙って抜け落ちさせず別枠で数える。"""
    return sorted(p for p in base.rglob("*.xls")
                  if p.is_file() and not any(d in p.parts for d in skip_dirs)
                  and not p.name.startswith("~$"))


def scan(base: Path, skip_dirs: list[str]) -> dict:
    """教材フォルダを全部読んで、明細つきの辞書（audit_all.json 相当）を返す。DBには触らない。読むだけ。"""
    files = find_xlsx(base, skip_dirs)
    old_xls = find_old_xls(base, skip_dirs)
    print(f"対象 {len(files)} 本" + (f"（.xls 旧形式 {len(old_xls)} 本は対象外）" if old_xls else ""),
          flush=True)

    t0 = time.time()
    n_sheet = n_q = n_unwritten = n_nonfmt = 0
    kinds: collections.Counter = collections.Counter()
    dropped_rows, warn_rows, failed = [], [], []
    per_book, sheet_rows = [], []

    for n, p in enumerate(files, 1):
        rel = str(p.relative_to(base))
        try:
            sets, warn = fx.build(p, None, None, "", False)
        except Exception as e:
            failed.append({"file": rel, "error": f"{type(e).__name__}: {e}"})
            print(f"  🔴 {rel}\n     {traceback.format_exc(limit=1)}", file=sys.stderr, flush=True)
            continue

        q = sum(len(s["questions"]) for s in sets)
        u = sum(len(s.get("unwritten", [])) for s in sets)
        nf = sum(1 for s in sets if "FMT ではない" in str(s.get("error", "")))
        n_sheet += len(sets)
        n_q += q
        n_unwritten += u
        n_nonfmt += nf
        per_book.append({"file": rel, "sheets": len(sets), "questions": q, "unwritten": u})

        for s in sets:
            sheet_rows.append({"file": rel, "sheet": s["sheet"],
                               "questions": len(s["questions"]),
                               "unwritten": len(s.get("unwritten", [])),
                               "dropped": len(s["dropped"]),
                               "error": s.get("error")})
            for d in s["dropped"]:
                dropped_rows.append({"file": rel, "sheet": s["sheet"],
                                     "seq": d["seq"], "row": d["row"], "reason": d["reason"]})
        for w in warn:
            label, need = kind_of(w)
            kinds[label] += 1
            if need or "画像つき" in label:
                warn_rows.append({"file": rel, "kind": label, "text": w})

        if n % 25 == 0:
            print(f"  … {n}/{len(files)} 本  ({time.time() - t0:.0f}秒)", file=sys.stderr, flush=True)

    # ★母数＝Excel にあった「問題番号のある行」の総数。
    #   取り込めた分だけを母数にすると、落ちた分が分母から消えて率が甘くなる。
    n_rows = n_q + len(dropped_rows) + n_unwritten

    def is_ruby_off(name: str) -> bool:
        return "ルビ" in name and ("なし" in name or "無し" in name)

    def is_ruby_on(name: str) -> bool:
        return "ルビ" in name and not is_ruby_off(name)

    ruby_on = sum(1 for r in sheet_rows if is_ruby_on(r["sheet"]))
    ruby_off = sum(1 for r in sheet_rows if is_ruby_off(r["sheet"]))
    q_ruby_off = sum(r["questions"] for r in sheet_rows if is_ruby_off(r["sheet"]))

    return {
        "base": str(base),
        "scanned_at": date.today().isoformat(),
        "elapsed_sec": round(time.time() - t0, 1),
        "books": per_book,
        "sheets_detail": sheet_rows,
        "dropped": dropped_rows,
        "warnings": warn_rows,
        "failed": failed,
        "old_xls_files": [str(p.relative_to(base)) for p in old_xls],
        "kinds": dict(kinds),
        "unwritten_total": n_unwritten,
        "nonfmt_sheets": n_nonfmt,
        "total": {"books": len(per_book), "sheets": n_sheet, "questions": n_q,
                  "rows": n_rows, "dropped": len(dropped_rows), "unwritten": n_unwritten,
                  "ruby_on_sheets": ruby_on, "ruby_off_sheets": ruby_off,
                  "ruby_off_questions": q_ruby_off},
    }


# ---------------------------------------------------------------- 画面向けの母数つきサマリ
def print_summary(data: dict) -> None:
    T = data["total"]
    n_rows = T["rows"]
    dropped_rows = data["dropped"]

    print("=" * 78)
    print("■ 母数")
    print(f"   ブック                  {T['books']:6,}")
    print(f"   シート                  {T['sheets']:6,}   （ルビあり {T['ruby_on_sheets']} / "
          f"ルビなし {T['ruby_off_sheets']} / ルビ無関係 {T['sheets'] - T['ruby_on_sheets'] - T['ruby_off_sheets']}）")
    print(f"   Excel にあった問題行    {n_rows:6,}   ← ★以下の「問」の母数はこれ")
    print(f"     ├ 取り込めた          {T['questions']:6,}   {pct(T['questions'], n_rows)}")
    print(f"     ├ 不備で落ちた        {T['dropped']:6,}   {pct(T['dropped'], n_rows)}")
    print(f"     └ まだ書かれていない  {T['unwritten']:6,}   {pct(T['unwritten'], n_rows)}")
    print(f"   ※ このうち ルビなし版が {T['ruby_off_sheets']} シート・{T['ruby_off_questions']:,}問（同じ問題の別版）")
    if data.get("old_xls_files"):
        print(f"   ※ .xls 旧形式のため検査対象外  {len(data['old_xls_files'])} 本")
    print(f"   所要 {data['elapsed_sec']:.0f} 秒")

    print(f"\n■ 🔴 不備で取り込めなかった設問   {len(dropped_rows)} / {n_rows:,} 問  {pct(len(dropped_rows), n_rows)}")
    by_reason = collections.Counter(d["reason"].split("（")[0] for d in dropped_rows)
    for r, c in by_reason.most_common():
        print(f"   {c:5d} / {n_rows:,}  {pct(c, n_rows)}   {r}")

    print("\n■ 警告の種類ごと（シート単位のものは母数がシート数）")
    for k, v in sorted(data["kinds"].items(), key=lambda x: (not x[0].startswith("🔴"), -x[1])):
        if any(t in k for t in SHEET_KINDS):
            print(f"   {v:5d} / {T['sheets']:,} シート  {pct(v, T['sheets'])}   {k}")
        else:
            print(f"   {v:5d} / {n_rows:,} 問     {pct(v, n_rows)}   {k}")

    if data["failed"]:
        print(f"\n■ 🔴 開けなかったブック: {len(data['failed'])} 件")
        for f in data["failed"]:
            print(f"   {f['file']}\n      {f['error']}")


# ---------------------------------------------------------------- HTML レポート
CSS = """
:root{--ink:#1f2933;--sub:#66707a;--line:#e4e8ee;--bg:#eceff4;--surface:#fff;
      --brand:#2563eb;--brand-d:#1e40af;--warn:#c62828;--ok:#2f9e44;--hl:#eef2fd}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.7;
     font-family:"Segoe UI Variable","Segoe UI","Yu Gothic UI","Meiryo",sans-serif}
.top{padding:16px 22px;color:#fff;background:linear-gradient(100deg,var(--brand-d),var(--brand) 70%)}
.top h1{margin:0;font-size:1.2rem}
.top .s{font-size:.82rem;color:rgba(255,255,255,.85);margin-top:4px}
.wrap{max-width:980px;margin:0 auto;padding:18px 16px 70px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;
      padding:14px 18px;margin-bottom:14px;box-shadow:0 1px 2px rgba(20,30,55,.06)}
.card h2{margin:0 0 8px;font-size:1rem;color:var(--brand-d)}
.lead{font-size:.9rem}
table{width:100%;border-collapse:collapse;font-size:.87rem}
th,td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--sub);font-weight:600;font-size:.8rem}
td.n{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;font-weight:700}
details{border:1px solid var(--line);border-radius:10px;margin-bottom:8px;background:var(--surface);
        overflow:hidden}
details>summary{cursor:pointer;padding:10px 14px;font-weight:700;font-size:.92rem}
details details{margin:0 12px 8px;border-color:#eef1f5}
details details>summary{font-weight:400;font-size:.87rem;padding:7px 12px}
.cnt{color:var(--warn);font-weight:700;font-size:.8rem;margin-left:8px}
.sheet{font-size:.8rem;color:var(--sub);margin-left:8px;font-weight:400}
.rows{padding:2px 14px 10px}
.row{display:flex;gap:10px;padding:4px 0;border-top:1px dotted var(--line);font-size:.86rem}
.row .q{flex:0 0 8.5em;font-weight:700;color:var(--warn)}
.note{border-left:4px solid var(--warn);background:var(--surface);border-radius:10px;
      padding:12px 16px;margin-bottom:14px;font-size:.88rem}
.note b{color:var(--warn)}
.ok{border-left-color:var(--ok)}
.ok b{color:var(--ok)}
.dim{opacity:.72}
.badge{display:inline-block;font-size:.72rem;border-radius:99px;padding:1px 9px;
       background:var(--hl);color:var(--brand-d);font-weight:700;margin-left:6px}
@media (prefers-color-scheme:dark){
  :root{--ink:#f0f3f6;--sub:#aeb8c2;--line:#3a414b;--bg:#15181d;--surface:#1f242b;--hl:#262c34}
  .top{box-shadow:0 2px 10px rgba(0,0,0,.4)}
}
"""


def esc(s) -> str:
    return html.escape(str(s))


def ranges(nums: list[int]) -> str:
    """[1,2,3,5,6,9] → '問1〜3、問5〜6、問9'"""
    nums = sorted(set(nums))
    out, start, prev = [], None, None
    for n in nums + [None]:
        if start is None:
            start = prev = n
            continue
        if n is not None and n == prev + 1:
            prev = n
            continue
        out.append(f"問{start}" if start == prev else f"問{start}〜{prev}")
        start = prev = n
    return "、".join(out)


def short_reason(r: str) -> str:
    return re.sub(r"（.*?）", "", r).strip()


RUBY_OFF = re.compile(r"(なし|無し)")


def is_secondary(sheet: str) -> bool:
    """ルビあり版を採用したので、ルビなし版の不備は後回し枠へ。"""
    return "ルビ" in sheet and bool(RUBY_OFF.search(sheet))


def render_html(data: dict) -> str:
    """audit_all.json 相当の辞書 → make_report.py の HTML。JavaScriptは使わない（LINE WORKSで開いても動くように）。

    ★渡す相手は作問の先生。だから
      ・直してほしいものと直さなくてよいものを混ぜない
      ・ファイル → シート → 問題番号 の順で、開いて直せる並びにする
      ・連続する問題番号はまとめる（問1〜18 のように）
      ・ルビあり版を採用したので、ルビなし版の不備は後回し枠に分ける
    """
    # ① 設問ごとの不備（dropped）
    per_sheet: dict[tuple[str, str], dict[str, list[int]]] = collections.defaultdict(
        lambda: collections.defaultdict(list))
    for d in data["dropped"]:
        per_sheet[(d["file"], d["sheet"])][short_reason(d["reason"])].append(d["seq"])

    # ② シートごとの不備（warnings のうち 🔴 のもの。設問単位で数えられないもの）
    for w in data["warnings"]:
        if not w["kind"].startswith("🔴"):
            continue
        if "設問の不備" in w["kind"]:
            continue                      # ①と重複するので入れない
        # ★「ブックが壊れている」は import_fmt_xlsx.py 側が文言の先頭に🔴を付けて返す
        #   （他は `[シート名] ...` から始まる）。先頭の記号だけ落としてから読む。
        #   ここで弾くと🔴なのに一覧に出ない＝直してほしいものが静かに漏れる。
        text = re.sub(r"^🔴\s*", "", w["text"])
        m = re.match(r"\[(.+?)\]\s*(?:問(\d+):\s*)?(.*)", text)
        if not m:
            continue
        sheet, seq, body = m.group(1), m.group(2), short_reason(m.group(3))
        per_sheet[(w["file"], sheet)][body].append(int(seq) if seq else 0)

    main_rows, sub_rows = collections.defaultdict(list), collections.defaultdict(list)
    n_main = n_sub = 0
    for (f, sheet), reasons in sorted(per_sheet.items()):
        group = f.split("\\")[0]
        bucket, target = (sub_rows, "sub") if is_secondary(sheet) else (main_rows, "main")
        items = []
        for reason, seqs in sorted(reasons.items(), key=lambda x: -len(x[1])):
            seqs = [s for s in seqs if s]
            items.append((reason, len(seqs) if seqs else 1, ranges(seqs) if seqs else "シート全体"))
        bucket[group].append((f, sheet, items))
        n = sum(i[1] for i in items)
        if target == "main":
            n_main += n
        else:
            n_sub += n

    # ★明細にも母数を出す。「10件」だけでは多いのか少ないのか分からないため。
    SHEET_ROWS: dict[tuple[str, str], int] = {}
    GROUP_ROWS: collections.Counter = collections.Counter()
    for s in data.get("sheets_detail", []):
        n = s["questions"] + s["unwritten"] + s["dropped"]
        SHEET_ROWS[(s["file"], s["sheet"])] = n
        GROUP_ROWS[s["file"].split("\\")[0]] += n

    def ratio(n: int, d: int) -> str:
        return f"{n} / {d:,}問（{n / d * 100:.1f}%）" if d else f"{n}件"

    def render(bucket: dict, dim: bool) -> list[str]:
        L = []
        for group in sorted(bucket):
            rows = bucket[group]
            total = sum(sum(i[1] for i in items) for _, _, items in rows)
            L.append(f"<details{' class=dim' if dim else ''}><summary>{esc(group)}"
                     f"<span class='cnt'>{ratio(total, GROUP_ROWS.get(group, 0))}</span>"
                     f"<span class='sheet'>{len(rows)}シート</span></summary>")
            for f, sheet, items in rows:
                n = sum(i[1] for i in items)
                name = f.split("\\")[-1]
                L.append(f"<details><summary>{esc(name)}<span class='sheet'>／{esc(sheet)}</span>"
                         f"<span class='cnt'>{ratio(n, SHEET_ROWS.get((f, sheet), 0))}</span>"
                         f"</summary><div class='rows'>")
                for reason, cnt, where in items:
                    L.append(f"<div class='row'><div class='q'>{esc(where)}</div>"
                             f"<div>{esc(reason)}</div></div>")
                L.append("</div></details>")
            L.append("</details>")
        return L

    T = data["total"]
    ROWS = T.get("rows") or (T["questions"] + T.get("dropped", 0) + T.get("unwritten", 0))

    def pc(n: int) -> str:
        return f"{n / ROWS * 100:.1f}%" if ROWS else "—"

    L = ["<!DOCTYPE html><html lang='ja'><head><meta charset='UTF-8'>",
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         "<title>教材の不備一覧</title>", f"<style>{CSS}</style></head><body>",
         "<div class='top'><h1>📋 教材データの不備一覧</h1>",
         f"<div class='s'>ヨリソル用の作成Excel {T['books']}本・{T['sheets']}シートを機械で読んで、"
         f"そのままでは出題できないものを拾いました　／　{date.today():%Y年%m月%d日} 作成</div></div>",
         "<div class='wrap'>",

         "<div class='note'><b>これは何か</b><br>"
         "来年度から校内の仕組みで小テストを配信するため、いまある作成用Excelを"
         "<b>そのまま読み込めるか</b>を全ファイル試した結果です。<br>"
         "下に挙げたのは<b>「機械が読んだときに出題できない」もの</b>だけで、"
         "日本語の正しさや問題の質は見ていません。"
         f"（検査対象: <code>{esc(data.get('base', ''))}</code>）</div>",

         "<div class='card'><h2>数でみる</h2>",
         "<div class='lead' style='margin-bottom:8px'>割合はすべて "
         f"<b>Excel にあった問題行 {ROWS:,} 問</b> に対するものです。</div><table>",
         "<tr><th>項目</th><th style='text-align:right'>数</th>"
         "<th style='text-align:right'>割合</th><th>備考</th></tr>",

         f"<tr><td>読んだファイル</td><td class='n'>{T['books']}本</td><td class='n'>—</td>"
         f"<td>{T['sheets']}シート</td></tr>",
         f"<tr><td><b>Excel にあった問題行</b></td><td class='n'>{ROWS:,}問</td>"
         f"<td class='n'>100%</td><td>★これが下の割合の母数</td></tr>",
         f"<tr><td>　├ そのまま使えた</td><td class='n'>{T['questions']:,}問</td>"
         f"<td class='n'>{pc(T['questions'])}</td><td>読み込めました</td></tr>",
         f"<tr><td>　├ <b style='color:#c62828'>出題できない</b></td>"
         f"<td class='n' style='color:#c62828'>{T['dropped']:,}問</td>"
         f"<td class='n' style='color:#c62828'>{pc(T['dropped'])}</td>"
         f"<td>解答や選択肢が足りず、読み込めませんでした</td></tr>",
         f"<tr><td>　└ まだ書かれていない</td><td class='n'>{T['unwritten']:,}問</td>"
         f"<td class='n'>{pc(T['unwritten'])}</td>"
         f"<td>問題番号の枠だけ＝<b>不備ではなく作りかけ</b></td></tr>",

         "<tr><td colspan='4' style='border:none;height:6px'></td></tr>",
         f"<tr><td><b>直していただきたいもの（合計）</b></td>"
         f"<td class='n' style='color:#c62828'>{n_main + n_sub}件</td>"
         f"<td class='n' style='color:#c62828'>{pc(n_main + n_sub)}</td>"
         f"<td>上の「出題できない」{T['dropped']}問＋"
         f"<b>出題はできるが問題として成立していない</b>{n_main + n_sub - T['dropped']}件</td></tr>",
         f"<tr><td>　├ ルビあり版</td><td class='n' style='color:#c62828'>{n_main}件</td>"
         f"<td class='n'>{pc(n_main)}</td><td>下の一覧のとおり</td></tr>",
         f"<tr><td>　└ ルビなし版</td><td class='n'>{n_sub}件</td>"
         f"<td class='n'>{pc(n_sub)}</td>"
         f"<td>ルビあり版を使う方針のため<b>後回しで構いません</b></td></tr>",
         "</table>",
         f"<div class='lead' style='margin-top:8px;color:#66707a'>※ {T['sheets']}シートのうち "
         f"<b>{T.get('ruby_off_sheets', 0)}枚</b>は「ルビなし版」で、同じ問題の別版です"
         f"（{T.get('ruby_off_questions', 0):,}問）。"
         f"これを除いた実質の問題数は <b>{ROWS - T.get('ruby_off_questions', 0):,}問</b> ほどになります。</div>",
         "</div>",

         "<div class='card'><h2>直していただきたいもの</h2>"
         "<div class='lead'>教材のフォルダごとにたたんであります。クリックで開きます。"
         "<b>ファイル名／シート名／問題番号</b>の順に並んでいるので、そのまま開いて直せます。</div></div>"]

    L += render(main_rows, dim=False)

    L += ["<div class='card dim'><h2>ルビなし版の同じ問題（後回しで構いません）</h2>"
          "<div class='lead'>ルビあり版とルビなし版が両方あるファイルでは、"
          "<b>ルビあり版を使う</b>ことにしました。こちらは同じ問題のルビなし版です。</div></div>"]
    L += render(sub_rows, dim=True)

    # ★お願いは実行結果から組み立てる（固定のファイル名を書かない＝再検査のたびに正しい）
    ask_parts = []
    if data.get("failed"):
        items = "".join(f"<li><code>{esc(f['file'])}</code></li>" for f in data["failed"])
        ask_parts.append(
            f"<b>開けなかったファイル（{len(data['failed'])}件）</b>：ファイルが壊れているか、"
            f"読み取れない状態です。<b>Excelで開いて保存し直して</b>いただけると直ります。"
            f"<ul>{items}</ul>")
    if data.get("old_xls_files"):
        items = "".join(f"<li><code>{esc(f)}</code></li>" for f in data["old_xls_files"])
        ask_parts.append(
            f"<b>古い形式（.xls）のファイル（{len(data['old_xls_files'])}件）</b>："
            f"このチェックは新しい形式（.xlsx）しか読めません。<b>.xlsx で保存し直し</b>をお願いします。"
            f"<ul>{items}</ul>")
    if ask_parts:
        L.append("<div class='note'><b>お願い</b><br>" + "<br>".join(ask_parts) + "</div>")

    L += ["<div class='note ok'><b>直さなくてよいもの（参考）</b><br>"
          "・<b>まだ書かれていない問題</b>… 20問の枠に7問だけ書いてある、といった状態。作りかけとして数えています<br>"
          "・<b>「集計」の行</b>… 各シートの最後にある集計行は、問題ではないので飛ばしています<br>"
          "・<b>見出しのちがい・列のずれ</b>… こちら側で吸収しました<br>"
          "・<b>一覧表のシート</b>… 問題文だけの一覧表（課題登録FMTと形が違うシート）は読んでいません</div>",
          "</div></body></html>"]

    return "\n".join(L)


# ---------------------------------------------------------------- main
def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="教材フォルダの課題登録FMT Excelを全部検査し、不備一覧HTMLを作る（DBには触らない・読むだけ）")
    ap.add_argument("--dir", type=Path, default=DEFAULT_BASE,
                    help=f"教材フォルダのルート（既定: {DEFAULT_BASE}）")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"不備一覧HTMLの出力先（既定: {DEFAULT_OUT}）")
    ap.add_argument("--json-out", type=Path, default=None,
                    help="中間JSON（再集計用）の出力先。省略時は --out と同じ場所・同じ名前で拡張子だけ .json")
    ap.add_argument("--include-skipped", action="store_true",
                    help=f"きあ判断で除外しているフォルダ（{', '.join(SKIP_DIRS)}）も検査する")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)

    # ★「見つからない」と「見つかったが0件」を区別する。黙って0件にしない
    if not a.dir.exists():
        print(f"🔴 教材フォルダが見つからない: {a.dir}\n"
              f"   パスを確かめること（会社PCなど場所が違う環境では --dir で渡す）", file=sys.stderr)
        return 2
    if not a.dir.is_dir():
        print(f"🔴 --dir がフォルダではない: {a.dir}", file=sys.stderr)
        return 2

    skip_dirs = [] if a.include_skipped else SKIP_DIRS
    data = scan(a.dir, skip_dirs)
    print_summary(data)

    json_out = a.json_out or a.out.with_suffix(".json")
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明細（再集計用）: {json_out}")

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(render_html(data), encoding="utf-8")
    print(f"レポート: {a.out}")

    return 1 if (data["failed"] or data["total"]["dropped"]) else 0


if __name__ == "__main__":
    sys.exit(main())
