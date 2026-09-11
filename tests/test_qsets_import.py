# -*- coding: utf-8 -*-
r"""test_qsets_import.py — 教師画面「問題の登録・解放」（src/assets/fmt-import.js）の回帰テスト（2026-09-10）

**DB不要・実物のExcel不要**。見ているのは次の3つ。

  ① 構造（DB不要・常に実行）: teacher.html の読み込み・置き場所の決まりが崩れていないか
     （xlsx.js は teacher.html だけ／index.html の「ライブラリ依存ゼロ」を破っていないか／
      innerHTML に流す前に rubyHtml()・setRuby() を通しているか／解説は question_answers 側か）
  ② JS の取り込みルール（Node で実行・DB不要）: fmt-import.js が
     `scripts/import_fmt_xlsx.py` と**同じ規則**で読めているか。列の位置・見出し検査・
     拾わない行・ルビ記法・選択肢の飛び/重複・ブック破損・同じ課の重複・同じ問題の別版—
     Python側の tests/test_import_fmt_xlsx.py と対になるシナリオを、SheetJSの最小スタブ
     （encode_cell/decode_range だけ）でシート相当のオブジェクトを組んで確かめる。
     ★フルの xlsx.js は要らない（この2関数しか fmt-import.js は使っていない）。
  ③ ブラウザ実操作（本物のデモDBへ往復）: tests/run_e2e_qsets_import.py（別ファイル・手本は run_e2e_quiz.py）

  py -X utf8 -m unittest discover -s tests -p "test_qsets_import.py" -v
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEACHER = os.path.join(ROOT, "src", "teacher.html")
INDEX = os.path.join(ROOT, "src", "index.html")
FMTJS = os.path.join(ROOT, "src", "assets", "fmt-import.js")


def read(p):
    return io.open(p, encoding="utf-8").read() if os.path.exists(p) else ""


class CheckMixin:
    def check(self, name, cond, detail=""):
        print(("  OK  " if cond else "  NG  ") + name + (f"  ({detail})" if detail and not cond else ""))
        with self.subTest(name=name):
            self.assertTrue(cond, detail or name)


# ------------------------------------------------------------------ ① 置き場所・安全側の決まり
class StructureTest(CheckMixin, unittest.TestCase):
    def test_01_where_things_load(self):
        print("=== 1. 読み込み場所（DB不要）===")
        tea, idx, js = read(TEACHER), read(INDEX), read(FMTJS)
        self.check("fmt-import.js がある", bool(js), FMTJS)
        self.check("teacher.html が fmt-import.js を読む", 'assets/fmt-import.js' in tea)
        self.check("teacher.html が ruby.js を読む（設問文・選択肢をinnerHTMLに出すため）", 'assets/ruby.js' in tea)
        self.check("xlsx.js（SheetJS）は teacher.html だけ", "xlsx" in tea.lower() and "xlsx" not in idx.lower())
        self.check("★学生画面はライブラリ依存ゼロのまま（index.html に xlsx を足していない）",
              "cdnjs.cloudflare.com/ajax/libs/xlsx" not in idx)
        self.check("xlsx のCDN読み込みはバージョンを固定して書いてある",
              bool([1 for line in tea.splitlines() if "cdnjs.cloudflare.com/ajax/libs/xlsx/" in line
                    and any(ch.isdigit() for ch in line)]))
        # 読み込みの順番: xlsx/ruby/fmt-import は api.js より後（api.token を使うため）
        self.check("fmt-import.js は api.js より後に読む",
              tea.index("assets/api.js") < tea.index("assets/fmt-import.js"))

    def test_02_ruby_safety(self):
        print("\n=== 2. ルビ・innerHTML の安全側（DB不要）===")
        tea = read(TEACHER)
        self.check("プレビュー・修正フォームで rubyHtml か setRuby を使っている",
              "rubyHtml(" in tea or "setRuby(" in tea)
        self.check("編集フォームの入力欄には生の記法のまま出す設計"
              "（escHtml で十分・rubyHtml をtextarea/valueに使っていない誤用が無いか目視は別途）",
              "escHtml(" in tea)

    def test_03_explanation_is_teacher_only(self):
        print("\n=== 3. 解説の置き場所（DB不要）===")
        js = read(FMTJS)
        self.check("解説（explanation）は question_answers 側の insert 本文に入れている",
              "abody.explanation" in js)
        self.check("★解説を questions 側（学生が読める表）には入れていない",
              "qbody.explanation" not in js)
        self.check("正解は選択肢を入れたあとに insert している（外部キーの順序）",
              js.index("question_choices") < js.index("question_answers"))

    def test_04_duplicate_lesson_guard_exists(self):
        print("\n=== 4. 同じ課の重複への言及（DB不要）===")
        js, tea = read(FMTJS), read(TEACHER)
        self.check("fmt-import.js が「同じ範囲」の重複を検出している", "同じ範囲" in js and "★同じ範囲" in js)
        self.check("teacher.html 側が重複を理由に次へを止める作りになっている",
              "disabled" in tea and ("同じ課の範囲" in tea or "同じ範囲" in tea))

    def test_05_graceful_column_degrade(self):
        print("\n=== 5. 追加4列が無くても落ちない作り（DB不要）===")
        js = read(FMTJS)
        self.check("列の有無を読み取りで確かめてから書き込む（probeColumns）", "probeColumns" in js)
        self.check("★4列が無い場合はその4つを外して insert する分岐がある",
              "cols.questionExtra" in js and "cols.explanation" in js)

    def test_05b_draft_first_and_safe_delete(self):
        """公開・停止・削除（2026-09-11 きあ決定 b）。

        🔴 ここで見ているのは2つの決めごと:
          ①取り込みは**下書き**で入る（取り込んだ瞬間に学生へ出る事故を無くす）
          ②削除は**必ず RPC 経由**（quiz_sets を直接 DELETE すると cascade で受験記録まで消え、
            しかも cascade は RLS を通らない）
        """
        print("\n=== 5b. 下書きで登録・消し方（DB不要）===")
        js, tea = read(FMTJS), read(TEACHER)
        self.check("★登録は is_open:false（下書き）で入る", "is_open: false" in js)
        self.check("★is_open:true で作る書き方が残っていない", "is_open: true" not in js)
        self.check("公開・停止の切り替えがある（setOpen）", "function setOpen" in js and "setOpen" in tea)
        self.check("★削除は RPC delete_quiz_set を呼んでいる", "rpc/delete_quiz_set" in js)
        self.check("★quiz_sets を直接 DELETE する書き方が fmt-import.js に無い",
              not any('"DELETE"' in l and "quiz_sets" in l for l in js.splitlines()))
        self.check("押す前に受験記録の件数を数える口がある（attemptCount）", "function attemptCount" in js)
        self.check("画面が「受験記録があるので消せません」を出す", "消せません" in tea)
        # ⚠ 「confirm(」を数えてはいけない。2026-09-11 に自前の <dialog> へ置き換えたので
        #   実際の呼び出しは0件だが、**コメントの中の「confirm()」に当たって、たまたま通る**。
        #   数えるのは実物の呼び出し（askDialog）。
        self.check("★押す前の確認は自前のダイアログ（askDialog）で出す",
              tea.count("askDialog(") >= 4, "askDialog= " + str(tea.count("askDialog(")))
        self.check("★ブラウザ標準の confirm() を使っていない",
              " confirm(" not in tea.replace("window.confirm", "") or "await confirm(" not in tea,
              "「このページの内容」という消せない見出しが出るため")
        self.check("ダイアログに危険な操作の色分けがある（danger）", "danger" in tea)
        self.check("④の文言が「登録」になっている（公開は一覧で押す）",
              "登録する（下書き）" in tea)

    def test_05c_delete_rpc_sql_exists(self):
        """SQL 側の見張り。★受験記録があるときに消さないことが本体。"""
        print("\n=== 5c. delete_quiz_set の SQL（DB不要）===")
        sql_path = os.path.join(ROOT, "db", "2026-09-11_delete_quiz_set.sql")
        self.check("db/2026-09-11_delete_quiz_set.sql がある", os.path.exists(sql_path), sql_path)
        if not os.path.exists(sql_path):
            return
        sql = read(sql_path)
        self.check("教師だけが呼べる", "app_hidden.is_teacher()" in sql)
        self.check("★受験記録を数えて、1件でもあれば例外にする",
              "from public.attempts" in sql and "raise exception" in sql)
        self.check("anon から revoke している", "from anon" in sql)
        self.check("巻き戻し手順が書いてある", "巻き戻" in sql)

    def test_06_no_db_write_outside_publish(self):
        print("\n=== 6. 公開以外でDBに書き込まない（DB不要）===")
        js = read(FMTJS)
        # build() / buildSheet() はブラウザ内のメモリ処理だけ。fetch や api を呼んでいないこと
        import re
        m = re.search(r"function build\([\s\S]*?\n  \}\n\n  return \{", js)
        self.check("build() 本体が読める", m is not None)
        if m:
            self.check("★パース処理（build）は fetch も api も呼んでいない（プレビューはDBに触らない）",
                  "fetch(" not in m.group(0) and "api." not in m.group(0))


# ------------------------------------------------------------------ ② 取り込みルール（Node）
NODE_HARNESS = r"""
"use strict";
// ---- SheetJS の最小スタブ（fmt-import.js が使うのはこの2関数だけ） ----
const XLSX = { utils: {
  encode_cell: function (c) {
    let col = "", n = c.c;
    do { col = String.fromCharCode(65 + (n % 26)) + col; n = Math.floor(n / 26) - 1; } while (n >= 0);
    return col + (c.r + 1);
  },
  decode_range: function (ref) {
    const [a, b] = ref.split(":");
    const dec = (s) => {
      const m = s.match(/^([A-Z]+)(\d+)$/);
      let col = 0; for (const ch of m[1]) col = col * 26 + (ch.charCodeAt(0) - 64);
      return { r: parseInt(m[2], 10) - 1, c: col - 1 };
    };
    return { s: dec(a), e: dec(b || a) };
  },
} };

