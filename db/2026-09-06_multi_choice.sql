-- =====================================================================
-- 選択肢を2個固定から「いくつでも」へ  2026-09-06
--
-- ■ なぜ要るか
--   ヨリソルの設問バンクを実際に書き出したら、**2択ではなかった**。
--   実測（105問・選択肢836行）: 3個=142問 / 4個=84問 / 2個=21問 / 5個=4 / 6個=2 / 1個=2。
--   ★とくに**公開中の59問はすべて4択**。今の作り（choice_a / choice_b の2列）では
--   変換スクリプトを通しても取り込めた設問は 0 件だった。
--   ※ 以前「ヨリソルは2択なので1対1で対応する」と書いてあったのは、
--     サンプル1件が2択だったのを全体だと思い込んだもの。ここで直す。
--
-- ■ 作り
--   選択肢を questions の列から外し、別表 question_choices に出す。
--   1つの設問に選択肢が何個ぶら下がってもよい形にする。
--   答えの記録は 'a'/'b' ではなく **何番目を選んだか（idx）** になる。
--
-- ■ 表示順のランダム化との関係
--   ★保存するのは常に**元の番号（idx）**で、画面の並び順ではない。
--   並べ替えは表示だけの話（出題順と同じく、学生と設問の組で決まる並び）。
--   この分離があるので、並べ替えても採点・途中保存・集計はいっさい影響を受けない。
--
-- ■ データについて
--   デモの10問は choice_a / choice_b から idx 1,2 へそのまま移す。
--   提出済み150行の 'a'/'b' も 1/2 へ移す。★消える情報は無い。
-- =====================================================================

begin;

-- ---------- 1. 選択肢の表 ----------
create table if not exists public.question_choices (
  question_id uuid     not null references public.questions(id) on delete cascade,
  idx         smallint not null check (idx between 1 and 12),
  label       text     not null check (length(btrim(label)) > 0),
  primary key (question_id, idx)
);

alter table public.question_choices enable row level security;

-- questions と同じ条件で読める（公開中の回、または教師）。
-- ★正解はここに入れない。正解は question_answers（教師のみ）に分けたままにする。
-- ★ to authenticated を必ず付ける。付けないと全ロール（anon を含む）が対象になり、
--   「公開中の回なら読める」の条件は未ログインでも真になるので、選択肢が漏れる。
--   既存の questions のポリシーも to authenticated で書かれている（そろえる）。
drop policy if exists "read choices of open quiz" on public.question_choices;
create policy "read choices of open quiz"
  on public.question_choices for select
  to authenticated
  using (
    exists (
      select 1 from public.questions q
        join public.quiz_sets s on s.id = q.quiz_set_id
       where q.id = question_choices.question_id and s.is_open
    )
    or app_hidden.is_teacher()
  );

drop policy if exists "teacher manage choices" on public.question_choices;
create policy "teacher manage choices"
  on public.question_choices for all
  to authenticated
  using (app_hidden.is_teacher())
  with check (app_hidden.is_teacher());

-- ---------- 2. いまの2択を選択肢の表へ移す ----------
insert into public.question_choices (question_id, idx, label)
select id, 1, choice_a from public.questions
  where choice_a is not null and btrim(choice_a) <> ''
on conflict do nothing;

insert into public.question_choices (question_id, idx, label)
select id, 2, choice_b from public.questions
  where choice_b is not null and btrim(choice_b) <> ''
on conflict do nothing;

-- ---------- 3. 正解を「何番目か」に ----------
alter table public.question_answers add column if not exists correct_idx smallint;

update public.question_answers
   set correct_idx = case correct when 'a' then 1 when 'b' then 2 end
 where correct_idx is null and correct in ('a','b');

alter table public.question_answers alter column correct_idx set not null;
alter table public.question_answers drop constraint if exists question_answers_correct_check;
alter table public.question_answers drop column if exists correct;

-- 正解が、その設問に実在する選択肢を指していること
alter table public.question_answers drop constraint if exists question_answers_correct_idx_fkey;
alter table public.question_answers
  add constraint question_answers_correct_idx_fkey
  foreign key (question_id, correct_idx)
  references public.question_choices(question_id, idx) on delete cascade;

-- ---------- 4. 提出済みの解答を「何番目か」に ----------
alter table public.attempt_answers drop constraint if exists attempt_answers_chosen_check;
alter table public.attempt_answers
  alter column chosen type smallint
  using (case chosen when 'a' then 1 when 'b' then 2 else null end);
