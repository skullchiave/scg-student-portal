# -*- coding: utf-8 -*-
r"""check_board.py — 進捗ボードの「n / m」と棒の幅がそろっているかを確かめる（2026-09-13）

進捗ボード（ドライブ側の運用書類）は、領域ごとに「5 / 6」という数字と、その下に棒を持つ。
**数字と棒を手で二重に持っている**ので、片方だけ直すとずれる。
2026-09-11 にきあが目で見つけた（B が 6/6 なのに 33%、F が 2/3 なのに 2%）。
ボード側の JS が画面上で警告を出すようにはしたが、**出す前に気づける**ほうがよい。

  py -X utf8 scripts\check_board.py
  py -X utf8 scripts\check_board.py "別の場所\進捗ボード.html"

★なぜブラウザを使わないか（2026-09-13 に2回続けて道具に騙された）
  (1) 相対パスで chrome --dump-dom を呼んだら **別のページ** が返ってきて、
      「ずれ警告なし」という嘘のOKが出た
  (2) 絶対パスに直したら、今度は **<script> の本文** に警告の文言が入っているせいで
      「警告が出ている」と誤検出した（この案件で4回目の「説明文と検査語の衝突」）
  → 判定に要るのは数字と幅の突き合わせだけで、ブラウザは要らない。

🔴 DBにもリポにも触らない。読むだけ。
"""
import re
import sys
from pathlib import Path

# 既定の置き場。★進捗ボードはリポではなくドライブ側（運用の書類）にある
DEFAULT = Path(r"I:\マイドライブ\claude作業場\0.2 claude-work"
               r"\【学生ポータル】 Student Portal\進捗ボード.html")


def main() -> int:
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not p.exists():
        print(f"🔴 見つかりません: {p}")
        return 2
    s = p.read_text(encoding="utf-8")
    # ★<script> の中は「説明」なので検査の対象から外す（検査語と説明文の衝突を断つ）
    body = re.sub(r"<script\b.*?</script>", "", s, flags=re.S)

    cards = re.findall(
        r'<div class="area[^"]*"><div class="t"><b>(.*?)</b><span>(.*?)</span></div>\s*'
        r'<div class="mini"><i style="width:(\d+)%"></i></div>', body, re.S)

    print(f"■ 領域カード {len(cards)} 枚")
    bad: list[str] = []
    done = total = 0
    for name, label, w in cards:
        nice = re.sub("<[^>]+>", "", name)
        m = re.search(r"(\d+)\s*/\s*(\d+)", label)
        if not m:
            bad.append(f"{nice}: 「n / m」が読めない（{label}）")
            continue
        n, d = int(m.group(1)), int(m.group(2))
        done += n
        total += d
        # 0件でも「そこに棒がある」と分かるように 2% を置く（ボード側の JS と同じ決め）
        want = 2 if n == 0 else round(n / d * 100)
        if int(w) != want:
            bad.append(f"{nice}: HTMLは {w}% ・正しくは {want}%")
        print(f"  {'✅' if int(w) == want else '🔴'} {nice[:26]:26s} {n:2d} / {d:2d}   "
              f"幅 {w:>3s}%（正しくは {want}%）")

    pct = round(done / total * 100) if total else 0
    print(f"\n■ 合計  {done} / {total} = {pct}%")
    m = re.search(r"完成までの全(\d+)工程のうち、終わったもの</span><b>(\d+)%</b>", body)
    mw = re.search(r'<div class="bar"><i style="width:(\d+)%"></i></div>', body)
    if not m:
        bad.append("全体のラベルが読めない")
    else:
        if int(m.group(1)) != total:
            bad.append(f"全体の分母が {m.group(1)} ・正しくは {total}")
        if int(m.group(2)) != pct:
            bad.append(f"全体の割合が {m.group(2)}% ・正しくは {pct}%")
        ok = int(m.group(1)) == total and int(m.group(2)) == pct
        print(f"  {'✅' if ok else '🔴'} ラベル: 全{m.group(1)}工程 / {m.group(2)}%")
    if not mw:
        bad.append("全体の棒が読めない")
    elif int(mw.group(1)) != pct:
        bad.append(f"全体の棒が {mw.group(1)}% ・正しくは {pct}%")
    else:
        print(f"  ✅ 棒: {mw.group(1)}%")

    print()
    for tag in ("div", "ul", "li", "h2", "h3"):
        o = len(re.findall(rf"<{tag}[\s>]", body))
        c = len(re.findall(rf"</{tag}>", body))
        print(f"  {'✅' if o == c else '🔴'} {tag}: 開 {o} / 閉 {c}")
        if o != c:
            bad.append(f"{tag} タグが釣り合わない（{o}/{c}）")

    if bad:
        print("\n🔴 直すところ:")
        for b in bad:
            print("   -", b)
        return 1
    print("\n✅ 数字・棒・タグ すべてそろっています")
    return 0


if __name__ == "__main__":
    sys.exit(main())