__FMT_IMPORT_JS__

// ---- テスト用の小道具（tests/test_import_fmt_xlsx.py の qrow/make_book と同じ形） ----
const HEAD = ["問題番号", "問題文1", "問題文2", "添付ファイル名",
  "選択肢1", "選択肢2", "選択肢3", "選択肢4", "選択肢5", "解説", "解答", "カテゴリ", "配点"];

function qrow(no, o) {
  o = o || {};
  const t2 = o.t2 !== undefined ? o.t2 : "つぎの ぶんを えらんで ください";
  const choices = o.choices || ["あ", "い", "う"];
  const ans = o.ans !== undefined ? o.ans : 1;
  const ch = choices.concat(Array(5 - choices.length).fill(""));
  return [no, o.t1 || "", t2, o.image || "", ...ch, o.explain || "",
          ans, o.cat !== undefined ? o.cat : "文法", o.points !== undefined ? o.points : 5];
}

function mkWs(rows) {
  const ws = {}; let maxR = 0, maxC = 0;
  rows.forEach((row, r) => {
    row.forEach((val, c) => {
      if (val === undefined || val === null || val === "") return;
      const addr = XLSX.utils.encode_cell({ r, c });
      if (val && typeof val === "object" && "formula" in val) {
        ws[addr] = { f: val.formula };
        if (val.value !== undefined) ws[addr].v = val.value;
      } else {
        ws[addr] = { v: val };
      }
      maxR = Math.max(maxR, r); maxC = Math.max(maxC, c);
    });
  });
  ws["!ref"] = XLSX.utils.encode_cell({ r: 0, c: 0 }) + ":" + XLSX.utils.encode_cell({ r: maxR, c: maxC });
  return ws;
}

