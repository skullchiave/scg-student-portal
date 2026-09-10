/* scg-student-portal 教師画面 — 課題登録FMT Excel の取り込み（2026-09-10）
 *
 * teacher.html の「問題の登録・解放」から使う。ライブラリは xlsx.js（SheetJS・CDN）のみ、
 * これは teacher.html だけで読み込む（学生画面 index.html の「ライブラリ依存ゼロ」は守る）。
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
  const TEMPLATE_MARK = "FMT";           // シート名にこれを含むものはテンプレート本体
  const CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳";
  const RUBY = /\$\{([^}]*)\}\(([^)]*)\)/g;

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
  function listImportableSheets(workbook) {
    // テンプレート本体（シート名に FMT を含む）は最初から出さない
    return workbook.SheetNames.filter(n => n.indexOf(TEMPLATE_MARK) === -1);
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
  };
})();

/* ---------------------------------------------------------------- DB への書き込み（公開時のみ）
 * teacher.html だけで使う。api.js の api オブジェクト（ログイン・自動再送つきfetch）をそのまま使う。
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
     判定は軽い読み取りだけ（1行 select）＝書き込みを試して失敗を拾うより安全。 */
  async function probeColumns() {
    if (colsProbed) return colsProbed;
    const probe = async (table, cols) => {
      try { await authedGet(`/rest/v1/${table}?select=${cols}&limit=1`); return true; }
      catch (e) { return false; }
    };
    colsProbed = {
      questionExtra: await probe("questions", "image_name,category,points"),
      explanation: await probe("question_answers", "explanation"),
    };
    return colsProbed;
  }

  function resetProbeCache() { colsProbed = null; }   // テスト・やり直し用

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
    return { quizSetId, questionCount: set.questions.length };
  }

  /* 公開・停止の切り替え（2026-09-11）。
     ★これは学生に見えるかどうかを変えるだけで、中身には触らない。
       教師は quiz_sets のポリシー「teacher manage」で更新できるので、RPC は要らない。 */
  async function setOpen(quizSetId, open) {
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
    return rows[0];
  }

  /* 登録した回を消す（2026-09-11）。
     🔴 **必ず RPC を通す。** quiz_sets を直接 DELETE すると、外部キーの cascade で
        その回の受験記録まで一緒に消える（しかも cascade は RLS を通らない）。
        delete_quiz_set は受験記録が1件でもあれば例外にする＝**消してよい範囲だけに閉じてある**。
        db/2026-09-11_delete_quiz_set.sql を見よ。 */
  async function deleteSet(quizSetId) {
    return await authedWrite("POST", "/rest/v1/rpc/delete_quiz_set", { p_quiz_set_id: quizSetId });
  }

  /* その回に受験記録が何件あるか（消せるかどうかを押す前に出すため）。 */
  async function attemptCount(quizSetId) {
    const rows = await authedGet(
      "/rest/v1/attempts?select=id&quiz_set_id=eq." + encodeURIComponent(quizSetId) + "&limit=1000");
    return rows.length;
  }

  return { probeColumns, resetProbeCache, publishSet, setOpen, deleteSet, attemptCount,
           authedGet, authedWrite };
})();
