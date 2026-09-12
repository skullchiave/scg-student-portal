#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""教材フォルダを丸ごと歩いて、課題登録FMT の Excel を1本ずつ取り込み SQL にする。

`scripts/import_fmt_xlsx.py` が「Excel 1本」を受け持つのに対して、こちらは
**どのファイルのどのシートを入れて、どれを入れないか**を決める役。
DB には触らない（SQL と JSON を書き出すだけ）。

★このスクリプトがいちばん間違えると痛いところ＝**黙って捨てること**。
  だから「入れたもの」と同じ重さで「除いたものと、その理由」を必ず出す。
  除外は全部この1か所に書いてあり、`--show-rules` で読める。

使い方:
    # 何が入って何が除かれるか、読むだけ（SQLは書かない）
    py -X utf8 scripts\\import_fmt_bulk.py --book "001.つなぐ日本語初級" --dry-run

    # SQL を tmp\\ に書き出す
    py -X utf8 scripts\\import_fmt_bulk.py --book "001.つなぐ日本語初級"

🔴 出力先は tmp\\（.gitignore 済み）から変えないこと。
   このリポは public で、設問データを入れると
   「公開は学内に限られる」という著作権の見解の前提が崩れる（2026-09-11）。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_BASE = Path(
    r"I:\マイドライブ\claude作業場\0.2 claude-work\【学生ポータル】 Student Portal"
    r"\Googleドライブ教材フォルダ"
)
DEFAULT_OUT = REPO / "tmp"

# ---------------------------------------------------------------- 除外のルール
# ★ここが正本。増やすときは必ず理由を書くこと。
#   「なんとなく要らなさそう」で足さない＝あとから理由を再構成できなくなる。

# ① 「全体」のような大きいシート。
#    ★2026-09-11、ここも1度間違えた。「他シートの寄せ集めだから捨てる」と判断しかけたが、
#      現物を照合したら**重なりは9%しかなく、全体にしかない問題が398問＋289問**あった。
#      ＝寄せ集めではなく、別の問題集だった。捨てていたら 687問を落としていた。
#      （最初の照合で0%と出たのは、全体シートが**1列ずれ**ていて生の列で読めていなかったため。
#        取り込み口 build_sheet に読ませて初めて正しく比べられた）
#    → **捨てない**。ただし1回の小テストとしては大きすぎるので、警告だけ出す。
BIG_SHEET_QUESTIONS = 60  # これを超えたら「1回のテストとしては大きい」と知らせる

# ② ルビなし版。きあ判断で「ルビあり版を採用」（2026-09-10）。
#    ⚠ 実データでは名前が8通りにばらけていた:
#      ルビあり / ルビなし / ルビふり / ルビふり版 / ルビなし版 / ルビふり前 / ルビふり後 / ルビ振り
#    「ルビふり前」＝ルビを振る前＝ルビなし、なので除外側。
RUBY_OFF = re.compile(r"ルビ\s*(なし|無し|ナシ)|ルビ\s*ふり\s*前|ルビ\s*振り\s*前")
RUBY_ON = re.compile(r"ルビ\s*(あり|有り|アリ)|ルビ\s*ふり|ルビ\s*振り")

# ③ テンプレート本体。import_fmt_xlsx.py 側も既定で外すが、ここでも落とす。
SHEET_TEMPLATE = re.compile(r"FMT|ＦＭＴ|テンプレート")

# ④ 同じ範囲のシートが新旧2枚あるとき、どちらを採るか。
#    「（新）」が付いているほうを採る。付いていないほうが旧版。
NEWER_MARK = re.compile(r"[（(]\s*新\s*[)）]")

def lesson_key(sheet: str) -> str:
    """新旧の重複を見つけるための鍵。

    ★2026-09-11 にここを1度間違えた。最初は「丸数字を落として最初の数字を拾う」
      にしていたが、教材によって丸数字の意味が逆だった:
        まとめテスト    「①1-3」    … ①＝通し番号、1-3＝課の範囲
        文法チェックテスト「1-①」    … 1＝課、①＝その課の何枚目
      そのため `1-①` `1-②` `1-③`（同じ課の**別のテスト**）を重複と誤判定して、
      入れるべき 1,647問のうち大半を捨てるところだった。

    正しい鍵＝**シート名そのもの**（「（新）」と空白と全半角の揺れだけ均す）。
    つまり「名前が（新）以外そっくり同じ2枚」だけを新旧の重複とみなす。
    これなら教材ごとの命名の違いに引きずられない。
    """
    s = NEWER_MARK.sub("", sheet)
    s = s.replace("－", "-").replace("ー", "-").replace("　", " ")
    return re.sub(r"\s+", "", s).strip()


