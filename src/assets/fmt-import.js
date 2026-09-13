/* scg-student-portal 教師画面 — 課題登録FMT Excel の取り込み（2026-09-10）
 *
 * master.html の「問題の登録・解放」から使う。ライブラリは xlsx.js（SheetJS・CDN）のみ、
 * これは master.html だけで読み込む（学生画面 index.html の「ライブラリ依存ゼロ」は守る）。
 *
 * 🔴 ★ここが肝: 取り込みの規則は scripts/import_fmt_xlsx.py と**意図して同じにそろえてある**。
 *   列の位置・見出しの検査・拾わない行・ルビ記法・選択肢の飛び/重複・同じ課の重複・ブック破損の
 *   検出は、どれもあちらと同じロジックの JS 移植。ロジックを変えるときは**両方**直すこと。
 *   （定数やルールを1か所にまとめる案＝JSONで共有する等はリードへの報告に書いた。今回は間に合わせ）
 *
 * DB へは quiz_sets → questions → question_choices → question_answers の順で書く（公開時のみ）。
 * 解説（explanation）は questions ではなく question_answers に入れる
 * （公開中の回の解説を受験前に読めてしまうのを防ぐため。db/2026-09-10_question_columns.sql 参照）。
 */
const FmtImport = (() => {
  "use strict";

  // ---- 列の位置（0始まり。import_fmt_xlsx.py は1始まりなので、そこから1引いた値） -------
  const COL_NO = 0, COL_T1 = 1, COL_T2 = 2, COL_IMG = 3;
  const COL_CH = 4, N_CH = 5;                 // 選択肢1〜5 → 4,5,6,7,8
  const COL_EXPL = 9, COL_ANS = 10, COL_CAT = 11, COL_PTS = 12;

  const EXPECTED = {
    0: "問題番号", 1: "問題文1", 2: "問題文2", 3: "添付ファイル名",
    4: "選択肢1", 5: "選択肢2", 6: "選択肢3", 7: "選択肢4", 8: "選択肢5",
    9: "解説", 10: "解答", 11: "カテゴリ", 12: "配点",
  };
  const N_EXPECTED = Object.keys(EXPECTED).length;

  const MAX_CHOICES = 12;
  // テンプレート本体らしいシート名の目印。★これは**手がかり**であって、判定そのものではない
  const TEMPLATE_MARK = "FMT";
  const TEMPLATE_MARK2 = "コピーして";    // 「…_コピーして使用」「作問シート（コピーして使う）」

  /* 🔴 テンプレートかどうかは **中身** で決める（2026-09-13）。
     それまでは「シート名に FMT が入っていたら取り込まない」だった。ところが実データでは、
     作問した人が **新しいシートにコピーせず、テンプレートのシートに直接書いて** いた。
       ・009.文型チェックシート 12枚 120問 が、名前のせいで黙って捨てられていた
         （この教材は取り込めていたのが50問。つまり大半が落ちていた）
     逆に判定を「コピー」という語に広げると、今度は
       ・008.JapanGo_スピードマスター 13枚 199問（本物）を新しく捨てることになった
     ＝**名前では決まらない。**
     🔴 指紋は FNV-1a 32bit で本文には戻せない（このリポは public）。
        scripts/import_fmt_xlsx.py の TEMPLATE_SAMPLE_KEYS と **同じ値・同じ計算**にすること。 */
  const TEMPLATE_SAMPLE_KEYS = new Set([
    "05f66d46", "166e479a", "20e458bd", "2e430831", "2f77e1a1", "36205745",
    "38fc6776", "420e2a0f", "513be979", "7f55aabb", "a67e5013", "aaa0d3ca",
    "b492fcfe", "c0315902", "ca0a73d7", "ddc14b7c", "ea10d188", "f9ce8ff7",
    "fd5f3472", "ff00d85c",
    // 【作問シート】テンプレート（2026-09-13）の見本3行。scripts/make_sakumon_template.py が作る。
    // ★見本の行を書き換えたら --keys で出し直して、ここと import_fmt_xlsx.py の両方に貼ること。
    "d295f90a", "7ebfad72", "19258114",
  ]);

  function fnv1a(text) {
    const bytes = new TextEncoder().encode(text);
    let h = 0x811c9dc5;
    for (let i = 0; i < bytes.length; i++) {
      h ^= bytes[i];
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h.toString(16).padStart(8, "0");
  }

  /* 設問の指紋。★ルビ記法は外してから作る（ルビあり版／なし版で同じ指紋になるように）。 */
  function questionKey(prompt, choices) {
    const strip = t => String(t || "").replace(RUBY_G, "$1");
    return fnv1a(strip(prompt) + "\u0001" + (choices || []).map(strip).join("\u0001"));
  }

  function looksLikeTemplate(sheetName) {
    return sheetName.indexOf(TEMPLATE_MARK) !== -1 || sheetName.indexOf(TEMPLATE_MARK2) !== -1;
  }

  /* 設問のうち見本と同じものの割合（0〜1）。設問が無ければ 1（＝白紙とみなす）。 */
  function sampleShare(items) {
    if (!items || !items.length) return 1;
    let hit = 0;
    items.forEach(q => { if (TEMPLATE_SAMPLE_KEYS.has(questionKey(q.prompt, q.choices))) hit++; });
    return hit / items.length;
  }
  const CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳";
  const RUBY = /\$\{([^}]*)\}\(([^)]*)\)/g;
  /* ★指紋を作るときのルビ外し用。RUBY をそのまま使い回すと lastIndex が残って
     2回目以降の replace が食い違う（/g 付きの正規表現を共有したときの定番の罠）。 */
  const RUBY_G = /\$\{([^}]*)\}\(([^)]*)\)/g;

  // ---------------------------------------------------------------- 小道具
  function zenkakuToHan(s) {
    return s.replace(/[０-９]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0));
  }

  function asInt(v) {
    if (v === null || v === undefined || v === "") return null;
    if (typeof v === "boolean") return null;
    if (typeof v === "number") return Number.isInteger(v) ? v : null;
    const s = zenkakuToHan(String(v).trim());
    return /^\d+$/.test(s) ? parseInt(s, 10) : null;
  }

  function cellAt(ws, r, c) {
    return ws[XLSX.utils.encode_cell({ r, c })];
  }

  function cellText(ws, r, c) {
    const cell = cellAt(ws, r, c);
    if (!cell || cell.v === undefined || cell.v === null) return "";
    return String(cell.v).trim();
  }

  function lastRow(ws) {
    const range = XLSX.utils.decode_range(ws["!ref"] || "A1:A1");
    return range.e.r;    // 0始まり。ヘッダー行=0なので、データ行は 1..lastRow
  }

  function lessonOf(sheetName) {
    // ①1-3 （新） → '1-3'。範囲が取れない形（'1-①' 'オリエン'）はシート名そのまま
    const m = sheetName.match(/(\d+)\s*[-‐−–~〜]\s*(\d+)/);
    if (m) return `${parseInt(m[1], 10)}-${parseInt(m[2], 10)}`;
    return sheetName.trim();
  }

  function titleOf(sheetName, prefix) {
    let body = sheetName;
    while (body.length && CIRCLED.indexOf(body[0]) !== -1) body = body.slice(1);
    body = body.trim();
    return prefix ? `${prefix} ${body}`.trim() : (body || sheetName);
  }

  function applyRuby(s, mode) {
    if (!s || mode === "keep") return s;
    if (mode === "strip") return s.replace(RUBY, "$1");
    if (mode === "html") return s.replace(RUBY, "<ruby>$1<rt>$2</rt></ruby>");
    throw new Error("bad ruby mode: " + mode);
  }

  // ---------------------------------------------------------------- どの列から始まるか
  function anchorOffset(ws) {
    for (let c = 0; c < 5; c++) {
      if (cellText(ws, 0, c) === "問題番号") return c;
    }
    return 0;
  }

  // ---------------------------------------------------------------- 計算結果が入っているか
  function staleCache(ws, sheetName, off) {
    let nFormula = 0, nMissing = 0;
    const last = lastRow(ws);
    for (let r = 1; r <= last; r++) {
      const cell = cellAt(ws, r, COL_NO + off);
      if (cell && typeof cell.f === "string") {
        nFormula++;
        if (cell.v === undefined || cell.v === null || cell.v === "") nMissing++;
      }
    }
    if (nFormula && nMissing === nFormula) {
      return `🔴 [${sheetName}] 問題番号が数式（${nFormula}行）なのに、計算結果が入っていない` +
        "＝このままでは1問も取り込めない。Excel で開いて保存し直してからやり直すこと" +
        "（保存し直したブックをもう一度選び直してください）";
    }
    return null;
  }

  // ---------------------------------------------------------------- 変換（1シート）
  function buildSheet(ws, sheetName, prefix, ruby) {
    ruby = ruby || "keep";
    const warn = [];
    const tag = `[${sheetName}]`;
    const off = anchorOffset(ws);
    if (off) {
      warn.push(`${tag} FMT が ${off + 1} 列目から始まっている（1列目は「${cellText(ws, 0, 0)}」）＝その分ずらして読む`);
    }

    let hit = 0;
    for (const colStr of Object.keys(EXPECTED)) {
      const col = Number(colStr);
      const want = EXPECTED[col];
      const got = cellText(ws, 0, col + off);
      if (got === want) hit++;
      else warn.push(`${tag} ${col + off + 1}列目の見出しが「${got || "(空)"}」＝想定は「${want}」` +
        "（位置で読むので取り込みは続けるが、列がずれていないか目で確かめること）");
    }
    if (hit < 9) {
      return {
        sheet: sheetName, title: titleOf(sheetName, prefix), lesson: lessonOf(sheetName),
        questions: [], dropped: [], unwritten: [],
        error: `課題登録FMT ではない（見出しの一致 ${hit}/${N_EXPECTED}）`,
        warn: [`${tag} 課題登録FMT ではないので触らない（見出しの一致 ${hit}/${N_EXPECTED}）`],
      };
    }

    const items = [], dropped = [], skippedRows = [], unwritten = [];
    const last = lastRow(ws);
    for (let r = 1; r <= last; r++) {
      const rawCell = cellAt(ws, r, COL_NO + off);
      const rawNo = rawCell ? rawCell.v : undefined;
      if (rawNo === undefined || rawNo === null || String(rawNo).trim() === "") continue;   // 空行は静かに飛ばす
      const seq = asInt(rawNo);
      if (seq === null) {
        skippedRows.push(`${r + 1}行目「${String(rawNo).trim().slice(0, 20)}」`);
        continue;
      }

      const otherCols = [COL_T1, COL_T2, COL_IMG, COL_EXPL, COL_ANS, COL_CAT];
      const hasOther = otherCols.some(c => cellText(ws, r, c + off)) ||
        Array.from({ length: N_CH }, (_, k) => cellText(ws, r, COL_CH + off + k)).some(Boolean);
      if (!hasOther) { unwritten.push(seq); continue; }     // 問題番号だけの行＝作りかけ

      const t1 = applyRuby(cellText(ws, r, COL_T1 + off), ruby);
      const t2 = applyRuby(cellText(ws, r, COL_T2 + off), ruby);
      const prompt = [t1, t2].filter(Boolean).join("\n");
      const image = cellText(ws, r, COL_IMG + off);
      const explain = cellText(ws, r, COL_EXPL + off);
      const category = cellText(ws, r, COL_CAT + off);
      const ptsCell = cellAt(ws, r, COL_PTS + off);
      const points = asInt(ptsCell ? ptsCell.v : undefined);

      const raw = Array.from({ length: N_CH }, (_, k) => applyRuby(cellText(ws, r, COL_CH + off + k), ruby));
      const labels = raw.filter(Boolean);
      let firstBlank = raw.findIndex(s => !s);
      if (firstBlank === -1) firstBlank = N_CH;
      const gap = raw.slice(firstBlank + 1).some(Boolean);

      const drop = (reason) => { warn.push(`${tag} 問${seq}: ${reason}`); dropped.push({ seq, row: r + 1, reason }); };

      if (gap) { drop(`選択肢が飛んでいる（${JSON.stringify(raw.map(Boolean))}）＝正解の番号とずれる恐れがある`); continue; }
      if (!prompt) { drop("問題文1も問題文2も空"); continue; }
      if (labels.length < 2) { drop(`選択肢が ${labels.length} 個（2個以上ないと出題できない）`); continue; }
      if (labels.length > MAX_CHOICES) { drop(`選択肢が ${labels.length} 個（上限 ${MAX_CHOICES} 個）`); continue; }

      const ansCell = cellAt(ws, r, COL_ANS + off);
      const ans = asInt(ansCell ? ansCell.v : undefined);
      if (ans === null) { drop("解答が空か、数字でない"); continue; }
      if (!(ans >= 1 && ans <= labels.length)) { drop(`解答が ${ans} だが選択肢は ${labels.length} 個しかない`); continue; }

      const counts = {};
      labels.forEach(l => { counts[l] = (counts[l] || 0) + 1; });
      const dups = Object.keys(counts).filter(l => counts[l] > 1).sort();
      if (dups.length) {
        if (dups.indexOf(labels[ans - 1]) !== -1) {
          drop(`選択肢が重複していて、しかも正解がその中にある（${JSON.stringify(dups)}）`);
          continue;
        }
        warn.push(`${tag} 問${seq}: 選択肢が重複している（${JSON.stringify(dups)}）＝問題として成立していない。作問側に直してもらうこと`);
      }
      if (image) {
        warn.push(`${tag} 問${seq}: 画像つきの設問（${image}）＝いまの画面は画像を出さない。文字だけで意味が通るか確認すること`);
      }

      items.push({
        seq, prompt, choices: labels, correctIdx: ans,
        imageName: image || null, category: category || null, points,
        explanation: explain || null,
      });
    }

    if (skippedRows.length) {
      warn.push(`${tag} 問題番号が数字でないので飛ばした行: ${skippedRows.join("、")}（「集計」なら想定どおり）`);
    }
    if (unwritten.length) {
      warn.push(`${tag} まだ書かれていない問題が ${unwritten.length} 問（問${unwritten[0]}〜${unwritten[unwritten.length - 1]}）` +
        "＝問題番号の枠だけがある状態。作問の不備ではなく、作りかけ");
    }

    const seqCounts = {};
    items.forEach(i => { seqCounts[i.seq] = (seqCounts[i.seq] || 0) + 1; });
    const dupSeq = Object.keys(seqCounts).filter(s => seqCounts[s] > 1).map(Number).sort((a, b) => a - b);
    if (dupSeq.length) warn.push(`${tag} 問題番号が重複: ${JSON.stringify(dupSeq)}`);

    // ★同じテストの中で配点がそろっていない（2026-09-11 追加）
    //   🔴 import_fmt_xlsx.py の同じ検査と対になっている。片方だけ直さないこと。
    //   実測（2026-09-11）: 設問のある667シートのうち 662枚（99.3%）は全問おなじ配点で、
    //   本当に2種類以上あるのは5枚だけ。★空欄は数に入れない（入れると18枚に増えて5枚が埋もれる）。
    //   採点には使っていないので取り込みは止めない。作問側に見てもらうために出すだけ。
    const ptsList = items.map(i => i.points).filter(v => v !== null && v !== undefined);
    const ptsCount = {};
    ptsList.forEach(v => { ptsCount[v] = (ptsCount[v] || 0) + 1; });
    const ptsKeys = Object.keys(ptsCount).map(Number).sort((a, b) => a - b);
    if (ptsKeys.length > 1) {
      // いちばん少ない配点＝打ち間違いの候補（同数なら小さいほう。Python 側と同じ選び方）
      let rare = ptsKeys[0];
      ptsKeys.forEach(v => { if (ptsCount[v] < ptsCount[rare]) rare = v; });
      const detail = ptsKeys.map(v => `${v}点が${ptsCount[v]}問`).join("、");
      warn.push(`${tag} 同じテストの中で配点がそろっていない（${detail}）` +
                `＝${rare}点の問だけ違います。打ち間違いでなければそのままで構いません`);
    }

    return {
      sheet: sheetName, title: titleOf(sheetName, prefix), lesson: lessonOf(sheetName),
      questions: items, dropped, unwritten, warn,
    };
  }

  // ---------------------------------------------------------------- 変換（ブック全体）
  /* ───────── 配る「作問シート」のテンプレートの中身（2026-09-13 きあ指摘）─────────
     ★きあ：「場所が散らばると混乱するから。テンプレを管理者画面からダウンロードできるようにすればよくない？」
       それまではドライブのフォルダに置いていたが、**手順書と置き場が別だと片方だけ古くなる**。
     🔴 見本の3行は scripts/make_sakumon_template.py の SAMPLES と **1文字も違えてはいけない。**
        違うと指紋が変わり、見本が **本物の問題として取り込まれる**。
        tests/test_qsets_import.py が「1セルも違わない」「見本として登録ずみ」を毎回見ている。 */
  const TEMPLATE_SHEET_NAME = "作問シート（コピーして使う）";
  const TEMPLATE_HEADERS = ["問題番号", "問題文1", "問題文2", "添付ファイル名",
    "選択肢1", "選択肢2", "選択肢3", "選択肢4", "選択肢5", "解説", "解答", "カテゴリ", "配点"];
  const TEMPLATE_ROWS = [
    [1, "これは 見本です。この行を 消してから、問題を 書いてください。", "", "",
      "はい", "いいえ", "", "", "", "", 1, "文法", 1],
    [2, "つぎの ぶんの （  ）に 入る ことばは どれですか。",
      "わたしは まいにち コーヒー（  ）のみます。", "",
      "を", "が", "に", "で", "", "", 1, "文法", 1],
    [3, "${昨日}(きのう)、なにを たべましたか。", "", "",
      "たべました", "たべます", "", "", "",
      "「きのう」は すぎた ことなので、「〜ました」を つかいます。", 1, "文法", 1],
  ];

  /* ───────── 受験結果をまとめて書き出す（2026-09-13 きあ依頼）─────────
   *
   * ★きあ：「一括で落とせないと、今みたいにクラス毎に20個…みたいになって大変」
   *   それまでの書き出しは **1テスト × クラス** が単位だった。87回あれば87個になる。
   *   ここは **テストをまたいで1ファイル** にするための、表を組み立てるところ。
   *
   * 🔴 ここは**純粋な組み立てだけ**（通信もDOMも触らない）。
   *    そうしておくと、Node の検査から「どんな表ができるか」を直接確かめられる。
   *
   * ■ 2つの形を出す（混ぜない。ヨリソルの失敗6番目「同じ表に混ぜない」と同じ考え方）
   *   一覧 wideRows … 1行＝1学生。テストが横に並ぶ。**台帳に貼る用**
   *   明細 longRows … 1行＝1受験。**数え直す用**
   */
  const RESULT_EMPTY = "";      // 受けていないセル。★0 と区別する（0点と未受験は違う）

  function fmtWhen(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    const z = n => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + z(d.getMonth() + 1) + "-" + z(d.getDate()) +
           " " + z(d.getHours()) + ":" + z(d.getMinutes());
  }

  /* 一覧（1行＝1学生・テストが横に並ぶ）。
     students: [{student_no, name, class_name}]（並び順のまま出す）
     sets:     [{id, title}]（並び順のまま列になる）
     byPair:   { "<student_no>\u0001<set_id>": {score, total} } */
  function wideRows(students, sets, byPair) {
    const head = ["学籍番号", "氏名", "クラス"]
      .concat(sets.map(s => s.title))
      .concat(["受けた数", "合計点", "合計満点"]);
    const rows = [head];
    students.forEach(st => {
      let n = 0, sum = 0, full = 0;
      const cells = sets.map(s => {
        const a = byPair[st.student_no + "\u0001" + s.id];
        if (!a) return RESULT_EMPTY;
        n++; sum += Number(a.score) || 0; full += Number(a.total) || 0;
        return a.score;
      });
      rows.push([st.student_no, st.name, st.class_name].concat(cells).concat([n, sum, full]));
    });
    return rows;
  }

  /* 明細（1行＝1受験）。attempts は新しい順でも古い順でも、渡された順に出す。 */
  function longRows(attempts) {
    const rows = [["学籍番号", "氏名", "クラス", "教科書", "テスト名", "課",
                   "点数", "満点", "提出日時", "所要(秒)"]];
    attempts.forEach(a => {
      rows.push([a.student_no, a.name, a.class_name, a.book, a.title, a.lesson,
                 a.score, a.total, fmtWhen(a.at),
                 a.duration_ms == null ? "" : Math.round(a.duration_ms / 1000)]);
    });
    return rows;
  }

  /* 取り込み候補のシート。★白紙のテンプレートだけ出さない。
     名前がテンプレートっぽくても、**中身が見本と違えば出す**（書き込まれているため）。 */
  function listImportableSheets(workbook) {
    return workbook.SheetNames.filter(n => {
      if (!looksLikeTemplate(n)) return true;
      try {
        const s = buildSheet(workbook.Sheets[n], n, "", "keep");
        if (s.error) return false;
        return sampleShare(s.questions) < 1;
      } catch (e) { return false; }       // 読めないテンプレは出さない（取り込みようがない）
    });
  }

  function build(workbook, opts) {
    opts = opts || {};
    const only = opts.only || null;             // 取り込むシート名の配列（省略時はテンプレート以外全部）
    const prefix = opts.prefix || "";
    const ruby = opts.ruby || "keep";

    const names = listImportableSheets(workbook);
    const chosen = only ? names.filter(n => only.indexOf(n) !== -1) : names;
    const sets = [], warn = [];

    for (const name of chosen) {
      const ws = workbook.Sheets[name];
      const off = anchorOffset(ws);
      const stale = staleCache(ws, name, off);
      if (stale) {
        warn.push(stale);
        sets.push({
          sheet: name, title: titleOf(name, prefix), lesson: lessonOf(name),
          questions: [], dropped: [], unwritten: [], error: "計算結果が入っていない",
        });
        continue;
      }
      const s = buildSheet(ws, name, prefix, ruby);
      /* ★テンプレートの名前なのに中身が見本と違う＝書き込まれている。
         listImportableSheets が候補に残しているので取り込むが、**黙って入れない**。
         （2026-09-13。名前で捨てていたせいで、文型チェックシートの120問が落ちていた） */
      if (looksLikeTemplate(name) && s.questions.length) {
        const sh = sampleShare(s.questions);
        if (sh < 1) {
          warn.push("[" + name + "] ★テンプレートの名前のシートに問題が書かれています（" +
            s.questions.length + "問中 見本と同じなのは" + Math.round(sh * s.questions.length) +
            "問）＝取り込みます。見本が混ざっていないか、プレビューで確かめてください");
        }
      }
      warn.push(...(s.warn || []));
      delete s.warn;
      if (!s.questions.length) warn.push(`[${name}] 取り込めた設問が 0 件`);
      sets.push(s);
    }

    // ★同じ課の範囲を指すシートが2枚あると二重登録になる
    const byLesson = {};
    for (const s of sets) {
      if (s.lesson) (byLesson[s.lesson] = byLesson[s.lesson] || []).push(s.sheet);
    }
    for (const lesson of Object.keys(byLesson)) {
      const sheets = byLesson[lesson];
      if (sheets.length > 1) {
        warn.push(`★同じ範囲「${lesson}課」のシートが ${sheets.length} 枚ある: ${JSON.stringify(sheets)}` +
          "＝そのまま流すと二重に登録される。どちらを使うか選ぶこと");
      }
    }

    // ★同じ問題の別版（中身の署名で判定。ルビあり／なし等）
    const sig = {};
    for (const s of sets) {
      if (s.questions.length) {
        const key = s.questions.map(q => `${q.seq}:${q.correctIdx}:${q.choices.length}`).join("|");
        (sig[key] = sig[key] || []).push(s.sheet);
      }
    }
    for (const sheets of Object.values(sig)) {
      if (sheets.length > 1) {
        warn.push(`★同じ問題の別版とみられるシートが ${sheets.length} 枚: ${JSON.stringify(sheets)}` +
          "（問題数・正解の並び・選択肢の数がすべて同じ）＝両方入れると二重になる。どちらを使うか決めること");
      }
    }

    return { sets, warn };
  }

  return {
    // 定数（テストや呼び出し側から参照する）
    COL_NO, COL_T1, COL_T2, COL_IMG, COL_CH, N_CH, COL_EXPL, COL_ANS, COL_CAT, COL_PTS,
    EXPECTED, MAX_CHOICES, TEMPLATE_MARK,
    // 関数
    asInt, lessonOf, titleOf, applyRuby, anchorOffset, staleCache, buildSheet, build, listImportableSheets,
    // ★テンプレ判定（2026-09-13）。Python 側と値が一致することを検査で見ている
    fnv1a, questionKey, looksLikeTemplate, sampleShare, TEMPLATE_SAMPLE_KEYS,
    // 配るテンプレートの中身（JS と Python で同じであることを検査で見ている）
    TEMPLATE_SHEET_NAME, TEMPLATE_HEADERS, TEMPLATE_ROWS,
    // 結果のまとめ書き出し（表の組み立てだけ。通信もDOMも触らない＝検査から直接確かめられる）
    wideRows, longRows, fmtWhen, RESULT_EMPTY,
  };
})();

