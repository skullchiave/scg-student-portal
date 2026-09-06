-- =====================================================================
-- 回答の途中保存（下書き）  2026-09-06
--
-- なぜ要るか: 校内Wi-Fiは落ちる前提。今は最後の1回で全問まとめて送るので、
--   途中で切れると解いた分が全部消える。「解いたのに消えた」は、サーバーが
--   落ちるより取り返しがつかない。後から足しにくいので先に入れる。
--
-- 作り: 1問答えるたびに1行を upsert する。(student_id, quiz_set_id, question_id)
--   が主キーなので、同じ回答が二度届いても行が増えず上書きになる（二重送信に強い）。
--   client_seq は端末側の連番。遅れて届いた古い回答が新しい回答を消さないための番。
--
-- 提出済みの記録（attempts / attempt_answers）とは別物。下書きは提出時に消す。
-- 学生は下書きテーブルへ直接書けない。書けるのは RPC 経由だけ。
-- =====================================================================

begin;

-- ---------- 下書き本体 ----------
create table if not exists public.attempt_drafts (
  student_id  uuid        not null default auth.uid()
                          references public.profiles(id) on delete cascade,
  quiz_set_id uuid        not null references public.quiz_sets(id) on delete cascade,
  question_id uuid        not null references public.questions(id) on delete cascade,
  chosen      text        not null check (chosen in ('a','b')),
  client_seq  bigint      not null default 0,
  updated_at  timestamptz not null default now(),
  primary key (student_id, quiz_set_id, question_id)
);

create index if not exists attempt_drafts_by_set
  on public.attempt_drafts (quiz_set_id, student_id);

alter table public.attempt_drafts enable row level security;

-- ---------- 読める人 ----------
-- 学生: 自分の下書きだけ（再開のため）
drop policy if exists "own drafts are readable" on public.attempt_drafts;
create policy "own drafts are readable"
  on public.attempt_drafts for select
  using (student_id = auth.uid());

-- 教師: 授業中に「誰がどこまで進んだか」を見るため。
--   ライブ集計（quiz_stats）で見えている範囲と同じ性質の情報。
drop policy if exists "teachers can read drafts" on public.attempt_drafts;
create policy "teachers can read drafts"
  on public.attempt_drafts for select
  using (app_hidden.is_teacher());

-- 書き込みポリシーは作らない＝学生も教師も直接は書けない。
-- 書けるのは下の save_draft / discard_drafts（security definer）だけ。

-- ---------- 1問ぶんの保存 ----------
create or replace function public.save_draft(
  p_quiz_set_id uuid,
  p_question_id uuid,
  p_chosen      text,
  p_client_seq  bigint default 0
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_student uuid := auth.uid();
  v_seq     bigint;
begin
  if v_student is null then
    raise exception 'not signed in' using errcode = '28000';
  end if;
  if p_chosen not in ('a','b') then
    raise exception 'bad choice' using errcode = '22023';
  end if;

  -- 設問がその回のものか（別の回の設問を混ぜて保存させない）
  if not exists (
    select 1 from public.questions q
     where q.id = p_question_id and q.quiz_set_id = p_quiz_set_id
  ) then
    raise exception 'question does not belong to this quiz set' using errcode = '22023';
  end if;

  -- 公開されていない回には保存させない（締切の判定はサーバー側で行う）
  if not exists (
    select 1 from public.quiz_sets s
     where s.id = p_quiz_set_id and s.is_open
  ) then
    raise exception 'quiz set is not open' using errcode = '22023';
  end if;

  insert into public.attempt_drafts as d
        (student_id, quiz_set_id, question_id, chosen, client_seq, updated_at)
  values (v_student,  p_quiz_set_id, p_question_id, p_chosen, coalesce(p_client_seq,0), now())
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

revoke all on function public.save_draft(uuid, uuid, text, bigint) from public;
-- ★anon も明示的に閉じる。revoke ... from public だけでは、Supabase の既定権限で
--   anon に execute が付き直してしまう（advisor の警告で判明・2026-09-06）
revoke execute on function public.save_draft(uuid, uuid, text, bigint) from anon;
grant execute on function public.save_draft(uuid, uuid, text, bigint) to authenticated;

-- ---------- 提出できたら下書きを捨てる ----------
create or replace function public.discard_drafts(p_quiz_set_id uuid)
returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_student uuid := auth.uid();
  v_n integer;
begin
  if v_student is null then
    raise exception 'not signed in' using errcode = '28000';
  end if;
  delete from public.attempt_drafts
   where student_id = v_student and quiz_set_id = p_quiz_set_id;
  get diagnostics v_n = row_count;
  return v_n;
end;
$$;

revoke all on function public.discard_drafts(uuid) from public;
revoke execute on function public.discard_drafts(uuid) from anon;
grant execute on function public.discard_drafts(uuid) to authenticated;

commit;

-- =====================================================================
-- 流したあとの確認（この2つが通ること）
--   py -X utf8 tests\test_security.py     … 既存の防御が壊れていないか
--   py -X utf8 tests\test_drafts.py --live … 下書きの保存・再開・二重送信・順序
-- =====================================================================
