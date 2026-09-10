-- =====================================================================
-- 課題登録FMT にあって、こちらに無かった4つを足す  2026-09-10
--
-- ■ なぜ要るか
--   先生が問題を書く Excel「課題登録FMT」には、いまの questions に無い項目が4つある。
--     添付ファイル名（画像）／カテゴリ／配点／解説
--   取り込み口（scripts/import_fmt_xlsx.py）は JSON にはこの4つを残しているが、
--   SQL には出していない。★つまり **DBに入れた時点で消える**。
--   画像を画面に出すと決めたとき、カテゴリで絞りたくなったときに、
--   「入れ直し」になる。入れる前のいまが、足すのに一番安いタイミング。
--
-- ■ 🔴 解説だけ置き場が違う（2026-09-10 の設計で判明・重要）
--   questions は「公開中の回に属する設問なら学生が読める」ポリシーで守られている。
--   ★**解説をここに置くと、学生が受験前に解説を読める**＝正解が漏れる。
--   なので解説は questions ではなく **question_answers（教師のみ）** に置く。
--   学生に見せるのは、採点が終わったあとに submit_attempt が返す形にする（このファイルで対応済み）。
--
--     image_name  → questions        （設問を表示するのに要る。学生が見てよい）
--     category    → questions        （分類。見えても害が無い）
--     points      → questions        （配点。ふつう学生にも見せるもの）
--     explanation → question_answers  🔴 正解につながるので教師だけ
--
-- ■ 配点について（このファイルでは採点に使わない）
--   points 列は足すが、**submit_attempt の採点はいまのまま「1問1点」**。
--   配点で採点する形に変えると、既存の attempts.score / total の意味が変わり、
--   過去の記録と比べられなくなる。★これは決めてもらうこと（保留）。
--   いまは「Excel に書かれた配点を捨てずに持っておく」までにとどめる。
--
-- ■ このファイルの性質
--   **追加だけ。既存の列を消さない・型を変えない。** 途中で止めても壊れない。
--   すでに入っているデータは1行も動かない（全部 null で入るだけ）。
--
-- ■ 巻き戻し方
--   このファイルの一番下に、足したものを外す SQL を書いてある（コメントアウト）。
--   列を落とすとその列に入れた値は消えるので、流し直す前に中身を確認すること。
-- =====================================================================

begin;

-- ---------- 1. questions に3列 ----------

-- 添付ファイル名。実データでは 200問中2問で使われている（例「7-9-⑮ゴミ出し.png」）。
-- ★ファイル名だけを持ち、画像そのものは Supabase に入れない
--   （顔写真を入れないと決めたのと同じ考え方。置かずに済むなら置かない）。
--   出すときは学校の Google ドライブ側の配信口を使う。
alter table public.questions add column if not exists image_name text;

-- カテゴリ。Excel の「カテゴリ」列（例「文法」「読解」）。
-- ⚠ 実データでは「④10-12」シートだけ見出しが「文法読解」に書き換わっていた。
--   値のゆれは取り込み時には直さない（勝手に寄せると元が分からなくなる）。
alter table public.questions add column if not exists category text;

-- 配点。null = 「書かれていない」＝ 1点あつかい。
-- ★上の「配点について」の通り、いまの採点はこの列を見ない。
alter table public.questions add column if not exists points smallint;
alter table public.questions drop constraint if exists questions_points_check;
alter table public.questions
  add constraint questions_points_check check (points is null or points between 0 and 1000);


-- ---------- 2. question_answers に解説 ----------
-- 🔴 学生から読めない表に置く。ここが questions と分かれている理由そのもの。
alter table public.question_answers add column if not exists explanation text;