class Decision:
    """1シートについての判定。理由を必ず持つ。"""

    __slots__ = ("file", "sheet", "questions", "keep", "reason")

    def __init__(self, file: str, sheet: str, questions: int, keep: bool, reason: str):
        self.file, self.sheet, self.questions = file, sheet, questions
        self.keep, self.reason = keep, reason


def decide(sheets: list[dict]) -> list[Decision]:
    """1ファイルぶんのシート一覧から、入れる／入れないを決める。

    sheets の要素は audit_fmt.py の sheets_detail 相当:
      {"file": 相対パス, "sheet": シート名, "questions": 問数, ...}
    """
    out: list[Decision] = []

    # --- まず単独で落ちるもの ---
    survivors: list[dict] = []
    for s in sheets:
        name, n = s["sheet"], s.get("questions", 0)
        if n == 0:
            out.append(Decision(s["file"], name, n, False, "問題が1問も取れないシート"))
        elif SHEET_TEMPLATE.search(name):
            out.append(Decision(s["file"], name, n, False, "テンプレート本体"))
        elif RUBY_OFF.search(name):
            out.append(Decision(s["file"], name, n, False, "ルビなし版（ルビあり版を採用）"))
        else:
            survivors.append(s)

    # --- 同じ範囲が2枚以上あるものを片付ける ---
    groups: dict[str, list[dict]] = defaultdict(list)
    for s in survivors:
        groups[lesson_key(s["sheet"])].append(s)

    for key, g in groups.items():
        if len(g) == 1:
            s = g[0]
            out.append(Decision(s["file"], s["sheet"], s["questions"], True, ""))
            continue

        newer = [s for s in g if NEWER_MARK.search(s["sheet"])]
        if len(newer) == 1:
            for s in g:
                if s is newer[0]:
                    out.append(Decision(s["file"], s["sheet"], s["questions"], True,
                                        f"同じ範囲が{len(g)}枚。（新）を採用"))
                else:
                    out.append(Decision(s["file"], s["sheet"], s["questions"], False,
                                        f"同じ範囲の旧版（「{newer[0]['sheet']}」を採用）"))
        else:
            # ★どちらを採るか機械では決められない。黙って選ばずに、全部落として人に投げる。
            for s in g:
                out.append(Decision(s["file"], s["sheet"], s["questions"], False,
                                    f"🔴 同じ範囲「{key}」が{len(g)}枚あり、"
                                    f"どれが新しいか決められない（人が決めること）"))

    out.sort(key=lambda d: (d.file, d.sheet))
    return out