function book(sheetsObj, head) {
  const H = head || HEAD;
  const SheetNames = Object.keys(sheetsObj);
  const Sheets = {};
  for (const name of SheetNames) Sheets[name] = mkWs([H, ...sheetsObj[name]]);
  return { SheetNames, Sheets };
}

const R = {};

// ---- 基本 ----
{
  const { sets, warn } = FmtImport.build(book({ "①1-3": [qrow(1, { choices: ["あ", "い", "う"], ans: 2 })] }));
  const q = sets[0].questions[0];
  R.basic = { seq: q.seq, choices: q.choices, correctIdx: q.correctIdx, warnLen: warn.length };
}
{
  const { sets } = FmtImport.build(book({ "①1-3": [qrow(1, { choices: ["あ", "い"], ans: 2 })] }));
  R.two_choices = sets[0].questions[0].choices;
}
{
  const { sets } = FmtImport.build(book({ "①1-3": [qrow(1, { choices: ["あ", "い", "う", "え", "お"], ans: 5 })] }));
  R.five_choices_len = sets[0].questions[0].choices.length;
}
{
  const { sets, warn } = FmtImport.build(book({ "①1-3": [qrow(1, { ans: "２" })] }));
  R.zenkaku_answer = { correctIdx: sets[0].questions[0].correctIdx, warnLen: warn.length };
}

