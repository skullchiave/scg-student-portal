#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""test_ruby.py — ルビ表示の回帰テスト（2026-09-10）

見ているのは2つ。

  ① `assets/ruby.js` の変換が正しいか（node で実際に動かして確かめる）
  ② ★**画面に素の文字列を innerHTML で入れる書き方が復活していないか**

②が本題。以前、出題画面は textContent で安全だったのに
**結果画面だけ設問文を素のまま innerHTML に入れていた**（`index.html:1499`）。
取り込み時にタグを外していたので実害は無かったが、
**人が設問を書ける画面を作った瞬間に穴になる**状態だった。
ルビを出すには innerHTML が要るので、同時に塞いだ。ここはその見張り。

  py -X utf8 -m unittest discover -s tests -p "test_ruby.py" -v
依存: node（Node.js）。無ければ ① は skip、② だけ走る。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
RUBY_JS = SRC / "assets" / "ruby.js"
INDEX = SRC / "index.html"
NODE = shutil.which("node")


def js(cases: list[str]) -> list[dict]:
    """ruby.js を node で読み込んで、まとめて変換した結果を返す。"""
    script = (
        "const fs=require('fs');\n"
        f"eval(fs.readFileSync({json.dumps(str(RUBY_JS))},'utf8'));\n"
        f"const cs={json.dumps(cases, ensure_ascii=False)};\n"
        "console.log(JSON.stringify(cs.map(c=>({ruby:rubyHtml(c),strip:rubyStrip(c),esc:escHtml(c)}))));"
    )
    p = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    if p.returncode != 0:
        raise AssertionError(f"node が失敗した: {p.stderr[:400]}")
    return json.loads(p.stdout)


@unittest.skipUnless(NODE, "node が無いので skip（②の検査だけ走ります）")
class RubyConvertTest(unittest.TestCase):
    def one(self, s: str) -> dict:
        return js([s])[0]

    # ---- 変換そのもの
    def test_basic(self):
        self.assertEqual(self.one("${昨日}(きのう)")["ruby"],
                         "<ruby>昨日<rt>きのう</rt></ruby>")

    def test_two_in_one_sentence(self):
        r = self.one("${昨日}(きのう)、まちで${会}(あ)った")["ruby"]
        self.assertEqual(r, "<ruby>昨日<rt>きのう</rt></ruby>、まちで<ruby>会<rt>あ</rt></ruby>った")

    def test_real_data_shape(self):
        """実データそのままの形（ポイント＆プラクティス N3語彙）。"""
        s = "${昨日}(きのう)、（ ）${高校}(こうこう)のときの${友達}(ともだち)と${町}(まち)で${会}(あ)った。"
        r = self.one(s)["ruby"]
        self.assertEqual(r.count("<ruby>"), 5)
        self.assertNotIn("${", r)          # ★記号が画面に残らないこと
        self.assertIn("（ ）", r)          # 空欄の括弧は消えない

    def test_no_ruby_is_untouched(self):
        self.assertEqual(self.one("ふつうの もんだい")["ruby"], "ふつうの もんだい")

    def test_newline_survives(self):
        """問題文1と2は改行でつないである。.prompt の white-space:pre-line が効く。"""
        self.assertEqual(self.one("いちぎょうめ\nにぎょうめ")["ruby"], "いちぎょうめ\nにぎょうめ")

    # ---- ★安全のほう（ここが本命）
    def test_script_tag_does_not_survive(self):
        r = self.one("<script>alert(1)</script>")["ruby"]
        self.assertNotIn("<script", r)
        self.assertIn("&lt;script&gt;", r)

    def test_tag_before_ruby_is_escaped_but_ruby_still_works(self):
        """★エスケープが先・ルビ変換が後、という順番の証明。"""
        r = self.one("<b>${昨日}(きのう)")["ruby"]
        self.assertEqual(r, "&lt;b&gt;<ruby>昨日<rt>きのう</rt></ruby>")

    def test_tag_inside_ruby_is_escaped(self):
        r = self.one("${<b>}(x)")["ruby"]
        self.assertEqual(r, "<ruby>&lt;b&gt;<rt>x</rt></ruby>")

    def test_ampersand(self):
        self.assertEqual(self.one("A&B")["ruby"], "A&amp;B")

    def test_quotes(self):
        r = self.one("\"'")["ruby"]
        self.assertEqual(r, "&quot;&#39;")

    def test_null_and_empty(self):
        out = js(["", None])
        self.assertEqual(out[0]["ruby"], "")
        self.assertEqual(out[1]["ruby"], "")

    # ---- 消すほう（将来「ルビを消す」切り替えを付けるときの土台）
    def test_strip(self):
        self.assertEqual(self.one("${昨日}(きのう)、まちで${会}(あ)った")["strip"], "昨日、まちで会った")

    def test_strip_keeps_plain_text(self):
        self.assertEqual(self.one("ふつうの もんだい")["strip"], "ふつうの もんだい")


class NoRawInnerHtmlTest(unittest.TestCase):
    """★設問文・選択肢・正解を innerHTML に入れるなら、必ず rubyHtml / setRuby を通すこと。
    素のまま入れる書き方が復活したら、ここで落ちる。"""

    WATCH = ("q.prompt", "correctTxt", "c.label", "it.prompt")

    def test_no_raw_value_in_innerhtml(self):
        src = INDEX.read_text(encoding="utf-8")
        bad = []
        for m in re.finditer(r"\.innerHTML\s*=(.+?);", src, re.S):
            body = m.group(1)
            for name in self.WATCH:
                if re.search(r"(?<![\w.])" + re.escape(name), body) \
                        and f"rubyHtml({name}" not in body:
                    line = src[:m.start()].count("\n") + 1
                    bad.append(f"{line}行目: {name} が rubyHtml を通らずに innerHTML へ入っている")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_ruby_js_is_loaded_before_use(self):
        src = INDEX.read_text(encoding="utf-8")
        self.assertIn('<script src="assets/ruby.js"></script>', src)
        # 使う側（本文のスクリプト）より前に読まれていること
        self.assertLess(src.index('assets/ruby.js'), src.index("rubyHtml("))

    def test_prompt_uses_ruby(self):
        """出題画面の設問文がルビを通っていること（textContent に戻っていないか）。"""
        src = INDEX.read_text(encoding="utf-8")
        self.assertRegex(src, r'\$\("qprompt"\)\.innerHTML\s*=.*rubyHtml\(q\.prompt\)')

    def test_choice_uses_ruby(self):
        src = INDEX.read_text(encoding="utf-8")
        self.assertIn("setRuby(s,", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