# ------------------------------------------------- 中身で見る重複（名前では分からない）
def content_dedup(base: Path, decisions: list[Decision]) -> list[Decision]:
    """入れると決めたシートを実際に読んで、**中身が完全に同じもの**を1枚に寄せる。

    ★名前の照合だけでは絶対に見つからない型。2026-09-11 に実物で見つかった:
      文法チェックテストⅡ の `26-②`〜`30-②` の14枚が `24-③` と1問たがわず同じだった。
      ＝**第26〜30課ぶんはまだ書かれておらず、24-③をコピーしたまま**置かれている。
      そのまま入れると「27-①」という名前で第24課の問題が配られる。
      名前は正しく見えるので、画面を見ても気づけない。

    最初に現れた1枚を採り、残りは理由つきで落とす。読めなかったシートは落とさない
    （読めないことを理由に捨てると、静かに消える側になるため）。
    """
    import hashlib

    from openpyxl import load_workbook

    sys.path.insert(0, str(HERE))
    import import_fmt_xlsx as imp

    keep = [d for d in decisions if d.keep]
    rest = [d for d in decisions if not d.keep]

    byfile: dict[str, list[Decision]] = defaultdict(list)
    for d in keep:
        byfile[d.file].append(d)

    sigs: dict[str, list[Decision]] = defaultdict(list)
    unreadable: list[Decision] = []

    for rel, ds in byfile.items():
        try:
            wb = load_workbook(base / rel, data_only=True)
        except Exception:
            unreadable += ds
            continue
        for d in ds:
            try:
                built, _ = imp.build_sheet(wb[d.sheet], d.sheet, "")
                qs = built["questions"]
                if not qs:
                    unreadable.append(d)
                    continue
                blob = "||".join(q["prompt"] + ">" + "|".join(q["choices"]) for q in qs)
                sigs[hashlib.sha1(blob.encode("utf-8")).hexdigest()].append(d)
            except Exception:
                unreadable.append(d)
        wb.close()

    out = list(rest) + unreadable
    for _, group in sigs.items():
        if len(group) == 1:
            out.append(group[0])
            continue
        first = group[0]
        out.append(Decision(first.file, first.sheet, first.questions, True,
                            f"中身が同じシートが{len(group)}枚。最初の1枚を採用"))
        for d in group[1:]:
            out.append(Decision(d.file, d.sheet, d.questions, False,
                                f"中身が「{first.sheet}」と1問たがわず同じ"
                                f"（＝まだ書かれていない可能性が高い）"))
    out.sort(key=lambda d: (d.file, d.sheet))
    return out


# ---------------------------------------------------------------- 教材を歩く
def load_audit(audit_json: Path) -> dict:
    with audit_json.open(encoding="utf-8") as f:
        return json.load(f)


def walk(audit: dict, book: str | None) -> dict[str, list[dict]]:
    """audit の sheets_detail を、ファイルごとにまとめる。"""
    byfile: dict[str, list[dict]] = defaultdict(list)
    for s in audit["sheets_detail"]:
        rel = s["file"]
        top = rel.replace("\\", "/").split("/")[0]
        if book and top != book:
            continue
        byfile[rel].append(s)
    return byfile


def out_stem(rel: str) -> str:
    """出力ファイル名。**元の相対パスと1対1**でなければならない。

    ★2026-09-11 にここで事故った。最初は `Path(rel).stem` を
      `[^0-9A-Za-z一-龥ぁ-んァ-ヶー]+` で潰していたが、この文字クラスに
      **ローマ数字（Ⅰ Ⅱ Ⅲ）が入っていなかった**。その結果
        …文法チェックテストⅠ.xlsx → _ヨリソル_文法チェックテスト_.sql
        …文法チェックテストⅡ.xlsx → _ヨリソル_文法チェックテスト_.sql  ← 同じ名前
      となり、**Ⅰの結果（440問ぶん）がⅡに黙って上書きされた**。
      例外も警告も出ない＝出力を見ても気づけない型。

    なので名前は「読める部分」＋「相対パス全体のハッシュ」にする。
    読める部分だけが衝突しても、ハッシュが違えば別ファイルになる。
    """
    import hashlib

    nice = re.sub(r"[^0-9A-Za-z぀-ヿ㐀-鿿Ⅰ-ⅿ]+", "_",
                  Path(rel).stem).strip("_")[:36]
    h = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:8]
    return f"{nice}_{h}" if nice else h


def title_prefix_of(rel: str) -> str:
    """一覧に出す見出し。ファイル名から作る。

    シート名だけだと「7-9」「全体」のようになり、**どの教材のどれか分からない**。
    87件、いずれ437件が並ぶので、名前だけで見分けがつく必要がある。

        ★ヨリソル_文法チェックテストⅠ.xlsx      → 文法チェックテストⅠ
        ★JapanGo_まとめテストⅡ（作成用）.xlsx   → まとめテストⅡ

    ★や業者名（ヨリソル／JapanGo）を落とすのは、**先生に見せる言葉ではない**ため。
    「（作成用）」「（作成例）」も作り手側の符丁なので落とす。
    """
    s = Path(rel).stem
    s = re.sub(r"^[★☆\s]+", "", s)
    s = re.sub(r"^(ヨリソル|JapanGo|japango)[_\-\s]*", "", s)
    s = re.sub(r"[（(](作成用|作成例|コピーして使用)[)）]", "", s)
    return re.sub(r"[_\s]+", " ", s).strip()