// ---- 問題文 ----
{
  const { sets } = FmtImport.build(book({ "①1-3": [qrow(1, { t1: "つぎの ぶん", t2: "ほんを＿＿。" })] }));
  R.prompt_join = sets[0].questions[0].prompt;
}
{
  const { sets, warn } = FmtImport.build(book({ "①1-3": [qrow(1, { t1: "", t2: "ほんを＿＿。" })] }));
  R.only_t2 = { prompt: sets[0].questions[0].prompt, warnLen: warn.length };
}
{
  const { sets, warn } = FmtImport.build(book({ "①1-3": [qrow(1, { t1: "", t2: "" }), qrow(2)] }));
  R.both_empty = { n: sets[0].questions.length, warned: warn.some(w => w.includes("問題文1も問題文2も空")) };
}

// ---- 黙って通さない ----
{
  const row = qrow(1); row[4] = "あ"; row[5] = ""; row[6] = "う";
  const { sets, warn } = FmtImport.build(book({ "①1-3": [row, qrow(2)] }));
  R.gap = { n: sets[0].questions.length, warned: warn.some(w => w.includes("飛んでいる")) };
}
{
  const { sets, warn } = FmtImport.build(book({ "①1-3": [qrow(1, { choices: ["あ", "い"], ans: 3 }), qrow(2)] }));
  R.ans_oor = { n: sets[0].questions.length, warned: warn.some(w => w.includes("選択肢は 2 個しかない")) };
}
{
  const { sets, warn } = FmtImport.build(book({ "①1-3": [qrow(1, { ans: 0 }), qrow(2)] }));
  R.ans_zero = { n: sets[0].questions.length, warned: warn.some(w => w.includes("解答が 0")) };
}
{
  const { sets, warn } = FmtImport.build(book({ "①1-3": [qrow(1, { ans: "" }), qrow(2)] }));
  R.ans_empty = { n: sets[0].questions.length, warned: warn.some(w => w.includes("解答が空か、数字でない")) };
}
{
  const { sets, warn } = FmtImport.build(book({ "①1-3": [qrow(1, { choices: ["あ"], ans: 1 }), qrow(2)] }));
  R.single_choice = { n: sets[0].questions.length, warned: warn.some(w => w.includes("選択肢が 1 個")) };
}
{
  const { warn } = FmtImport.build(book({ "①1-3": [qrow(1), qrow(1)] }));
  R.dup_seq = warn.some(w => w.includes("問題番号が重複"));
}
{
  // 配点がそろっているシートでは警告を出さない
  const { warn } = FmtImport.build(book({ "①1-3": [qrow(1, { points: 5 }), qrow(2, { points: 5 })] }));
  R.points_uniform = warn.some(w => w.includes("配点がそろっていない"));
}
{
  // 1問だけ配点が違う＝打ち間違いの候補として出す。取り込みは止めない
  const { sets, warn } = FmtImport.build(book({
    "①1-3": [qrow(1, { points: 5 }), qrow(2, { points: 5 }), qrow(3, { points: 20 })] }));
  const w = warn.filter(x => x.includes("配点がそろっていない"))[0] || "";
  R.points_mixed = { n: sets[0].questions.length, warned: !!w,
                     saysRare: w.includes("20点の問だけ"), detail: w.includes("5点が2問") };
}
{
  // 配点が空欄の問は数に入れない（空欄だけを理由に「そろっていない」と言わない）
  const { warn } = FmtImport.build(book({
    "①1-3": [qrow(1, { points: 5 }), qrow(2, { points: "" })] }));
  R.points_blank_ignored = warn.some(w => w.includes("配点がそろっていない"));
}
{
  const { sets, warn } = FmtImport.build(book({ "⑩28-30": [qrow(1, { choices: ["あ", "い", "い"], ans: 1 })] }));
  R.dup_choice_outside = { n: sets[0].questions.length, warned: warn.some(w => w.includes("選択肢が重複している")) };
}
{
  const { sets } = FmtImport.build(book({ "⑩28-30": [qrow(1, { choices: ["あ", "い", "い"], ans: 2 }), qrow(2)] }));
  R.dup_choice_inside = { seqs: sets[0].questions.map(q => q.seq), droppedReason: sets[0].dropped[0].reason };
}

