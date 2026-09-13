# -*- coding: utf-8 -*-
r"""test_export_kotest_events.py — 台帳へ渡す「イベント形式」の書き出しを見る（2026-09-13）

**DB不要**。見ているのは3つ。

  ① 17列が**3か所で同じ**か
     src/assets/fmt-import.js の EVENT_HEADERS ／ scripts/export_kotest_events.py の
     EVENT_COLS ／ 台帳リポ scripts/kotest.py の EVENT_COLS。
     ★ここがずれると台帳側は**ファイルを丸ごと飛ばす**（黙って一部だけ入れない作りなので、
       事故は静かではない）。それでも「置いたのに増えない」の原因究明は高くつくので先に見る。
     台帳リポが隣に無ければ、そのぶんだけ飛ばす（家PC以外でも走るように）。

  ② 組み立ての決まり
     1回目を採る／回は教科書ごとに実施順／しぼり外は数える／並び順。

  ③ 上書きの門番
     形式が違うファイルは上書きしない。

  🔴 学籍番号は 999 から降順のダミー帯を使う（実在の番号は 001 から昇順のため）。

  py -X utf8 -m unittest discover -s tests -p "test_export_kotest_events.py" -v
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import export_kotest_events as ex  # noqa: E402


# ---------------------------------------------------------------- ダミー
def _sets():
    return [
        {"id": "s1", "title": "1-①", "source_book": "つなぐ日本語Ⅰ"},
        {"id": "s2", "title": "1-②", "source_book": "つなぐ日本語Ⅰ"},
        {"id": "s3", "title": "漢字1", "source_book": "漢字マスター"},
        {"id": "s9", "title": "だれも受けていない回", "source_book": "つなぐ日本語Ⅰ"},
    ]


def _profs():
    return [
        {"id": "p1", "student_no": "26-0401999", "display_name": "テスト太郎"},
        {"id": "p2", "student_no": "2604998", "display_name": "テスト花子"},
    ]


def _at(pid, sid, score, when):
    return {"student_id": pid, "quiz_set_id": sid, "score": score, "total": 10,
            "submitted_at": when}


class ColumnParity(unittest.TestCase):
    """① 17列が、書く側と読む側で同じか"""

    def test_実装はここ1つだけ(self):
        """ブラウザ側に同じ形式をもう1つ持たない（2026-09-13）。

        ★以前は fmt-import.js にも EVENT_HEADERS / eventRows があった。
          画面のボタンを外して通れる人がいなくなったので、丸ごと外した。
          2つあると、片方だけ直して**ずれても誰も気づけない**。
        """
        js = (ROOT / "src" / "assets" / "fmt-import.js").read_text(encoding="utf-8")
        self.assertNotIn("EVENT_HEADERS", js)
        self.assertNotIn("eventRows", js)

    def test_台帳リポと同じ(self):
        kotest = ROOT.parent / "scg-student-master-db" / "scripts" / "kotest.py"
        if not kotest.exists():
            self.skipTest("台帳リポが隣に無いので飛ばしました")
        src = kotest.read_text(encoding="utf-8")
        m = re.search(r"^EVENT_COLS\s*=\s*\[(.*?)\]", src, re.S | re.M)
        self.assertIsNotNone(m, "kotest.py に EVENT_COLS が見つからない")
        self.assertEqual(re.findall(r'"([^"]+)"', m.group(1)), ex.EVENT_COLS)

    def test_17列ある(self):
        self.assertEqual(len(ex.EVENT_COLS), 17)


class Build(unittest.TestCase):
    """② 組み立ての決まり"""

    def test_1回目を採る(self):
        """同じ人が同じテストを2回受けたら、**古いほう**の点を出す。

        ★きあ「1回目のやつじゃないと、アンフェアになるよ」。
          ここが後勝ちに戻ると、たくさん受け直した人だけ点が上がる。
        """
        at = [_at("p1", "s1", 3, "2026-04-01T09:00:00"),
              _at("p1", "s1", 9, "2026-04-02T09:00:00")]
        rows, st = ex.build_events(_sets(), _profs(), at)
        self.assertEqual(len(rows), 2)                  # 見出し + 1行
        self.assertEqual(rows[1][6], 3)                 # 総合 = 1回目
        self.assertEqual(rows[1][3], "2026-04-01")      # 時点 も1回目
        self.assertEqual(st["重複を捨てた"], 1)

    def test_回は教科書ごとに実施順(self):
        """「回」は教科書の中で 1,2,3…。★別の教科書とは番号を共有しない。"""
        at = [_at("p1", "s2", 5, "2026-04-01T09:00:00"),   # Ⅰの1回目（先に実施）
              _at("p1", "s3", 5, "2026-04-02T09:00:00"),   # 漢字の1回目
              _at("p1", "s1", 5, "2026-04-03T09:00:00")]   # Ⅰの2回目
        rows, _ = ex.build_events(_sets(), _profs(), at)
        got = {(r[4], r[16]): r[5] for r in rows[1:]}
        self.assertEqual(got[("つなぐ日本語Ⅰ", "1-②")], 1)
        self.assertEqual(got[("つなぐ日本語Ⅰ", "1-①")], 2)
        self.assertEqual(got[("漢字マスター", "漢字1")], 1)

    def test_回は全学生で同じ番号(self):
        """あとから受けた人も同じ「回」になる＝台帳で横に並べたとき列がそろう。"""
        at = [_at("p1", "s1", 5, "2026-04-01T09:00:00"),
              _at("p2", "s2", 5, "2026-04-02T09:00:00"),
              _at("p2", "s1", 5, "2026-04-09T09:00:00")]   # 太郎より後に1回目を受けた
        rows, _ = ex.build_events(_sets(), _profs(), at)
        r1 = [r for r in rows[1:] if r[16] == "1-①"]
        self.assertEqual({r[5] for r in r1}, {1})

    def test_誰も受けていない回は出ない(self):
        at = [_at("p1", "s1", 5, "2026-04-01T09:00:00")]
        rows, st = ex.build_events(_sets(), _profs(), at)
        self.assertNotIn("だれも受けていない回", [r[16] for r in rows[1:]])
        self.assertEqual(st["回"], 1)

    def test_しぼり外は黙って消さず数える(self):
        """学生でない人・消えたテストの分は、**件数として出す**（黙って落とさない）。"""
        at = [_at("pX", "s1", 5, "2026-04-01T09:00:00"),   # 学生一覧にいない
              _at("p1", "sX", 5, "2026-04-01T09:00:00"),   # もう無いテスト
              _at("p1", "s1", 5, "2026-04-01T09:00:00")]
        rows, st = ex.build_events(_sets(), _profs(), at)
        self.assertEqual(len(rows), 2)
        self.assertEqual(st["しぼり外"], 2)

    def test_固定の列(self):
        at = [_at("p1", "s1", 7, "2026-04-01T09:00:00")]
        rows, _ = ex.build_events(_sets(), _profs(), at)
        r = rows[1]
        self.assertEqual(r[0], "260401999")       # 正規化ID = ハイフンを外しただけ
        self.assertEqual(r[2], "小テスト")
        self.assertEqual(r[4], "つなぐ日本語Ⅰ")   # 級 = 教科書名
        self.assertEqual(r[7], 10)                # 満点
        self.assertEqual(r[15], "学生ポータル")
        self.assertEqual(r[16], "1-①")            # 備考 = テスト名
        self.assertEqual([r[8], r[9], r[13]], ["", "", ""])   # 合否・聴解・授業数は空

    def test_教科書なしでも落ちない(self):
        sets = [{"id": "s1", "title": "ナシ", "source_book": None}]
        at = [_at("p1", "s1", 5, "2026-04-01T09:00:00")]
        rows, _ = ex.build_events(sets, _profs(), at)
        self.assertEqual(rows[1][4], ex.NO_BOOK)

    def test_並びは教科書_回_学籍番号(self):
        at = [_at("p2", "s1", 5, "2026-04-01T09:00:00"),
              _at("p1", "s1", 5, "2026-04-01T09:00:00"),
              _at("p1", "s3", 5, "2026-04-02T09:00:00")]
        rows, _ = ex.build_events(_sets(), _profs(), at)
        self.assertEqual([(r[4], r[5], r[0]) for r in rows[1:]],
                         [("つなぐ日本語Ⅰ", 1, "260401999"),
                          ("つなぐ日本語Ⅰ", 1, "2604998"),
                          ("漢字マスター", 1, "260401999")])

    def test_ハイフンが無ければそのまま(self):
        """1年生の学籍番号（26xxx…）はもともとハイフンが無い＝生IDと正規化IDが同じ。"""
        at = [_at("p2", "s1", 5, "2026-04-01T09:00:00")]
        rows, _ = ex.build_events(_sets(), _profs(), at)
        self.assertEqual(rows[1][0], "2604998")

    def test_受験ゼロ(self):
        rows, st = ex.build_events(_sets(), _profs(), [])
        self.assertEqual(rows, [ex.EVENT_COLS])
        self.assertEqual(st["イベント"], 0)


class Overwrite(unittest.TestCase):
    """③ 上書きの門番"""

    def test_同じ形式なら通す(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.csv"
            ex.write_csv(p, [ex.EVENT_COLS, ["2604999"] + [""] * 16])
            ex.check_overwrite(p)                 # 例外が出なければよい

    def test_違う形式は止める(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.csv"
            p.write_text("氏名,点数\r\nテスト太郎,5\r\n", encoding="utf-8-sig")
            with self.assertRaises(SystemExit):
                ex.check_overwrite(p)

    def test_無ければ通す(self):
        with tempfile.TemporaryDirectory() as d:
            ex.check_overwrite(Path(d) / "まだ無い.csv")

    def test_BOM付きCRLFで書く(self):
        """Excel がそのまま開ける形。★台帳側も utf-8-sig で読む。"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.csv"
            ex.write_csv(p, [ex.EVENT_COLS, ["2604999"] + [""] * 16])
            raw = p.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            self.assertIn(b"\r\n", raw)


