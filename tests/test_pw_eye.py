#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""test_pw_eye.py — パスワードの「目」の検査（2026-09-12 きあ依頼）

きあ「パスワードなんだけど。目のマークを押したら、入力してるパスが見えるようにしてください」

■ なぜ共通部品にしたか
  ログイン欄は3画面（学生・先生・マスター）にある。画面ごとに書くと、
  **どれか1つだけ直し忘れて動きが食い違う**。assets/pw-eye.js を読み込むだけで
  その画面の input[type=password] 全部に付く形にしてある。
  ★この検査の主題は「**3画面とも同じように付いていること**」。

■ DB不要・ブラウザ不要（node があれば JS の中身も見る）
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
SCREENS = ("index.html", "teacher.html", "master.html")
EYE = os.path.join(SRC, "assets", "pw-eye.js")
CSS = os.path.join(SRC, "assets", "app.css")
I18N = os.path.join(SRC, "assets", "i18n.js")
NODE = shutil.which("node")


def read(p):
    return io.open(p, encoding="utf-8").read() if os.path.exists(p) else ""


class CheckMixin:
    def check(self, name, cond, detail=""):
        print(("  OK  " if cond else "  NG  ") + name + (f"  ({detail})" if detail and not cond else ""))
        with self.subTest(name=name):
            self.assertTrue(cond, detail or name)


class SharedPartTest(CheckMixin, unittest.TestCase):
    def test_01_file_exists(self):
        print("\n=== 共通部品 ===")
        self.check("assets/pw-eye.js がある", os.path.exists(EYE))

    def test_02_all_three_screens_load_it(self):
        """🔴 ここが本題。1画面でも抜けたら、そこだけ目が出ない。"""
        for f in SCREENS:
            with self.subTest(screen=f):
                self.check(f"{f} が pw-eye.js を読み込む",
                           "assets/pw-eye.js" in read(os.path.join(SRC, f)))

    def test_03_no_per_screen_copy(self):
        """画面ごとに同じ処理を書き写していないこと（書き写すと片方だけ腐る）。"""
        for f in SCREENS:
            with self.subTest(screen=f):
                s = read(os.path.join(SRC, f))
                self.check(f"{f} に目の処理を書き写していない", 'class="pwbtn"' not in s)

    def test_04_attaches_to_every_password_field(self):
        js = read(EYE)
        self.check("input[type=password] を全部拾う", 'input[type="password"]' in js)
        self.check("二度付けを防いでいる", "pwEye" in js)
        self.check("type を password ⇄ text で切り替える",
                   '"text"' in js and '"password"' in js)

    def test_05_button_does_not_submit(self):
        """🔴 form の中なので type=button にしないと、押した瞬間にログインが走る。"""
        js = read(EYE)
        self.check("ボタンは type=button", 'btn.type = "button"' in js)


class LayoutTest(CheckMixin, unittest.TestCase):
    """入力欄の中に重ねる。横に並べると欄が縮んで崩れる。"""

    def test_01_css_exists(self):
        print("\n=== 見た目（崩さない） ===")
        css = read(CSS)
        self.check(".pwwrap がある", ".pwwrap{" in css)
        self.check(".pwbtn がある", ".pwbtn{" in css)

    def test_02_overlays_instead_of_sitting_beside(self):
        """🔴 .field input{width:100%} が効いているので、重ねないと欄が痩せる
        （2026-09-11 にチェックボックスで同じ崩れ方を踏んでいる）。"""
        css = read(CSS)
        m = re.search(r"\.pwbtn\{[^}]*\}", css)
        self.check(".pwbtn の指定が読める", m is not None)
        if m:
            self.check("入力欄に重ねている（position:absolute）", "position:absolute" in m.group(0))
        self.check("文字がボタンの下に潜らないよう右に余白がある",
                   "padding-right" in (re.search(r"\.pwwrap input\{[^}]*\}", css) or
                                       re.match("", "")).group(0) if re.search(r"\.pwwrap input\{[^}]*\}", css) else False)


class WordsTest(CheckMixin, unittest.TestCase):
    """文言。学生画面は日本語/English を切り替えるので、両方に要る。"""

    def test_01_both_languages(self):
        print("\n=== 文言 ===")
        s = read(I18N)
        for key in ("pw.show", "pw.hide"):
            with self.subTest(key=key):
                self.check(f"{key} が2か所（ja と en）にある", s.count(f'"{key}"') == 2,
                           f"{s.count(chr(34) + key + chr(34))} 個")

    def test_02_follows_language_switch(self):
        js = read(EYE)
        self.check("言語を切り替えたら文言も追従する", "sp:lang" in js)

    def test_03_works_without_i18n(self):
        """i18n が無い画面でも落ちないこと（t() を使う前に有無を見る）。"""
        js = read(EYE)
        self.check("t() があるか確かめてから使う", 'typeof t === "function"' in js)
        self.check("無いときの日本語の控えがある", "パスワードを見る" in js)


@unittest.skipUnless(NODE, "node が無いので JS の構文検査は skip")
class SyntaxTest(CheckMixin, unittest.TestCase):
    def test_01_parses(self):
        print("\n=== JS の構文 ===")
        r = subprocess.run([NODE, "--check", EYE], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        self.check("pw-eye.js が node で構文検査を通る", r.returncode == 0, r.stderr[:200])


if __name__ == "__main__":
    unittest.main(verbosity=2)