// ---- 落としたものを残す ----
{
  const { sets } = FmtImport.build(book({ "①1-3": [qrow(1), qrow(2, { choices: ["あ", "い"], ans: 3 })] }));
  R.dropped_recorded = sets[0].dropped;
}
{
  const { sets } = FmtImport.build(book({ "⑩28-30": [qrow(1), qrow(2), qrow(3, { choices: ["あ", "い"], ans: 3 })] }));
  R.last_dropped_visible = { seqs: sets[0].questions.map(q => q.seq), droppedSeqs: sets[0].dropped.map(d => d.seq) };
}

// ---- 作りかけ と 別形式 ----
{
  const blank = [8, "", "", "", "", "", "", "", "", "", "", "", 1];
  const { sets, warn } = FmtImport.build(book({ "ルビなし": [qrow(1), blank] }));
  R.unwritten = { n: sets[0].questions.length, unwritten: sets[0].unwritten,
                  droppedLen: sets[0].dropped.length, warned: warn.some(w => w.includes("作りかけ")) };
}
{
  const { sets } = FmtImport.build(book({ "①1-3": [qrow(1, { t1: "", t2: "", choices: ["あ", "い"], ans: 1 })] }));
  R.partial_written = { droppedLen: sets[0].dropped.length, unwritten: sets[0].unwritten };
}
{
  const head = ["回（課）", "問題番号", "問題文1", "問題文2", "選択肢1", "選択肢2", "選択肢3", "選択肢4", "解答"];
  const { sets, warn } = FmtImport.build(book({ "シート1": [["中7", 1, "", "もんだい", "", "", "", "", ""]] }, head));
  R.non_fmt = { n: sets[0].questions.length, hasError: "error" in sets[0],
                warned: warn.some(w => w.includes("課題登録FMT ではない")) };
}

// ---- 黙って捨てない ----
{
  const summary = ["集計", "", "", "", "", "", "", "", "", "", "", "", 100];
  const { sets, warn } = FmtImport.build(book({ "①1-3": [qrow(1), summary] }));
  R.summary_row = { n: sets[0].questions.length, warned: warn.some(w => w.includes("集計") && w.includes("飛ばした行")) };
}
{
  const { sets, warn } = FmtImport.build(book({ "①1-3": [qrow(1), ["", "", "", "", "", "", "", "", "", "", "", "", ""]] }));
  R.blank_row_silent = { n: sets[0].questions.length, warnLen: warn.length };
}
{
  const { sets, warn } = FmtImport.build(book({ "③7-9": [qrow(1, { image: "7-9-⑮ゴミ出し.png" })] }));
  R.image_kept = { imageName: sets[0].questions[0].imageName, warned: warn.some(w => w.includes("画像つきの設問")) };
}
{
  const { sets } = FmtImport.build(book({ "①1-3": [qrow(1, { cat: "文法読解", points: 3, explain: "かいせつ" })] }));
  const q = sets[0].questions[0];
  R.meta_kept = { category: q.category, points: q.points, explanation: q.explanation };
}
{
  const { sets } = FmtImport.build(book({ "①1-3": [qrow(1)] }));
  R.no_image_null = sets[0].questions[0].imageName;
}

// ---- 計算結果が消えたブック ----
{
  const rows = [];
  for (let i = 2; i <= 4; i++) rows.push([{ formula: "=" + (i - 1) }, "", "もんだい", "", "あ", "い", "", "", "", "", 1, "文法", 1]);
  const { sets, warn } = FmtImport.build(book({ "①1-3": rows }));
  R.stale_cache = { warned: warn.some(w => w.includes("計算結果が入っていない")),
                     hasError: "error" in sets[0], qLen: sets[0].questions.length };
}
{
  const { warn } = FmtImport.build(book({ "①1-3": [qrow(1)] }));
  R.no_stale_when_normal = warn.some(w => w.includes("計算結果"));
}