class OutDir(unittest.TestCase):
    """置き場を黙って変えない"""

    def test_outを指定したらそこ(self):
        d, why = ex.pick_out_dir(r"C:\どこか")
        self.assertEqual(d, Path(r"C:\どこか"))
        self.assertIn("--out", why)

    def test_理由を必ず返す(self):
        d, why = ex.pick_out_dir(None)
        self.assertTrue(why.strip())
        self.assertIsInstance(d, Path)


class ScreenHasNoLedgerButton(unittest.TestCase):
    """マスター画面に台帳のボタンを**置かない**（2026-09-13 きあ指示）。

    ★きあ「学生マスタDBは他人に触らせない。他人は存在を知らない前提で動いてほしい」
      ＝画面に置くと、押せるかどうか以前に**台帳の存在が漏れる**。
      うっかり戻したら、ここで落ちる。
    """

    def setUp(self):
        self.html = (ROOT / "src" / "master.html").read_text(encoding="utf-8")

    def test_ボタンが無い(self):
        self.assertNotIn('id="rx-event"', self.html)

    def test_台帳の名前を画面に出さない(self):
        """コメントには書いてよい（読むのはきあと私だけ）。**出る文字**に無いことを見る。"""
        body = re.sub(r"<!--.*?-->", "", self.html, flags=re.S)   # HTMLのコメントを外す
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)         # JSのコメントも外す
        body = re.sub(r"(?m)^\s*//.*$", "", body)
        self.assertNotIn("学生マスタDB", body)
        self.assertNotIn("学生マスターDB", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