def run_one(base: Path, rel: str, keep_sheets: list[str], book: str,
            out_dir: Path, ruby: str, dry: bool) -> tuple[int, str]:
    """Excel 1本を import_fmt_xlsx.py に渡して SQL を書かせる。"""
    xlsx = base / rel
    out_sql = out_dir / f"{out_stem(rel)}.sql"
    out_json = out_dir / f"{out_stem(rel)}.json"

    cmd = [sys.executable, "-X", "utf8", str(HERE / "import_fmt_xlsx.py"),
           "--xlsx", str(xlsx),
           "--ruby", ruby,
           "--source-book", book,
           "--source-file", rel,
           "--title-prefix", title_prefix_of(rel),
           # ★ import_fmt_xlsx.py は「同じ課の範囲のシートが複数あると止まる」作り。
           #   ここではそれを解除する。理由＝文法チェックテストは **1つの課に3〜4枚が正常**
           #   （16-① 16-② 16-③ …）なので、課が重なること自体は不備ではない。
           #   本当に見たいのは「中身が同じか」で、それは content_dedup が
           #   1問ずつ突き合わせて済ませてある（名前ではなく中身で見ている）。
           #   ＝向こうの見張りを外すかわりに、こちらでより強い検査を通している。
           "--allow-duplicate-lesson",
           "--out-sql", str(out_sql),
           "--out-json", str(out_json)]
    for s in keep_sheets:
        cmd += ["--sheet", s]

    if dry:
        return 0, f"（--dry-run なので走らせていません）→ {out_sql.name}"

    # 🔴 同じ名前を2回書かない。out_stem を直したので起きないはずだが、
    #    「黙って上書きされた」事故を二度と起こさないための最後の見張り。
    if out_sql.exists():
        return 1, f"🔴 出力先がもうある（上書きしません）: {out_sql.name}"

    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = (p.stdout or "") + (p.stderr or "")

    # ★ import_fmt_xlsx.py は「★警告があった」だけでも終了コード1を返す。
    #   SQL が書けているかどうかとは別の話なので、**終了コードだけで失敗と決めない**。
    #   実際に書けたか＝ファイルが在って中身があるか、で見る。
    if not out_sql.exists() or out_sql.stat().st_size == 0:
        return 1, log.strip()[-1200:] or f"SQL が書かれなかった（exit={p.returncode}）"

    warns = [ln.strip() for ln in log.splitlines() if ln.lstrip().startswith("★")]
    note = out_sql.name + (f"  ⚠警告{len(warns)}件" if warns else "")
    return 0, note


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="教材フォルダを歩いて課題登録FMT を取り込み SQL にする（DBには触らない）")
    ap.add_argument("--base", type=Path, default=DEFAULT_BASE, help="教材フォルダのルート")
    ap.add_argument("--audit-json", type=Path, default=REPO / "tmp" / "教材の不備一覧.json",
                    help="audit_fmt.py が書いた中間JSON（どのシートに何問あるかを読む）")
    ap.add_argument("--book", default=None,
                    help="教材フォルダ名。例 001.つなぐ日本語初級（省略＝全部）")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT, help="SQL/JSON の出力先")
    ap.add_argument("--ruby", default="keep", choices=["keep", "strip", "html"])
    ap.add_argument("--dry-run", action="store_true",
                    help="入れる／除くの判定だけ出して、SQL は書かない")
    ap.add_argument("--show-rules", action="store_true", help="除外ルールを表示して終わる")
    ap.add_argument("--skip-content-check", action="store_true",
                    help="中身を読んでの重複検査を飛ばす（速いが、名前だけでは分からない重複を見逃す）")
    a = ap.parse_args(argv)

    if a.show_rules:
        print("除外のルール（scripts/import_fmt_bulk.py の先頭が正本）:")
        print("  ① 寄せ集めシート     :", SHEET_AGGREGATE.pattern)
        print("  ② ルビなし版         :", RUBY_OFF.pattern)
        print("  ③ テンプレート       :", SHEET_TEMPLATE.pattern)
        print("  ④ 同じ範囲が2枚以上  : （新）が付いているほうを採る。決められなければ止める")
        print("  ⑤ 0問のシート       : 入れない")
        return 0

    if not a.audit_json.exists():
        print(f"🔴 {a.audit_json} がありません。先に scripts/audit_fmt.py を回してください。")
        return 2

    audit = load_audit(a.audit_json)
    byfile = walk(audit, a.book)
    if not byfile:
        print(f"🔴 教材フォルダ {a.book!r} に当たるシートがありませんでした。")
        return 2

    a.out_dir.mkdir(parents=True, exist_ok=True)

    all_dec: list[Decision] = []
    for rel, sheets in sorted(byfile.items()):
        all_dec += decide(sheets)

    # 名前で決めたあと、実際に読んで中身の重複も落とす（--skip-content-check で飛ばせる）
    if not a.skip_content_check:
        all_dec = content_dedup(a.base, all_dec)

    keep = [d for d in all_dec if d.keep]
    drop = [d for d in all_dec if not d.keep]
    blocked = [d for d in drop if d.reason.startswith("🔴")]

    # ------------------------------------------------ 入れるもの／除くものを出す
    print(f"教材フォルダ : {a.book or '（全部）'}")
    print(f"ファイル     : {len(byfile)} 本")
    print(f"シート       : {len(all_dec)} 枚 → 入れる {len(keep)} 枚 ／ 入れない {len(drop)} 枚")
    print(f"問題         : 入れる {sum(d.questions for d in keep):,} 問 "
          f"／ 入れない {sum(d.questions for d in drop):,} 問")
    print()

    print("── 入れないもの（理由つき・ここを必ず読むこと）" + "─" * 20)
    bykind: dict[str, list[Decision]] = defaultdict(list)
    for d in drop:
        bykind[d.reason].append(d)
    for reason, ds in sorted(bykind.items(), key=lambda x: -sum(y.questions for y in x[1])):
        print(f"  {len(ds):>3}枚 / {sum(d.questions for d in ds):>5}問  {reason}")
        for d in ds[:6]:
            print(f"        {Path(d.file).name} :: {d.sheet!r}")
        if len(ds) > 6:
            print(f"        …ほか {len(ds)-6} 枚")
    if not drop:
        print("  （なし）")
    print()

    # 1回の小テストとしては大きすぎるもの。捨てはしないが、知らせる。
    big = [d for d in keep if d.questions > BIG_SHEET_QUESTIONS]
    if big:
        print(f"⚠ 1回のテストとしては大きいシート（{BIG_SHEET_QUESTIONS}問超）"
              f"— 入れますが、そのまま配らないこと:")
        for d in sorted(big, key=lambda x: -x.questions):
            print(f"   {d.questions:>5}問  {Path(d.file).name} :: {d.sheet!r}")
        print("   → 問題集として持っておき、配るときは実施回で範囲を決めてください。")
        print()

    if blocked:
        print("🔴 人が決めるまで進められないものがあります:")
        for d in blocked:
            print(f"   {Path(d.file).name} :: {d.sheet!r} — {d.reason}")
        print("   → どちらを使うか決めてから、もう一度回してください。")
        return 1

    if a.dry_run:
        print("（--dry-run。SQL は書いていません）")
        return 0

    # ------------------------------------------------ 実際に SQL を書く
    print("── SQL を書き出します " + "─" * 30)
    keep_by_file: dict[str, list[str]] = defaultdict(list)
    for d in keep:
        keep_by_file[d.file].append(d.sheet)

    ng = 0
    written: list[str] = []
    for rel, names in sorted(keep_by_file.items()):
        top = rel.replace("\\", "/").split("/")[0]
        code, info = run_one(a.base, rel, names, top, a.out_dir, a.ruby, a.dry_run)
        mark = "  " if code == 0 else "🔴"
        print(f"{mark} {len(names):>3}枚  {Path(rel).name}  → {info}")
        if code == 0:
            written.append(info)
        else:
            ng += 1

    print()
    print(f"書けたファイル: {len(written)} 本" + (f" ／ 失敗 {ng} 本" if ng else ""))
    print(f"出力先: {a.out_dir}")
    print("🔴 この中身はリポに入れないこと（tmp/ は .gitignore 済み）")
    return 1 if ng else 0


if __name__ == "__main__":
    raise SystemExit(main())