-- ---------- 3. 採点のあとに解説を返す ----------
-- 学生が解説を見られるのは**提出したあと**だけ。サーバー側（SECURITY DEFINER）で
-- question_answers を読んで、結果に混ぜて返す。
-- ★引数は 2026-09-06 の版と同じ（クライアントを変えなくてよい）。
create or replace function public.submit_attempt(
  p_quiz_set_id uuid,
  p_answers     jsonb,
  p_duration_ms integer default null
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_attempt_id uuid;
  v_score int := 0;
  v_total int;
  v_results jsonb := '[]'::jsonb;
  q record;
  v_raw text;
  v_chosen smallint;
  v_n smallint;
begin
  if auth.uid() is null then raise exception 'not authenticated'; end if;
  if not exists(select 1 from quiz_sets where id = p_quiz_set_id and is_open) then
    raise exception 'quiz not open';
  end if;

  select count(*) into v_total from questions where quiz_set_id = p_quiz_set_id;
  insert into attempts(student_id, quiz_set_id, score, total, duration_ms)
    values (auth.uid(), p_quiz_set_id, 0, v_total, p_duration_ms) returning id into v_attempt_id;

  for q in
    select qq.id, qq.seq, qa.correct_idx, qa.explanation
    from questions qq join question_answers qa on qa.question_id = qq.id
    where qq.quiz_set_id = p_quiz_set_id order by qq.seq
  loop
    select count(*) into v_n from question_choices c where c.question_id = q.id;

    v_raw := p_answers->>(q.id::text);
    v_chosen := null;
    -- 数字でないもの・範囲外は「未回答」として扱う（例外にしない＝1問のミスで提出全体を落とさない）
    if v_raw ~ '^[0-9]{1,2}$' then
      v_chosen := v_raw::smallint;
      if v_chosen < 1 or v_chosen > v_n then v_chosen := null; end if;
    end if;

    if v_chosen is not null then
      insert into attempt_answers(attempt_id, question_id, chosen, is_correct)
        values (v_attempt_id, q.id, v_chosen, v_chosen = q.correct_idx);
      if v_chosen = q.correct_idx then v_score := v_score + 1; end if;
      v_results := v_results || jsonb_build_object(
        'seq', q.seq, 'chosen', v_chosen, 'correct', q.correct_idx,
        'is_correct', v_chosen = q.correct_idx,
        -- ★提出後なので解説を返してよい。未設定なら null（画面は出さない）
        'explanation', q.explanation);
    else
      v_results := v_results || jsonb_build_object(
        'seq', q.seq, 'chosen', null, 'correct', q.correct_idx, 'is_correct', false,
        'explanation', q.explanation);
    end if;
  end loop;

  update attempts set score = v_score where id = v_attempt_id;
  return jsonb_build_object('attempt_id', v_attempt_id, 'score', v_score,
                            'total', v_total, 'results', v_results);
end $$;

-- ★新しい RPC ではないが、create or replace で権限が戻ることがあるので毎回書く
revoke all on function public.submit_attempt(uuid, jsonb, integer) from public;
revoke execute on function public.submit_attempt(uuid, jsonb, integer) from anon;
grant execute on function public.submit_attempt(uuid, jsonb, integer) to authenticated;

commit;


-- =====================================================================
-- 流したあとの確認
--   py -X utf8 tests\test_security.py
--   py -X utf8 -m unittest discover -s tests -p "test_import_fmt_xlsx.py"
--   py -X utf8 scripts\import_fmt_xlsx.py --xlsx "...(作成用).xlsx" --out-sql tmp\q.sql
--     → SQL に image_name / category / points / explanation が出ること
--
-- 巻き戻し（★列を落とすと、その列に入れた値は消える）
--   begin;
--   alter table public.question_answers drop column if exists explanation;
--   alter table public.questions drop constraint if exists questions_points_check;
--   alter table public.questions drop column if exists points;
--   alter table public.questions drop column if exists category;
--   alter table public.questions drop column if exists image_name;
--   -- submit_attempt は db/2026-09-06_multi_choice.sql の「7.」節をもう一度流せば戻る
--   commit;
-- =====================================================================
