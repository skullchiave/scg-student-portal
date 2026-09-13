# -*- coding: utf-8 -*-
r"""test_daily_kotest_update.py — 毎日の自動更新の骨格を見る（2026-09-13）

**実データに触りません。DBも要りません。** 見ているのは4つ。

  ① 🔴 家PCでは走らない（SCG_ALLOW_REAL が無ければ、何もせずに止まる）
  ② 🔴 マスクできないときは、外のプログラムの出力をログに書かない
  ③ タスクの中身（9:00 / 16:30 / ログオン後 / 取りこぼしを取り戻す）
  ④ 前回うまくいった日を、ログから読める
     ★「走らなかった日」は目印が出ないので、これが唯一の気づき口。

  py -X utf8 -m unittest discover -s tests -p "test_daily_kotest_update.py" -v
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import daily_kotest_update as du  # noqa: E402


class SiteGuard(unittest.TestCase):
    """① どのPCか決まっていなければ走らない"""

    def test_印が無ければ何もしない(self):
        """★走る時刻はPCごとに違う（会社＝朝夕／家＝深夜）ので、
        どちらか決まっていないと動けない。印が無い＝まだ設定していないPC。
        """
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(du.ENV_SITE, None)
            with mock.patch.object(du, "ledger_home") as lh, \
                 mock.patch.object(du.subprocess, "run") as sub:
                self.assertEqual(du.do_run(), 2)
                lh.assert_not_called()      # 台帳の場所すら探しに行かない
                sub.assert_not_called()     # 外のプログラムを1つも起動しない

    def test_知らない値は通さない(self):
        with mock.patch.dict(os.environ, {du.ENV_SITE: "yes"}):
            with mock.patch.object(du.subprocess, "run") as sub:
                self.assertEqual(du.do_run(), 2)
                sub.assert_not_called()

    def test_大文字でも読む(self):
        with mock.patch.dict(os.environ, {du.ENV_SITE: "Office"}):
            self.assertEqual(du.site(), "office")


class Schedule(unittest.TestCase):
    """時間で分けて競合を避ける（きあ決定）"""

    def test_時間帯が重ならない(self):
        """🔴 これがこの仕組みの競合よけそのもの。

        きあ「職場PCはPCがついてる前提だから朝〜夕方まで。
              自宅PCは常につけてるから24時とかにすれば競合はまずまずしない」
        ここが重なると、同じ xlsx を2台が書いて Drive がコピーを作る。
        """
        office = {int(t[:2]) for t in du.SITES["office"]["times"]}
        home = {int(t[:2]) for t in du.SITES["home"]["times"]}
        self.assertFalse(office & home)
        # 家は深夜、会社は日中
        self.assertTrue(all(h <= 5 or h >= 22 for h in home), home)
        self.assertTrue(all(6 <= h <= 21 for h in office), office)

    def test_会社だけログオン後を持つ(self):
        """会社PCは消えている時間が長いので、時刻だけだと抜ける日がある。
        家PCは常時ONなので要らない。"""
        self.assertTrue(du.SITES["office"]["logon"])
        self.assertIsNone(du.SITES["home"]["logon"])


class MaskRequired(unittest.TestCase):
    """② マスクできないなら、出力をログに書かない"""

    def _fake(self, out="テスト太郎 の点が入りました", code=0):
        class R:
            returncode = code
            stdout = out
            stderr = ""
        return R()

    def test_マスクが無ければ出力を捨てる(self):
        """🔴 build_master.py の出力には氏名が混ざりうる。

        マスクの仕組みが見つからないときに素通しすると、
        **氏名入りのログがPCに残る**。捨てるほうを選ぶ。
        """
        with mock.patch.object(du.subprocess, "run", return_value=self._fake()):
            code, note = du.run(["dummy"], None)
        self.assertEqual(code, 0)
        self.assertNotIn("テスト太郎", note)
        self.assertIn("ログに残していません", note)

    def test_マスクがあれば通す(self):
        seen = {}

        def fake_mask(t):
            seen["text"] = t
            return ("〈氏名〉 の点が入りました", {})

        with mock.patch.object(du.subprocess, "run", return_value=self._fake()):
            code, note = du.run(["dummy"], fake_mask)
        self.assertIn("テスト太郎", seen["text"])      # マスクには素の文字が渡る
        self.assertNotIn("テスト太郎", note)           # 返るのはマスク後だけ
        self.assertIn("〈氏名〉", note)

    def test_落ちても終了コードを返す(self):
        with mock.patch.object(du.subprocess, "run", return_value=self._fake(code=9)):
            code, _ = du.run(["dummy"], lambda t: (t, {}))
        self.assertEqual(code, 9)

    def test_起動できなくても落ちない(self):
        with mock.patch.object(du.subprocess, "run", side_effect=OSError("no such file")):
            code, note = du.run(["dummy"], lambda t: (t, {}))
        self.assertNotEqual(code, 0)
        self.assertIn("起動できませんでした", note)


class TaskShape(unittest.TestCase):
    """③ タスクの中身"""

    def setUp(self):
        self.xml = du.task_xml("office")

    def test_きあが決めた時刻(self):
        self.assertIn("T09:00:00", self.xml)
        self.assertIn("T16:30:00", self.xml)

    def test_家は深夜だけ(self):
        h = du.task_xml("home")
        self.assertIn("T00:00:00", h)
        self.assertNotIn("T09:00:00", h)
        self.assertNotIn("<LogonTrigger>", h)     # 常時ONなので要らない

    def test_ログオン後にも走る(self):
        """🔴 時刻トリガーだけだと、その時刻に会社PCが起きていない日が丸ごと抜ける。

        ★2026-09-13 実例＝1週間出勤しなかったあいだ、会社PCの自動化3本が
          全部止まっていた（エラーは1件も出なかった）。
        """
        self.assertIn("<LogonTrigger>", self.xml)
        self.assertIn(du.SITES["office"]["logon"], self.xml)

    def test_取りこぼしを取り戻す(self):
        self.assertIn("<StartWhenAvailable>true</StartWhenAvailable>", self.xml)

    def test_二重に走らせない(self):
        self.assertIn("<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>", self.xml)

    def test_本人の権限で走る(self):
        """SYSTEM だとドライブと社内共有がセッションに無く、必ず失敗する（既存3本と同じ作法）。"""
        self.assertIn("<LogonType>InteractiveToken</LogonType>", self.xml)

    def test_電池でも止めない(self):
        self.assertIn("<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>", self.xml)

    def test_XMLとして読める(self):
        import xml.etree.ElementTree as ET
        ET.fromstring(self.xml.split("?>", 1)[1])      # 宣言を外してから解析


class LedgerHome(unittest.TestCase):
    """台帳の場所の決め方"""

    def test_環境変数が最優先(self):
        with mock.patch.dict(os.environ, {du.ENV_LEDGER: r"C:\どこか\台帳"}):
            home, why = du.ledger_home()
        self.assertEqual(home, Path(r"C:\どこか\台帳"))
        self.assertIn(du.ENV_LEDGER, why)

    def test_社用ドライブから組み立てる(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(du.ENV_LEDGER, None)
            with mock.patch.object(du, "company_drive", return_value=Path("X:/マイドライブ")):
                home, why = du.ledger_home()
        self.assertEqual(home, Path("X:/マイドライブ") / du.LEDGER_REL)
        self.assertTrue(why.strip())

    def test_見つからなければNoneと理由(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(du.ENV_LEDGER, None)
            with mock.patch.object(du, "company_drive", return_value=None):
                home, why = du.ledger_home()
        self.assertIsNone(home)
        self.assertTrue(why.strip())

    def test_社用ドライブの見分け方(self):
        """★ドライブ文字は PC ごとに違う（家 I: / 会社 H:）ので決め打ちしない。

        「マイドライブ と 共有ドライブ が両方ある」レターだけを社用とみなす。
        個人アカウントのドライブは共有ドライブを持たない。
        """
        def fake_is_dir(self):
            s = str(self).replace("\\", "/")
            if s.startswith("P:/"):
                return s.endswith("マイドライブ")          # 個人＝共有ドライブが無い
            if s.startswith("Q:/"):
                return True                                # 社用＝両方ある
            return False

        with mock.patch.object(Path, "is_dir", fake_is_dir):
            self.assertEqual(du.company_drive(), Path("Q:/") / "マイドライブ")


class LastSuccess(unittest.TestCase):
    """④ 前回うまくいった日を読む"""

    def _with_log(self, text):
        d = tempfile.mkdtemp()
        p = Path(d) / "kotest_daily.log"
        p.write_text(text, encoding="utf-8")
        return mock.patch.object(du, "log_path", return_value=p)

    def test_ログが無ければ未実施(self):
        with mock.patch.object(du, "log_path", return_value=Path(tempfile.mkdtemp()) / "no.log"):
            last, days = du.last_success()
        self.assertIsNone(last)

    def test_いちばん新しい成功を採る(self):
        y = (dt.datetime.now() - dt.timedelta(days=7))
        t = (dt.datetime.now() - dt.timedelta(days=2))
        with self._with_log(
                f"[{y:%Y-%m-%d %H:%M}] ✅ 終わり（30秒）\n"
                f"[{t:%Y-%m-%d %H:%M}] ✅ 終わり（28秒）\n"):
            last, days = du.last_success()
        self.assertEqual(days, 2)
        self.assertEqual(last.strftime("%Y-%m-%d"), t.strftime("%Y-%m-%d"))

    def test_失敗の行は成功として数えない(self):
        t = (dt.datetime.now() - dt.timedelta(days=5))
        with self._with_log(
                f"[{t:%Y-%m-%d %H:%M}] ✅ 終わり（30秒）\n"
                f"[{dt.datetime.now():%Y-%m-%d %H:%M}] 🔴 台帳を作り直せませんでした\n"):
            last, days = du.last_success()
        self.assertEqual(days, 5)

    def test_1週間あいたら気づける(self):
        """🔴 会社PCが起動しなかった日は走らない＝目印も出ない。

        ★だから「前回から何日あいたか」が唯一の気づき口になる。
        """
        t = (dt.datetime.now() - dt.timedelta(days=7))
        with self._with_log(f"[{t:%Y-%m-%d %H:%M}] ✅ 終わり（30秒）\n"):
            _last, days = du.last_success()
        self.assertGreaterEqual(days, 7)


class Alert(unittest.TestCase):
    """止まったときの目印"""

    def test_出して消せる(self):
        d = Path(tempfile.mkdtemp()) / du.ALERT_NAME
        with mock.patch.object(du, "alert_path", return_value=d):
            du.raise_alert("学生マスタDB.xlsx を開いたままでした")
            self.assertTrue(d.exists())
            body = d.read_text(encoding="utf-8")
            self.assertIn("開いたまま", body)
            self.assertIn("--check", body)      # 直し方が書いてある
            du.clear_alert()
            self.assertFalse(d.exists())

    def test_無くても消せる(self):
        d = Path(tempfile.mkdtemp()) / "ない.txt"
        with mock.patch.object(du, "alert_path", return_value=d):
            du.clear_alert()                    # 例外が出なければよい


class LogTrim(unittest.TestCase):
    def test_古い行から捨てる(self):
        d = Path(tempfile.mkdtemp()) / "a.log"
        with mock.patch.object(du, "log_path", return_value=d):
            du.write_log([f"行{i}" for i in range(du.LOG_KEEP + 50)])
            lines = d.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), du.LOG_KEEP)
        self.assertEqual(lines[-1], f"行{du.LOG_KEEP + 49}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