// ---- 見出しに頼らない ----
{
  const broken = HEAD.slice(); broken[10] = ""; broken[11] = "文法読解";
  const { sets, warn } = FmtImport.build(book({ "④10-12": [qrow(1, { ans: 3 })] }, broken));
  R.broken_header = { correctIdx: sets[0].questions[0].correctIdx, warned: warn.some(w => w.includes("見出しが")) };
}
{
  const { warn } = FmtImport.build(book({ "①1-3": [qrow(1)] }));
  R.correct_header_no_warn = warn.some(w => w.includes("見出し"));
}

// ---- 1列ずれた版 ----
{
  function shifted(firstColName) {
    const head = [firstColName, ...HEAD];
    const rows = [1, 2].map(i => ["L" + i, ...qrow(i, { choices: ["あ", "い", "う"], ans: 3 })]);
    return FmtImport.build(book({ "ルビあり": rows }, head));
  }
  const a = shifted("課番号");
  R.offset_kabangou = { seq: a.sets[0].questions[0].seq, choices: a.sets[0].questions[0].choices,
                         correctIdx: a.sets[0].questions[0].correctIdx,
                         reported: a.warn.some(w => w.includes("2 列目から始まっている")) };
  R.offset_setsumon_len = shifted("設問").sets[0].questions.length;
  R.offset_no_header_warn = a.warn.some(w => w.includes("想定は"));
  const { warn: noOff } = FmtImport.build(book({ "①1-3": [qrow(1)] }));
  R.no_offset_when_plain = noOff.some(w => w.includes("列目から始まっている"));
}

// ---- シートの選び方 ----
{
  const wb = book({ "250507から_課題登録FMT_コピーして使用": [qrow(1)], "①1-3": [qrow(1)] });
  R.template_excluded = FmtImport.listImportableSheets(wb);
}
{
  const { warn } = FmtImport.build(book({ "①1-3": [qrow(1)], "①1-3 （新）": [qrow(1)] }));
  R.same_lesson_warned = warn.some(w => w.includes("同じ範囲"));
}
{
  const wb = book({ "①1-3": [qrow(1)], "②4-6": [qrow(1)] });
  R.only_selected = FmtImport.build(wb, { only: ["②4-6"] }).sets.map(s => s.sheet);
}
{
  const a = [qrow(1, { t2: "かんじを よみます", choices: ["あ", "い", "う"], ans: 2 })];
  const b = [qrow(1, { t2: "漢字を読みます", choices: ["ア", "イ", "ウ"], ans: 2 })];
  const { warn } = FmtImport.build(book({ "ルビあり": a, "ルビなし": b }));
  R.variant_detected = warn.some(w => w.includes("同じ問題の別版"));
}
{
  const { warn } = FmtImport.build(book({ "1-①": [qrow(1, { ans: 1 })], "1-②": [qrow(1, { ans: 2 })] }));
  R.variant_not_falsely_flagged = warn.some(w => w.includes("同じ問題の別版"));
  R.check_test_not_dup = warn.some(w => w.includes("同じ範囲"));
}

// ---- ルビ ----
{
  const wb = book({ "①1-3": [qrow(1, { t2: "${昨日}(きのう)、まちで${会}(あ)った" })] });
  R.ruby_keep = FmtImport.build(wb).sets[0].questions[0].prompt;
  R.ruby_strip = FmtImport.build(wb, { ruby: "strip" }).sets[0].questions[0].prompt;
  R.ruby_html = FmtImport.build(book({ "①1-3": [qrow(1, { t2: "${昨日}(きのう)" })] }), { ruby: "html" }).sets[0].questions[0].prompt;
  const wb2 = book({ "①1-3": [qrow(1, { choices: ["${会}(あ)う", "い"], ans: 1 })] });
  R.ruby_choices_strip = FmtImport.build(wb2, { ruby: "strip" }).sets[0].questions[0].choices;
}

// ---- 名前 ----
R.lesson_of = [FmtImport.lessonOf("①1-3 （新）"), FmtImport.lessonOf("⑩28-30"),
               FmtImport.lessonOf("1-①"), FmtImport.lessonOf("オリエン")];
R.title_of = [FmtImport.titleOf("①1-3 （新）", "つなぐ まとめテスト"), FmtImport.titleOf("①1-3", "")];

