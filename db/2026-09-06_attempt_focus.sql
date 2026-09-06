-- =====================================================================
-- 画面を離れた記録  2026-09-06
--
-- ★これは「不正の検知」ではない。きあ方針（2026-09-06）:
--     小テストは到達度をはかる目安の一つで、成績には反映しない。
--     だからカンニングをしても下がるのはその学生の学習効果だけ。
--     罰として使わず、「この回の到達度確認は、うまく測れていないかもしれない」
--     という目安にとどめる。
--
-- したがって:
--   - 学生ごとの一覧は作らない（教師画面はクラス全体の合計だけを出す）
--   - 学生本人にも見せない（「あなたは4回離れました」は罰の言い方になる）
--   - 記録は残す。使い道は「この回の数字をどれくらい信用するか」の判断材料
--
-- ★証拠にはならない。iPhone は通知が来ただけ・画面が消えただけで同じ反応をする。
--   数えているのは「画面が隠れた回数」であって「調べものをした回数」ではない。
--
-- 下書き（attempt_drafts）と違い、提出しても消さない。1人1回につき1行。
-- =====================================================================

begin;

create table if not exists public.attempt_focus (
  student_id  uuid        not null default auth.uid()
                          references public.profiles(id) on delete cascade,
  quiz_set_id uuid        not null references public.quiz_sets(id) on delete cascade,
  away_count  integer     not null default 0,
  away_ms     bigint      not null default 0,
  updated_at  timestamptz not null default now(),
  primary key (student_id, quiz_set_id)
);

create index if not exists attempt_focus_by_set
  on public.attempt_focus (quiz_set_id);

alter table public.attempt_focus enable row level security;

-- 読めるのは本人と教師だけ。書き込みポリシーは作らない＝RPC 経由でしか書けない。
drop policy if exists "own focus is readable" on public.attempt_focus;
create policy "own focus is readable"
  on public.attempt_focus for select
  using (student_id = auth.uid());

drop policy if exists "teachers can read focus" on public.attempt_focus;
create policy "teachers can read focus"
  on public.attempt_focus for select
  using (app_hidden.is_teacher());

-- ---------- 記録する ----------
-- 端末側が持っている累計をそのまま送る。★greatest で必ず増える方向にしか動かないので、
-- 二重送信・順序の入れ替え・再読み込みのどれでも数が減らない（下書きと同じ考え方）。
create or replace function public.record_away(
  p_quiz_set_id uuid,
  p_away_count  integer,
  p_away_ms     bigint default 0
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_student uuid := auth.uid();
  v_n integer;
  v_ms bigint;
begin
  if v_student is null then
    raise exception 'not signed in' using errcode = '28000';
  end if;
  if coalesce(p_away_count,0) < 0 or coalesce(p_away_ms,0) < 0 then
    raise exception 'bad counter' using errcode = '22023';
  end if;
  if not exists (select 1 from public.quiz_sets s where s.id = p_quiz_set_id) then
    raise exception 'no such quiz set' using errcode = '22023';
  end if;

  insert into public.attempt_focus as f
        (student_id, quiz_set_id, away_count, away_ms, updated_at)
  values (v_student, p_quiz_set_id, coalesce(p_away_count,0), coalesce(p_away_ms,0), now())
  on conflict (student_id, quiz_set_id) do update
     set away_count = greatest(f.away_count, excluded.away_count),
         away_ms    = greatest(f.away_ms,    excluded.away_ms),
         updated_at = now();

  select f.away_count, f.away_ms into v_n, v_ms
    from public.attempt_focus f
   where f.student_id = v_student and f.quiz_set_id = p_quiz_set_id;

  return jsonb_build_object('ok', true, 'away_count', v_n, 'away_ms', v_ms);
end;
$$;

revoke all on function public.record_away(uuid, integer, bigint) from public;
revoke execute on function public.record_away(uuid, integer, bigint) from anon;
grant execute on function public.record_away(uuid, integer, bigint) to authenticated;

-- ---------- 教師向け集計に「全体の合計」だけ足す ----------
-- ★誰が何回か は返さない。返せば必ず個人を責める使われ方になる（方針で決めた通り）。
create or replace function public.quiz_stats(p_quiz_set_id uuid)
returns jsonb
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select case when not app_hidden.is_teacher() then jsonb_build_object('error','forbidden') else
  jsonb_build_object(
    'attempts', coalesce((
      select jsonb_agg(jsonb_build_object(
        'student_no', p.student_no, 'name', p.display_name,
        'score', a.score, 'total', a.total, 'at', a.submitted_at) order by a.submitted_at desc)
      from attempts a join profiles p on p.id = a.student_id
      where a.quiz_set_id = p_quiz_set_id), '[]'::jsonb),
    'by_question', coalesce((
      select jsonb_agg(jsonb_build_object('seq', q.seq, 'n', c.n, 'ok', c.ok) order by q.seq)
      from (select question_id, count(*) n, count(*) filter (where is_correct) ok
            from attempt_answers aa join attempts a on a.id = aa.attempt_id
            where a.quiz_set_id = p_quiz_set_id group by question_id) c
      join questions q on q.id = c.question_id), '[]'::jsonb),
    'focus', (
      select jsonb_build_object(
        'students', coalesce(count(*) filter (where away_count > 0), 0),
        'events',   coalesce(sum(away_count), 0))
      from attempt_focus where quiz_set_id = p_quiz_set_id)
  ) end
$$;

revoke all on function public.quiz_stats(uuid) from public;
revoke execute on function public.quiz_stats(uuid) from anon;
grant execute on function public.quiz_stats(uuid) to authenticated;

commit;

-- =====================================================================
-- 流したあとの確認
--   py -X utf8 tests\test_security.py       … 既存の防御が壊れていないか
--   py -X utf8 tests\test_integrity.py --live … 並べ替えと画面を離れた記録
-- =====================================================================