alter table public.attempt_answers
  add constraint attempt_answers_chosen_check check (chosen between 1 and 12);

-- ---------- 5. 下書きも同じく ----------
alter table public.attempt_drafts drop constraint if exists attempt_drafts_chosen_check;
alter table public.attempt_drafts
  alter column chosen type smallint
  using (case chosen when 'a' then 1 when 'b' then 2 else null end);
alter table public.attempt_drafts
  add constraint attempt_drafts_chosen_check check (chosen between 1 and 12);

-- ---------- 6. もう使わない2列を落とす ----------
alter table public.questions drop column if exists choice_a;
alter table public.questions drop column if exists choice_b;

-- ---------- 7. 採点（何番目を選んだかで採点する） ----------
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
    select qq.id, qq.seq, qa.correct_idx
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
        'is_correct', v_chosen = q.correct_idx);
    else
      v_results := v_results || jsonb_build_object(
        'seq', q.seq, 'chosen', null, 'correct', q.correct_idx, 'is_correct', false);
    end if;
  end loop;

  update attempts set score = v_score where id = v_attempt_id;
  return jsonb_build_object('attempt_id', v_attempt_id, 'score', v_score,
                            'total', v_total, 'results', v_results);
end $$;

revoke all on function public.submit_attempt(uuid, jsonb, integer) from public;
revoke execute on function public.submit_attempt(uuid, jsonb, integer) from anon;
grant execute on function public.submit_attempt(uuid, jsonb, integer) to authenticated;

-- ---------- 8. 途中保存も「何番目か」で受ける ----------
-- 引数の型が変わるので、text 版は落としてから作り直す
drop function if exists public.save_draft(uuid, uuid, text, bigint);

create or replace function public.save_draft(
  p_quiz_set_id uuid,
  p_question_id uuid,
  p_chosen      smallint,
  p_client_seq  bigint default 0
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_student uuid := auth.uid();
  v_seq     bigint;
  v_n       smallint;
begin
  if v_student is null then
    raise exception 'not signed in' using errcode = '28000';
  end if;

  -- 設問がその回のものか（別の回の設問を混ぜて保存させない）
  if not exists (
    select 1 from public.questions q
     where q.id = p_question_id and q.quiz_set_id = p_quiz_set_id
  ) then
    raise exception 'question does not belong to this quiz set' using errcode = '22023';
  end if;

  -- 選んだ番号が、その設問に実在する選択肢か
  select count(*) into v_n from public.question_choices c where c.question_id = p_question_id;
  if p_chosen is null or p_chosen < 1 or p_chosen > v_n then
    raise exception 'bad choice' using errcode = '22023';
  end if;

  if not exists (
    select 1 from public.quiz_sets s
     where s.id = p_quiz_set_id and s.is_open
  ) then
    raise exception 'quiz set is not open' using errcode = '22023';
  end if;

  insert into public.attempt_drafts as d
        (student_id, quiz_set_id, question_id, chosen, client_seq, updated_at)
  values (v_student, p_quiz_set_id, p_question_id, p_chosen, coalesce(p_client_seq,0), now())
  on conflict (student_id, quiz_set_id, question_id) do update
     set chosen     = excluded.chosen,
         client_seq = excluded.client_seq,
         updated_at = now()
   -- ★遅れて届いた古い回答で、新しい回答を上書きしない
   where excluded.client_seq >= d.client_seq;

  select d.client_seq into v_seq
    from public.attempt_drafts d
   where d.student_id = v_student
     and d.quiz_set_id = p_quiz_set_id
     and d.question_id = p_question_id;

  return jsonb_build_object('ok', true, 'client_seq', coalesce(v_seq, 0));
end;
$$;

revoke all on function public.save_draft(uuid, uuid, smallint, bigint) from public;
revoke execute on function public.save_draft(uuid, uuid, smallint, bigint) from anon;
grant execute on function public.save_draft(uuid, uuid, smallint, bigint) to authenticated;

-- ---------- 9. 表の権限 ----------
grant select on table public.question_choices to authenticated;
-- 未ログインには表そのものを触らせない（ポリシーと二重に閉じる）
revoke all on table public.question_choices from anon;

commit;

-- =====================================================================
-- 流したあとの確認（この4つが通ること）
--   py -X utf8 tests\test_security.py
--   py -X utf8 tests\test_drafts.py --live
--   py -X utf8 tests\test_integrity.py --live
--   py -X utf8 tests\test_choices.py --live
-- =====================================================================