/* ---------------------------------------------------------------- DB への書き込み（公開時のみ）
 * master.html だけで使う。api.js の api オブジェクト（ログイン・自動再送つきfetch）をそのまま使う。
 * api.js は「既存・変更が要るならリードへ」のファイルなので、ここでは変更せず
 * api._authed()（再送・トークン失効の自動リフレッシュつき）をそのまま呼ぶだけにしてある。
 */
FmtImport.db = (() => {
  "use strict";
  let colsProbed = null;

  async function authedGet(path) {
    const res = await api._authed(path);
    if (!res.ok) throw new Error("読み込みに失敗しました（" + res.status + "）");
    return res.json();
  }

  async function authedWrite(method, path, body) {
    const opts = { method, headers: { "Prefer": "return=representation" } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await api._authed(path, opts);
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      throw new Error((b && (b.message || b.hint)) || ("失敗しました（" + res.status + "）"));
    }
    const text = await res.text();
    return text ? JSON.parse(text) : null;
  }

  /* questions.image_name/category/points と question_answers.explanation は
     db/2026-09-10_question_columns.sql が本番DBに流れるまで存在しない。
     ★無ければ落ちずに、その4つを insert から外して警告に留める（きあのOK待ちの間の橋渡し）。
     判定は軽い読み取りだけ（1行 select）＝書き込みを試して失敗を拾うより安全。
     quiz_sets.source_book/source_file/source_sheet も同じ考え方で足す（2026-09-11・一覧の絞り込み用）。 */
  async function probeColumns() {
    if (colsProbed) return colsProbed;
    const probe = async (table, cols) => {
      try { await authedGet(`/rest/v1/${table}?select=${cols}&limit=1`); return true; }
      catch (e) { return false; }
    };
    colsProbed = {
      questionExtra: await probe("questions", "image_name,category,points"),
      explanation: await probe("question_answers", "explanation"),
      quizSetsSource: await probe("quiz_sets", "source_book,source_file,source_sheet"),
      // 教科書の順で並べるための値（2026-09-12）。無い環境では従来どおり新しい順に倒す
      quizSetsSort: await probe("quiz_sets", "sort_key"),
    };
    return colsProbed;
  }

  function resetProbeCache() { colsProbed = null; }   // テスト・やり直し用

  /* quiz_sets に source_book 等があるか（一覧・「はじめる」の絞り込みUIを出す・出さないの分岐に使う）。
     ★列が無い環境でも呼び出し側が落ちないよう、真偽値だけを返す薄いラッパー。 */
  async function probeQuizSetsSource() {
    const cols = await probeColumns();
    return cols.quizSetsSource;
  }

  /* 教材（source_book）の一覧。fetchClassNames()（master.html）と同じ考え方＝
     固定リストを持たず、実在の値から毎回引く。
     ⚠ 列が無い環境で呼ぶと PostgREST が 400 を返す。呼ぶ側は probeQuizSetsSource() で確かめてから呼ぶこと。 */
  async function listSourceBooks() {
    const rows = await authedGet("/rest/v1/quiz_sets?select=source_book&source_book=not.is.null");
    return [...new Set(rows.map(r => r.source_book).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ja"));
  }

  /* 教材（source_book）ごとの「回の数」と「設問の数」（2026-09-13 きあ指摘）。
   *
   * ★なぜ要るか: 控えの単位が「表示中の50件」になっていた。
   *   50件は **「もっと見る」を押す前の1ページ分** でしかなく、
   *   きあの言うとおり「何の50件？」になる。控えの単位は **教科書（教材）** が正しい。
   *   同じ数字を、一覧の教材プルダウンにも出す（選ぶ前に全何件か分かるように）。
   *
   * 🔴 quiz_sets → questions は経路が2つあるので外部キーを名指しする（素の questions(count) は 300）。
   */
  async function listBooksWithCounts() {
    const rows = await authedGet(
      "/rest/v1/quiz_sets?select=source_book,questions!questions_quiz_set_id_fkey(count)&limit=2000");
    const by = {};
    rows.forEach(r => {
      const k = r.source_book || "";                       // 空＝教材が入っていない回
      const n = (Array.isArray(r.questions) && r.questions[0] &&
                 typeof r.questions[0].count === "number") ? r.questions[0].count : 0;
      if (!by[k]) by[k] = { book: k, sets: 0, questions: 0 };
      by[k].sets++; by[k].questions += n;
    });
    // 教材名の順。★「教材なし」は最後に置く（ふだん使わないものを先頭に出さない）
    return Object.values(by).sort((a, b) =>
      (a.book || "\uffff\uffff").localeCompare(b.book || "\uffff\uffff", "ja"));
  }

  /* ある教材の回を **全部** 返す（一覧の50件ではなく）。
     ★book が空文字のときは「教材が入っていない回」＝ source_book is null を引く
       （eq. では null を拾えない）。 */
  async function listSetsOfBook(book) {
    const q = book ? "source_book=eq." + encodeURIComponent(book) : "source_book=is.null";
    return await authedGet("/rest/v1/quiz_sets?select=id,title&" + q +
                           "&order=sort_key.asc.nullsfirst,created_at.desc&limit=2000");
  }

  /* 一覧（showQsList）と「はじめる」画面（quiz-pick）が共通で使う絞り込み検索（2026-09-11）。
     🔴 **PostgREST 側で絞る。**クライアントで全部取ってから絞る書き方をこのリポに増やさない
     （99回→437回になると全件取得そのものが遅くなる・無駄なため）。
     🔴 件数は Prefer: count=exact と Content-Range ヘッダから取る。
        api.get() は res.json() しか返さない（ヘッダを読めない）ので、ここだけ api._authed を直に呼ぶ。
     戻り値: { rows, total }。total は数えられなかったときだけ null（0件と混同しないため）。 */
  async function searchQuizSets(select, opts) {
    opts = opts || {};
    // 🔴 sort_key が無い環境で order に書くと PostgREST が 400 を返す。必ず確かめてから使う
    //    （source_book 等と同じ考え方。列が無い相手でも落ちない、が守るところ）
    if (!opts.order) {
      const cols = await probeColumns();
      opts = Object.assign({}, opts,
        { order: cols.quizSetsSort ? "sort_key.asc.nullsfirst,created_at.desc"
                                   : "created_at.desc" });
    }
    const params = [
      "select=" + select,
      /* ★既定は「教科書の順」（2026-09-12 きあ指示・上の probe で決めている）。
         毎日のチェックテストとまとめテストを、課の進む順に1本に並べる:
           1-① 1-② 1-③ 2-① … 3-③ まとめ1-3 4-① …
         sort_key がそのための値（'01-1' / '03-9' のように0詰め）。
         🔴 sort_key を持たない回（取り込んだばかり・手で作った・検査用）は **nullsfirst で先頭**。
            最後に送ったら、取り込んだ直後の回が87件の向こうに隠れて
            「取り込んだのに何も起きていない」ように見えた（2026-09-12 に踏んだ）。
            null どうしは従来どおり新しい順。
         ⚠ lesson（"1-①"）で並べると 1,10,11,12,2,3… と文字の順になる。
            **表示用の文字で並べないこと。** */
      "order=" + opts.order,
      "limit=" + (opts.limit || 50),
      "offset=" + (opts.offset || 0),
    ];
    if (opts.book) params.push("source_book=eq." + encodeURIComponent(opts.book));
    // ★日本語が入るので必ず encodeURIComponent を通す（教師の入力をそのままURLへ差し込まない）
    if (opts.q) params.push("title=ilike.*" + encodeURIComponent(opts.q) + "*");
    const res = await api._authed("/rest/v1/quiz_sets?" + params.join("&"), {
      headers: { "Prefer": "count=exact" },
    });
    if (!res.ok) throw new Error("読み込みに失敗しました（" + res.status + "）");
    const rows = await res.json();
    const cr = res.headers.get("content-range");   // 例 "0-49/162"。数えられないと "0-49/*"
    const m = cr && cr.match(/\/(\d+)$/);
    return { rows, total: m ? Number(m[1]) : null };
  }

  /* 1セット（1シートぶん）を登録する。quiz_sets → questions → question_choices → question_answers の順。
     ★解説は question_answers 側（学生が受験前に読めないように）。

     🔴 **is_open = false（下書き）で作る**（2026-09-11 きあ決定）。
        取り込んだ瞬間に学生へ出てしまう事故を無くすため。学生に見せるのは、
        一覧で「公開」を押したとき（＝ setOpen）。
        ★4月からは実施回（quiz_runs）でクラスごとに開く形になるので、
          そのとき is_open は「臨時で全員に開く」予備の手段に降りる。 */
  async function publishSet(set) {
    if (!set.questions.length) throw new Error("設問が1件も無いので登録できません");
    const cols = await probeColumns();

    const qs = await authedWrite("POST", "/rest/v1/quiz_sets",
      { title: set.title, lesson: set.lesson, is_open: false });
    const quizSetId = qs[0].id;

    for (const q of set.questions) {
      const qbody = { quiz_set_id: quizSetId, seq: q.seq, prompt: q.prompt };
      if (cols.questionExtra) {
        qbody.image_name = q.imageName; qbody.category = q.category; qbody.points = q.points;
      }
      const qr = await authedWrite("POST", "/rest/v1/questions", qbody);
      const questionId = qr[0].id;

      await authedWrite("POST", "/rest/v1/question_choices",
        q.choices.map((label, i) => ({ question_id: questionId, idx: i + 1, label })));

      const abody = { question_id: questionId, correct_idx: q.correctIdx };
      if (cols.explanation) abody.explanation = q.explanation;
      await authedWrite("POST", "/rest/v1/question_answers", abody);
    }
    const logged = await logEdit({
      quizSetId: quizSetId, title: set.title, action: "import",
      summary: "Excelから取り込んだ（" + set.questions.length + "問・下書き）",
      detail: { sheet: set.sheet || null, questions: set.questions.length },
    });
    return { quizSetId, questionCount: set.questions.length, logged };
  }

  /* 公開・停止の切り替え（2026-09-11）。
     ★これは学生に見えるかどうかを変えるだけで、中身には触らない。
       教師は quiz_sets のポリシー「teacher manage」で更新できるので、RPC は要らない。 */
  async function setOpen(quizSetId, open, opts) {
    const rows = await authedWrite(
      "PATCH", "/rest/v1/quiz_sets?id=eq." + encodeURIComponent(quizSetId) + "&select=id,is_open",
      { is_open: !!open });
    // 🔴 **0行しか変わらなくても PostgREST は 200 を返す。**
    //    そのまま「公開しました」と言うと、画面は成功と表示して中身は変わらない
    //    ＝2026-09-11 に実際にそう出た。**変わったことを確かめてから成功と言う。**
    if (!rows || !rows.length) {
      throw new Error("その回が見つからないか、変える権限がありません（1行も変わりませんでした）");
    }
    if (rows[0].is_open !== !!open) {
      throw new Error("状態が変わりませんでした（いまは " + (rows[0].is_open ? "公開中" : "下書き") + "）");
    }
    // ★履歴（2026-09-13）。失敗しても公開・停止そのものは成立している
    rows[0].logged = await logEdit({
      quizSetId: quizSetId, title: opts && opts.title,
      action: open ? "publish" : "unpublish",
      summary: open ? "学生に公開した" : "公開をやめた",
    });
    return rows[0];
  }

  /* 登録した回を消す（2026-09-11）。
     🔴 **必ず RPC を通す。** quiz_sets を直接 DELETE すると、外部キーの cascade で
        その回の受験記録まで一緒に消える（しかも cascade は RLS を通らない）。
        delete_quiz_set は受験記録が1件でもあれば例外にする＝**消してよい範囲だけに閉じてある**。
        db/2026-09-11_delete_quiz_set.sql を見よ。 */
  async function deleteSet(quizSetId, opts) {
    const r = await authedWrite("POST", "/rest/v1/rpc/delete_quiz_set", { p_quiz_set_id: quizSetId });
    /* ★消したあとに残す。quiz_edit_log は quiz_sets に外部キーを張っていないので、
       回が消えても「だれが消したか」は残る（db/2026-09-13_edit_log.sql）。 */
    await logEdit({
      quizSetId: quizSetId, title: (opts && opts.title) || "（消された回）", action: "delete_set",
      summary: "回ごと消した（設問 " + ((r && r.questions != null) ? r.questions : "?") + "問）",
      detail: r || null,
    });
    return r;
  }

  /* その回に受験記録が何件あるか（消せるかどうかを押す前に出すため）。 */
  async function attemptCount(quizSetId) {
    const rows = await authedGet(
      "/rest/v1/attempts?select=id&quiz_set_id=eq." + encodeURIComponent(quizSetId) + "&limit=1000");
    return rows.length;
  }

  /* ───────── 登録済みの回を「読み出して直す」（2026-09-13 きあ依頼）─────────
   *
   * ■ なぜ要るか
   *   それまで **登録したあとに設問を直す手段が1つも無かった**。しかも「消す」は
   *   受験記録が1件でもあると押せないので、誤字に気づいても打つ手が無い状態だった。
   *   ③1問ずつ修正 は **登録する前** にしか出ない画面だった。
   *   ★原因は判断の広げすぎ＝現場聞き取りの「誰もヨリソルの画面で問題を書いていない」から
   *     「取り込みが主・編集が従」と決めたのは正しい。ただしそれは **ゼロから作る画面** の話で、
   *     **直す画面** まで要らないことにはならなかった。
   *
   * ■ 直せるもの（2026-09-13 にきあ判断で制限を外した）
   *   設問文・選択肢（文言も個数も）・正解・カテゴリ・配点・解説、
   *   そして **設問そのものの追加（末尾）と削除**。
   *
   * ■ なぜ制限を外したか
   *   最初は「受験ずみなら選択肢の個数を変えさせない」「設問は増減させない」にしていた。
   *   過去の受験記録とのズレを避けるためだったが、きあの前提を聞いて判断が変わった:
   *     ・同じ学年が同じ日（午前・午後）に全員受ける。**再受験は無い**
   *     ・過去の学生と比べる必要はほとんど無い
   *     ・「あげたあとに直せる」ほうが、サイトとして使いやすい
   *   そのうえで実際に何が動くかを確かめたら、心配していたほどではなかった:
   *     attempts.score / total（点数）  → **動かない**（提出時に保存された数字）
   *     学生の「これまでの伸び」・CSV  → **動かない**（上を見ている）
   *     ライブ集計の設問ごとの正答率   → ここだけ変わる
   *   ＝ **設問を消しても、誰の点数も変わらない。**
   *
   * ■ それでも残る影響（画面で必ず知らせること）
   *   ・選択肢を入れ替えると、結果画面の「その学生が選んだ答え」の見え方がずれる
   *     （attempt_answers.chosen は文言ではなく **何番目か** の番号で持っているため）
   *   ・設問を消すと、その問の「何を選んだか」の記録も一緒に消える（点数は残る）
   */

  /* 1回ぶんを、取り込みウィザードと **同じ形** に組み立てて返す。
     ★埋め込み（questions?select=...,question_choices(...)）を使わず3回に分けて引く。
       questions からの埋め込みは quiz_set_questions 経由の経路があって
       PostgREST が「どちらか選べない」で 300 を返すことがある（一覧で踏んだ罠と同じ）。
       ここは1回ぶん（多くても数十行）なので、確実に動くほうを取る。 */
  async function loadSetForEdit(quizSetId) {
    const cols = await probeColumns();
    const enc = encodeURIComponent;

    const sel = "id,title,lesson,is_open" + (cols.quizSetsSource ? ",source_book,source_sheet" : "");
    const setRows = await authedGet("/rest/v1/quiz_sets?select=" + sel + "&id=eq." + enc(quizSetId));
    if (!setRows.length) throw new Error("その回が見つかりません（消されたか、見る権限がありません）");
    const s = setRows[0];

    const qcols = "id,seq,prompt" + (cols.questionExtra ? ",image_name,category,points" : "");
    const qrows = await authedGet("/rest/v1/questions?select=" + qcols +
      "&quiz_set_id=eq." + enc(quizSetId) + "&order=seq.asc");
    if (!qrows.length) throw new Error("この回には設問がありません（取り込み直してください）");

    const ids = qrows.map(q => q.id);
    const inList = "(" + ids.map(enc).join(",") + ")";
    const crows = await authedGet(
      "/rest/v1/question_choices?select=question_id,idx,label&question_id=in." + inList + "&order=idx.asc");
    const acols = "question_id,correct_idx" + (cols.explanation ? ",explanation" : "");
    const arows = await authedGet(
      "/rest/v1/question_answers?select=" + acols + "&question_id=in." + inList);

    const byQ = {}; ids.forEach(id => { byQ[id] = []; });
    crows.forEach(c => { if (byQ[c.question_id]) byQ[c.question_id].push(c); });
    const ansByQ = {}; arows.forEach(a => { ansByQ[a.question_id] = a; });

    const questions = qrows.map(q => {
      const cs = (byQ[q.id] || []).slice().sort((a, b) => a.idx - b.idx);
      const a = ansByQ[q.id] || {};
      return {
        id: q.id, seq: q.seq, prompt: q.prompt || "",
        choices: cs.map(c => c.label),
        /* ★読み出した時点の並び。書き戻すときに「何個だったか」「どれが変わったか」を
           これと比べて決める（変わっていない行に PATCH を投げない）。 */
        choicesBefore: cs.map(c => c.label),
        correctIdx: a.correct_idx || 1,
        imageName: q.image_name || null,
        category: q.category || null,
        points: (q.points === undefined ? null : q.points),
        explanation: a.explanation || null,
      };
    });

    return {
      id: s.id, title: s.title, lesson: s.lesson || "", isOpen: !!s.is_open,
      sheet: s.source_sheet || "", sourceBook: s.source_book || "",
      questions, dropped: [], unwritten: [], warn: [],
    };
  }

  /* 直した内容を書き戻す。★1問ずつ、下の順番を必ず守る。
   *
   *   (1) questions を直す
   *   (2) 選択肢を 1..N まで上書き／足りない分を足す
   *   (3) 正解（と解説）を直す        ← ★消す前
   *   (4) あふれた選択肢を消す        ← ★いちばん最後
   *
   * 🔴 (3) と (4) を入れ替えてはいけない。question_answers は
   *    (question_id, correct_idx) → question_choices(question_id, idx) の外部キーを
   *    **ON DELETE CASCADE** で持っている（db/2026-09-06_multi_choice.sql）。
   *    正解が指している選択肢を先に消すと、**正解の行ごと黙って消える**。
   *    そうなった設問は採点のときに正解が無く、受けた全員が不正解になる。
   */
  async function updateSetQuestions(set, opts) {
    opts = opts || {};
    const cols = await probeColumns();
    const enc = encodeURIComponent;

    /* ---- 先に全部検査する。★途中まで書いてから落とすと、直した回が半分だけ変わる ---- */
    if (!set.id) throw new Error("内部エラー: どの回を直すのかが分かりません");
    if (!set.questions.length) {
      throw new Error("設問が1件も無くなります。回そのものを消すなら、一覧の「消す」を使ってください");
    }
    const seen = {};
    for (const q of set.questions) {
      const at = "問" + (q.seq == null ? "（新しい設問）" : q.seq) + "：";
      const labels = (q.choices || []).map(c => (c == null ? "" : String(c).trim()));
      if (!String(q.prompt || "").trim()) throw new Error(at + "設問文が空です");
      if (labels.some(l => !l)) throw new Error(at + "空の選択肢があります（消すか、文字を入れてください）");
      if (labels.length < 2) throw new Error(at + "選択肢は2個以上ないと出題できません");
      // ★FmtImport.db は外側とは別の閉じた関数なので、上の MAX_CHOICES は見えない。
      //   写して2か所に持たず、公開してある定数を参照する（2026-09-13 に e2e が拾った）。
      if (labels.length > FmtImport.MAX_CHOICES) {
        throw new Error(at + "選択肢が多すぎます（上限 " + FmtImport.MAX_CHOICES + " 個）");
      }
      if (!(q.correctIdx >= 1 && q.correctIdx <= labels.length)) {
        throw new Error(at + "正解が選ばれていないか、選択肢の数と合っていません");
      }
      // 🔴 questions(quiz_set_id, seq) は一意。ぶつかると 409 になるので、ここで止める
      if (seen[q.seq]) throw new Error(at + "問題番号が重なっています（" + q.seq + "）");
      seen[q.seq] = true;
    }

    let nQ = 0, nChoice = 0, nAdd = 0, nDel = 0;

    /* (0) 消す設問。★いちばん先に消す＝末尾に足した設問と問題番号がぶつからないように。
       questions を消すと、外部キーの cascade で question_choices / question_answers /
       attempt_answers（その問で何を選んだか）も一緒に消える。
       ★消えないもの＝ attempts.score / total（点数）。提出時に保存された数字はそのまま残る。 */
    for (const id of (set.removedIds || [])) {
      await authedWrite("DELETE", "/rest/v1/questions?id=eq." + enc(id));
      nDel++;
    }
    set.removedIds = [];

    for (const q of set.questions) {
      const labels = q.choices.map(c => String(c).trim());
      const before = q.choicesBefore || [];

      /* 新しく足した設問（まだ id が無い）。publishSet と同じ順で入れる。
         ⓘ quiz_set_questions（②と①をつなぐ表）はトリガ questions_sync_set_link が入れる。 */
      if (!q.id) {
        const nbody = { quiz_set_id: set.id, seq: q.seq, prompt: q.prompt };
        if (cols.questionExtra) {
          nbody.image_name = q.imageName; nbody.category = q.category; nbody.points = q.points;
        }
        const nr = await authedWrite("POST", "/rest/v1/questions", nbody);
        const newId = nr[0].id;
        await authedWrite("POST", "/rest/v1/question_choices",
          labels.map((label, i) => ({ question_id: newId, idx: i + 1, label })));
        const nab = { question_id: newId, correct_idx: q.correctIdx };
        if (cols.explanation) nab.explanation = q.explanation;
        await authedWrite("POST", "/rest/v1/question_answers", nab);
        q.id = newId; q.choicesBefore = labels.slice();
        nAdd++; nChoice += labels.length;
        continue;
      }

      // (1) 設問。★0行でも PostgREST は 200 を返すので、変わったことを確かめる
      const qbody = { prompt: q.prompt };
      if (cols.questionExtra) {
        qbody.image_name = q.imageName; qbody.category = q.category; qbody.points = q.points;
      }
      const qr = await authedWrite("PATCH", "/rest/v1/questions?id=eq." + enc(q.id) + "&select=id", qbody);
      if (!qr || !qr.length) throw new Error("問" + q.seq + "：直せませんでした（1行も変わっていません）");

      // (2) 選択肢（1..N）。変わっていない行は触らない
      for (let i = 0; i < labels.length; i++) {
        const idx = i + 1;
        if (idx <= before.length) {
          if (labels[i] === before[i]) continue;
          const cr = await authedWrite("PATCH",
            "/rest/v1/question_choices?question_id=eq." + enc(q.id) + "&idx=eq." + idx + "&select=idx",
            { label: labels[i] });
          if (!cr || !cr.length) throw new Error("問" + q.seq + "：選択肢" + idx + "を直せませんでした");
        } else {
          await authedWrite("POST", "/rest/v1/question_choices",
            { question_id: q.id, idx: idx, label: labels[i] });
        }
        nChoice++;
      }

      // (3) 正解と解説（★(4) より先。理由は上の🔴）
      const abody = { correct_idx: q.correctIdx };
      if (cols.explanation) abody.explanation = q.explanation;
      const ar = await authedWrite("PATCH",
        "/rest/v1/question_answers?question_id=eq." + enc(q.id) + "&select=question_id", abody);
      if (!ar || !ar.length) throw new Error("問" + q.seq + "：正解を直せませんでした（1行も変わっていません）");

      // (4) あふれた選択肢を消す。ここまで来れば正解は必ず N 以下を指している
      if (labels.length < before.length) {
        await authedWrite("DELETE",
          "/rest/v1/question_choices?question_id=eq." + enc(q.id) + "&idx=gt." + labels.length);
        nChoice += (before.length - labels.length);
      }

      // 次に保存するときの比較元を、いま書いた内容に更新する（続けて直せるように）
      q.choicesBefore = labels.slice();
      nQ++;
    }
    const logged = await logEdit({
      quizSetId: set.id, title: set.title, action: "edit",
      summary: "設問を直した（直した " + nQ + "問"
             + (nAdd ? "／足した " + nAdd + "問" : "")
             + (nDel ? "／消した " + nDel + "問" : "") + "）",
      /* 🔴 キーの名前も「本文っぱく」しない。choices だと中身が選択肢の文字に見える。
         実際は直した箇所の件数。検査（tests/test_security.py test_09）は
         キーの名前で見ているので、緩めずにこちらを直した（2026-09-13）。 */
      detail: { edited: nQ, added: nAdd, removed: nDel, choice_edits: nChoice,
                seqs: set.questions.map(q => q.seq) },
    });
    return { questions: nQ, choices: nChoice, added: nAdd, removed: nDel, logged };
  }

  /* ───────── だれが・いつ・どの回を変えたかを残す（2026-09-13 きあ依頼）─────────
   *
   * ★記録に失敗しても、**元の操作は止めない**。
   *   「履歴が残せなかった」ために公開や保存が失敗するのは割に合わない。
   *   ただし **黙って飲み込まない**＝ ok:false を返して、呼んだ側が画面に出す。
   *   （db/2026-09-13_edit_log.sql に、トリガにしなかった理由も書いてある）
   *
   * 🔴 detail には設問の本文を入れない。入れるのは問題番号と件数まで。
   */
  async function logEdit(entry) {
    try {
      await authedWrite("POST", "/rest/v1/quiz_edit_log", {
        quiz_set_id: entry.quizSetId || null,
        quiz_set_title: String(entry.title || "（題名なし）").slice(0, 300),
        action: entry.action,
        summary: String(entry.summary || "").slice(0, 500),
        detail: entry.detail || null,
      });
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }

  /* 履歴を読む。★名前は profiles から引く（ログには id しか持たない）。 */
  async function readEditLog(opts) {
    opts = opts || {};
    const enc = encodeURIComponent;
    let q = "/rest/v1/quiz_edit_log?select=id,at,actor_id,quiz_set_id,quiz_set_title,action,summary,detail" +
            "&order=at.desc&limit=" + (opts.limit || 100);
    if (opts.quizSetId) q += "&quiz_set_id=eq." + enc(opts.quizSetId);
    const rows = await authedGet(q);
    const ids = [...new Set(rows.map(r => r.actor_id).filter(Boolean))];
    const names = {};
    if (ids.length) {
      try {
        const ps = await authedGet("/rest/v1/profiles?select=id,display_name,role&id=in.(" +
                                   ids.map(enc).join(",") + ")");
        ps.forEach(p => { names[p.id] = p.display_name + "（" + p.role + "）"; });
      } catch (e) { /* 名前が引けなくても履歴そのものは出す */ }
    }
    rows.forEach(r => { r.actor_name = names[r.actor_id] || "（不明）"; });
    return rows;
  }

  /* ───────── 課題登録FMT の形で Excel に書き出す（2026-09-13 きあ依頼）─────────
   *
   * ■ なぜ要るか（きあの言葉）
   *   「正本をだれかが触って、問題のDBが壊れる可能性もあるが…それは仕方ない。
   *     Excelをダウンロードできるようにもしておいて、万が一正本がぶっ壊れても復帰できるようにしたい」
   *   ＝ 編集できるようにした以上、**戻す道**が要る。
   *
   * ■ 大事なところ: **取り込みと同じ形で出す**
   *   出したファイルを、そのまま「①Excelから取り込む」に食わせて戻せる。
   *   列も、見出しも、1シート＝1回、というところも取り込み口と同じ。
   *   ★形を変えると、戻せるかどうかを別に確かめないといけなくなる。
   *
   * ■ 気をつけること
   *   ・シート名は Excel の決まりで **31文字まで**、`[ ] : * ? / \` が使えない。
   *     削ったせいで同じ名前になったら、後ろに (2) を付ける（黙って上書きしない）。
   *   ・設問文は DB では「問題文1 と 問題文2 を改行でつないだ1つ」になっている。
   *     書き戻すときは**最初の改行**で2つに割る。どこで割っても、取り込み口が
   *     また改行でつなぐので **中身は元どおりになる**（往復しても変わらない）。
   *   ・選択肢が6個以上ある設問があると、FMTの5列には収まらない。
   *     そのときだけ列を右に伸ばし、**そのことを呼び出し側に返す**（黙って捨てない）。
   */
  const FMT_HEADERS = ["問題番号", "問題文1", "問題文2", "添付ファイル名",
                       "選択肢1", "選択肢2", "選択肢3", "選択肢4", "選択肢5",
                       "解説", "解答", "カテゴリ", "配点"];

  function safeSheetName(name, used) {
    let base = String(name || "無題").replace(/[\[\]:*?\/\\]/g, "_").trim().slice(0, 28) || "無題";
    let n = base, i = 2;
    while (used[n]) { n = base.slice(0, 28 - String(i).length - 2) + "(" + i + ")"; i++; }
    used[n] = true;
    return n;
  }

  /* 1回ぶんを、FMT の行（配列の配列）にする。戻り値に「選択肢の最大数」も返す。 */
  function setToRows(set) {
    const maxCh = set.questions.reduce((a, q) => Math.max(a, (q.choices || []).length), 0);
    const nCh = Math.max(5, maxCh);                  // ★5未満でも FMT の5列は必ず出す
    const head = FMT_HEADERS.slice(0, 4)
      .concat(Array.from({ length: nCh }, (_, i) => "選択肢" + (i + 1)))
      .concat(["解説", "解答", "カテゴリ", "配点"]);
    const rows = [head];
    for (const q of set.questions) {
      const prompt = String(q.prompt || "");
      const cut = prompt.indexOf("\n");
      const t1 = cut < 0 ? prompt : prompt.slice(0, cut);
      const t2 = cut < 0 ? "" : prompt.slice(cut + 1);
      const chs = (q.choices || []).slice();
      while (chs.length < nCh) chs.push("");
      rows.push([q.seq, t1, t2, q.imageName || ""]
        .concat(chs)
        .concat([q.explanation || "", q.correctIdx, q.category || "", q.points == null ? "" : q.points]));
    }
    return { rows, maxCh };
  }

  /* 複数の回を1つのブックにして返す。{ wb, sheets, questions, wideSets } */
  function buildWorkbook(sets) {
    if (typeof XLSX === "undefined") throw new Error("Excelを書き出す部品（xlsx.js）が読み込まれていません");
    const wb = XLSX.utils.book_new();
    const used = {};
    let questions = 0;
    const wideSets = [];                              // 選択肢が6個以上あった回
    for (const set of sets) {
      if (!set.questions || !set.questions.length) continue;
      const { rows, maxCh } = setToRows(set);
      if (maxCh > 5) wideSets.push(set.title);
      const ws = XLSX.utils.aoa_to_sheet(rows);
      // ★シート名は元のシート名を優先する（取り込み元と同じ名前で戻せる）。無ければ題名
      XLSX.utils.book_append_sheet(wb, ws, safeSheetName(set.sheet || set.title, used));
      questions += set.questions.length;
    }
    if (!wb.SheetNames.length) throw new Error("書き出せる設問がありません");
    return { wb, sheets: wb.SheetNames.length, questions, wideSets };
  }

  /* ───────── 配る「作問シート」のテンプレートを、画面から落とせるようにする（2026-09-13）─────────
   *
   * ★きあ指摘：「場所が散らばると混乱するから。テンプレを管理者画面からダウンロードできるようにすればよくない？」
   *   それまではドライブのフォルダに置いていた。**手順書と置き場が別だと、片方だけ古くなる。**
   *   取り込む画面のすぐ隣に置けば、「ここから落として、ここに戻す」で1周する。
   *
   * 🔴 見本の3行は scripts/make_sakumon_template.py の SAMPLES と **1文字も違えてはいけない。**
   *    違うと指紋が変わり、見本が **本物の問題として取り込まれる**。
   *    tests/test_qsets_import.py が「Python 側の見本と一致するか」を毎回見ている。
   */
  /* ★見本のデータそのものは **外側の FmtImport** に置いてある。
     api.js を読まなくても（＝検査のNodeからも）届くようにするため。
     ここは Excel を組み立てるところだけ（XLSX が要る）。 */
  function buildTemplateWorkbook() {
    if (typeof XLSX === "undefined") throw new Error("Excelを作る部品（xlsx.js）が読み込まれていません");
    const wb = XLSX.utils.book_new();
    const ws = XLSX.utils.aoa_to_sheet([FmtImport.TEMPLATE_HEADERS].concat(FmtImport.TEMPLATE_ROWS));
    ws["!cols"] = [9, 38, 30, 16, 14, 14, 14, 14, 14, 32, 7, 12, 7].map(w => ({ wch: w }));
    ws["!freeze"] = { xSplit: 0, ySplit: 1 };
    XLSX.utils.book_append_sheet(wb, ws, FmtImport.TEMPLATE_SHEET_NAME);
    return wb;
  }

  function downloadTemplate(filename) {
    const wb = buildTemplateWorkbook();
    XLSX.writeFile(wb, filename || "【作問シート】テンプレート.xlsx");
    return { sheet: FmtImport.TEMPLATE_SHEET_NAME, samples: FmtImport.TEMPLATE_ROWS.length };
  }

  /* そのままダウンロードさせる。★サーバーには何も送らない（ブラウザの中だけで作る）。 */
  function downloadWorkbook(sets, filename) {
    const r = buildWorkbook(sets);
    XLSX.writeFile(r.wb, filename);
    // ★控えを取ったことも残す（いつの控えがあるか、あとから分かるように）。待たない
    logEdit({
      quizSetId: sets.length === 1 ? sets[0].id : null,
      title: sets.length === 1 ? sets[0].title : (sets.length + "回ぶん"),
      action: "export",
      summary: "Excelに書き出した（" + r.sheets + "回 / " + r.questions + "問）",
      detail: { sheets: r.sheets, questions: r.questions, filename: filename },
    });
    return r;
  }

  return { probeColumns, resetProbeCache, probeQuizSetsSource, listSourceBooks, searchQuizSets,
           publishSet, setOpen, deleteSet, attemptCount, loadSetForEdit, updateSetQuestions,
           buildWorkbook, downloadWorkbook, setToRows, safeSheetName,
           buildTemplateWorkbook, downloadTemplate,
           listBooksWithCounts, listSetsOfBook,
           logEdit, readEditLog, authedGet, authedWrite };
})();