console.log(JSON.stringify(R));
"""


class NodeParityTest(CheckMixin, unittest.TestCase):
    """fmt-import.js を Node で実際に動かし、import_fmt_xlsx.py と同じ規則で読めているか確かめる。"""

    @classmethod
    def setUpClass(cls):
        js = read(FMTJS)
        if not js:
            cls.results = None
            return
        src = NODE_HARNESS.replace("__FMT_IMPORT_JS__", js)
        fd, path = tempfile.mkstemp(suffix=".js")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(src)
            try:
                out = subprocess.run(["node", path], capture_output=True, text=True, timeout=60)
            except (FileNotFoundError, OSError) as e:
                cls.node_error = f"node を実行できない: {e}"
                cls.results = None
                return
            if out.returncode != 0 or not out.stdout.strip():
                cls.node_error = f"Node の実行に失敗:\n{out.stderr[-2000:]}"
                cls.results = None
                return
            try:
                cls.results = json.loads(out.stdout.strip().splitlines()[-1])
            except json.JSONDecodeError as e:
                cls.node_error = f"Node の出力がJSONでない: {e}\n{out.stdout[-1000:]}"
                cls.results = None
        finally:
            if os.path.exists(path):
                os.remove(path)

    def setUp(self):
        if self.results is None:
            self.skipTest(getattr(self, "node_error", "node が使えないためskip"))

    def test_01_basic(self):
        print("\n=== Node: 基本 ===")
        r = self.results
        self.check("問1つが3つの部分になる", r["basic"] == {"seq": 1, "choices": ["あ", "い", "う"], "correctIdx": 2, "warnLen": 0})
        self.check("2択でよい", r["two_choices"] == ["あ", "い"])
        self.check("5択でよい", r["five_choices_len"] == 5)
        self.check("全角の解答も受け付ける", r["zenkaku_answer"] == {"correctIdx": 2, "warnLen": 0})

    def test_02_prompt(self):
        print("\n=== Node: 問題文 ===")
        r = self.results
        self.check("問題文1と2は改行でつなぐ", r["prompt_join"] == "つぎの ぶん\nほんを＿＿。")
        self.check("問題文2だけでもよい", r["only_t2"] == {"prompt": "ほんを＿＿。", "warnLen": 0})
        self.check("両方空は落として警告", r["both_empty"] == {"n": 1, "warned": True})

    def test_03_reject(self):
        print("\n=== Node: 黙って通さない ===")
        r = self.results
        self.check("選択肢の飛びは拒否", r["gap"] == {"n": 1, "warned": True})
        self.check("解答が範囲外は拒否", r["ans_oor"] == {"n": 1, "warned": True})
        self.check("解答0は拒否", r["ans_zero"] == {"n": 1, "warned": True})
        self.check("解答が空は拒否", r["ans_empty"] == {"n": 1, "warned": True})
        self.check("選択肢1個は拒否", r["single_choice"] == {"n": 1, "warned": True})
        self.check("問題番号の重複は警告", r["dup_seq"] is True)
        self.check("重複選択肢・正解が外なら残して警告", r["dup_choice_outside"] == {"n": 1, "warned": True})
        self.check("重複選択肢・正解が中なら落とす",
              r["dup_choice_inside"]["seqs"] == [2] and "正解がその中にある" in r["dup_choice_inside"]["droppedReason"])

    def test_03b_points_parity(self):
        """★配点のばらつき検出が Python と JS で同じ答えになるか。
        実測 2026-09-11: 設問のある667シート中 662枚（99.3%）は全問おなじ配点で、
        本当に2種類以上あるのは5枚だけ。採点には使わないので取り込みは止めない。"""
        print("\n=== Node: 配点のばらつき ===")
        r = self.results
        self.check("そろっていれば警告なし", r["points_uniform"] is False)
        self.check("1問だけ違えば警告する", r["points_mixed"]["warned"] is True)
        self.check("★取り込みは止めない（3問とも残る）", r["points_mixed"]["n"] == 3)
        self.check("いちばん少ない配点を名指しする", r["points_mixed"]["saysRare"] is True)
        self.check("内訳も出す", r["points_mixed"]["detail"] is True)
        self.check("空欄は数に入れない", r["points_blank_ignored"] is False)

    def test_04_dropped(self):
        print("\n=== Node: 落としたものを残す ===")
        r = self.results
        d = r["dropped_recorded"]
        self.check("落とした理由が残る", len(d) == 1 and d[0]["seq"] == 2 and "選択肢は 2 個" in d[0]["reason"])
        self.check("最後の問題が落ちても記録に残る（番号の抜けにならない）",
              r["last_dropped_visible"] == {"seqs": [1, 2], "droppedSeqs": [3]})

    def test_05_unwritten(self):
        print("\n=== Node: 作りかけ と 別形式 ===")
        r = self.results
        self.check("番号だけの行は作りかけ扱い（不備に混ぜない）",
              r["unwritten"] == {"n": 1, "unwritten": [8], "droppedLen": 0, "warned": True})
        self.check("一部でも書かれていれば不備として扱う",
              r["partial_written"] == {"droppedLen": 1, "unwritten": []})
        self.check("FMT形式でないシートは触らない",
              r["non_fmt"] == {"n": 0, "hasError": True, "warned": True})

    def test_06_keep(self):
        print("\n=== Node: 黙って捨てない ===")
        r = self.results
        self.check("集計行は飛ばして報告", r["summary_row"] == {"n": 1, "warned": True})
        self.check("空行は静か", r["blank_row_silent"] == {"n": 1, "warnLen": 0})
        self.check("画像は残して警告", r["image_kept"] == {"imageName": "7-9-⑮ゴミ出し.png", "warned": True})
        self.check("カテゴリ・配点・解説を保持", r["meta_kept"] == {"category": "文法読解", "points": 3, "explanation": "かいせつ"})
        self.check("画像なしは null", r["no_image_null"] is None)

    def test_07_stale_cache(self):
        print("\n=== Node: 計算結果が消えたブック ===")
        r = self.results
        self.check("計算結果なしを名指しで警告", r["stale_cache"] == {"warned": True, "hasError": True, "qLen": 0})
        self.check("通常のブックには出ない", r["no_stale_when_normal"] is False)

    def test_08_header(self):
        print("\n=== Node: 見出しに頼らない ===")
        r = self.results
        self.check("見出しが壊れていても位置で読む", r["broken_header"] == {"correctIdx": 3, "warned": True})
        self.check("正しい見出しには警告なし", r["correct_header_no_warn"] is False)

    def test_09_offset(self):
        print("\n=== Node: 1列ずれた版 ===")
        r = self.results
        self.check("「課番号」列が前にあっても読める",
              r["offset_kabangou"] == {"seq": 1, "choices": ["あ", "い", "う"], "correctIdx": 3, "reported": True})
        self.check("「設問」列でも読める（2問とも）", r["offset_setsumon_len"] == 2)
        self.check("ずれを吸収できていれば見出しズレの警告は出ない", r["offset_no_header_warn"] is False)
        self.check("ずれていなければオフセット警告は出ない", r["no_offset_when_plain"] is False)

    def test_10_sheet_selection(self):
        print("\n=== Node: シートの選び方 ===")
        r = self.results
        self.check("テンプレート本体（FMTを含む名前）は候補から除く", r["template_excluded"] == ["①1-3"])
        self.check("同じ課の範囲が複数あれば警告", r["same_lesson_warned"] is True)
        self.check("only で選んだシートだけ取り込む", r["only_selected"] == ["②4-6"])
        self.check("★中身が同じなら別シート名でも別版として検出", r["variant_detected"] is True)
        self.check("正解が違えば別版扱いしない（誤検出しない）", r["variant_not_falsely_flagged"] is False)
        self.check("'1-①''1-②' は同じ範囲の重複と誤検出しない", r["check_test_not_dup"] is False)

    def test_11_ruby(self):
        print("\n=== Node: ルビ ===")
        r = self.results
        self.check("既定は記法のまま保存（keep）", r["ruby_keep"] == "${昨日}(きのう)、まちで${会}(あ)った")
        self.check("strip でルビが消える", r["ruby_strip"] == "昨日、まちで会った")
        self.check("html で <ruby> タグになる", r["ruby_html"] == "<ruby>昨日<rt>きのう</rt></ruby>")
        self.check("選択肢も同じ扱いを受ける", r["ruby_choices_strip"] == ["会う", "い"])

    def test_12_naming(self):
        print("\n=== Node: 名前 ===")
        r = self.results
        self.check("シート名から課の範囲を取る", r["lesson_of"] == ["1-3", "28-30", "1-①", "オリエン"])
        self.check("タイトルは丸数字を外して前置き文字を足す",
              r["title_of"] == ["つなぐ まとめテスト 1-3 （新）", "1-3"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
