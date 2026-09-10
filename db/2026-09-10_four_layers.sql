-- =====================================================================
-- 4層に割る — 設問／問題セット／実施回／回答  2026-09-10
--
--   ★ db/2026-09-10_question_columns.sql を先に流すこと（submit_attempt をこちらで
--     作り直すので、順番が逆だと解説を返す修正が消える）。
--
-- ■ なぜ要るか（2026-09-06 きあと設計）
--   いまは②と③が混ざっている。
--
--     ① 設問       questions（＋ question_choices / question_answers）
--     ② 問題セット quiz_sets … 出題のまとまり＝原本。「L7 小テスト 20問」
--     ③ 実施回     quiz_runs（新）… 「1Aで 12/10 14:40 に開いた」
--     ④ 回答       attempts / attempt_answers
--
--   ・quiz_sets に opens_at を足す形にすると、1Aで開いて1Bで開き直したときに
--     **1Aの実施記録が上書きで消える**（きあの「間違えて違うクラスで始めた場合は？」）。
--   ・questions が quiz_set_id 直付けなので、設問を使い回すとコピーになり、
--     **集計から見て別の問題になる**。あいだに quiz_set_questions を挟む。
--   ・アンケートの月次化も同じ問題。survey_rounds を足す。
--     ★回答が入る前が、直す唯一の安いタイミング。
--
-- ■ このファイルの性質
--   **追加だけ。既存の列を消さない・型を変えない。既存データは1行も動かない。**
--   関数は create or replace（と、引数が増えるものだけ drop → create）。
--   クライアント（src/）は**1行も変えなくてよい**形にしてある＝
--   新しい引数はすべて既定値つきで、省略すると 2026-09-06 の挙動そのまま。
--
-- ■ 🔴 このファイルで**やらないこと**（意図的に残した2つ）
--   (1) submit_attempt / save_draft の「どの設問がこの回のものか」の読み手は
--       **questions.quiz_set_id のまま**にしてある。quiz_set_questions には
--       同じ内容を入れて（バックフィル＋トリガ）あるが、**読み手は切り替えない**。
--       理由: src/index.html が `questions?quiz_set_id=eq.X` で設問を取っている。
--       サーバー側だけ quiz_set_questions に切り替えると、**使い回しの設問が
--       学生の画面に出ないまま採点される**（見ていない問題で不正解が付く）。
--       ★切り替えるときは src/index.html の取得と同時に、1回で。
--   (2) survey_responses の一意制約 (student_id, survey_key) は**外していない**。
--       外すと src/assets/api.js の upsert（on_conflict=student_id,survey_key）が
--       即エラーになる。手順はこのファイルの末尾に書いた（★段階2・未実行）。
--       このファイルで作るのは器（survey_rounds と round_id 列）まで。
--
-- ■ 予約型について
--   ★きあ判断＝**開始型**（教師が「はじめる」を押した時刻が opens_at）。
--   「授業終了前20分から」は授業のコマの中の相対位置なので、絶対時刻で予約すると
--   授業が5分ずれただけで使えない。
--   ただし opens_at は実在の列なので、**未来の時刻で1行入れれば予約型になる**
--   （生き判定が now() between opens_at and closes_at なので、列を足さずに後付けできる）。
-- =====================================================================

begin;

-- =====================================================================
-- 1. ② 問題セット と ① 設問 のあいだ — quiz_set_questions
-- =====================================================================

-- 「どのセットに、どの設問が、何番目で載っているか」。
-- ★ここができると、同じ設問を1A用セットと復習用セットの両方に載せても
--   **同じ question_id のまま**でいられる＝集計で1つの問題として数えられる。
create table if not exists public.quiz_set_questions (
  quiz_set_id uuid    not null references public.quiz_sets(id) on delete cascade,
  question_id uuid    not null references public.questions(id) on delete cascade,
  seq         integer not null,
  primary key (quiz_set_id, question_id)
);

-- 同じセットの中で番号が重ならないこと
create unique index if not exists quiz_set_questions_seq_uniq
  on public.quiz_set_questions (quiz_set_id, seq);

-- 設問から「どのセットに載っているか」を引く用
create index if not exists quiz_set_questions_by_question
  on public.quiz_set_questions (question_id);

-- ---------- いまある設問を写す（バックフィル） ----------
-- ★これで quiz_set_questions は questions.quiz_set_id の関係を必ず含む状態になる。
insert into public.quiz_set_questions (quiz_set_id, question_id, seq)
select q.quiz_set_id, q.id, q.seq from public.questions q
on conflict do nothing;

-- ---------- これから入る設問も自動で写す ----------
-- 🔴 これが無いと、取り込みスクリプトや教師画面が questions にだけ入れたときに
--    quiz_set_questions が空のままになり、**あとで読み手を切り替えた瞬間に
--    「設問0件の回」が静かにできる**。安全網としてトリガを置く。
--    使い回し（同じ設問を別のセットにも載せる）は、明示的に insert する。
create or replace function app_hidden.sync_quiz_set_question()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  insert into public.quiz_set_questions (quiz_set_id, question_id, seq)
  values (new.quiz_set_id, new.id, new.seq)
  on conflict do nothing;
  return new;
end $$;

drop trigger if exists questions_sync_set_link on public.questions;
create trigger questions_sync_set_link
  after insert on public.questions
  for each row execute function app_hidden.sync_quiz_set_question();

-- ---------- RLS ----------
alter table public.quiz_set_questions enable row level security;

-- ★ to authenticated を必ず書く。省くと anon も対象になり、
--   「公開中の回なら読める」が未ログインでも真になる（2026-09-06 に踏みかけた穴）。
drop policy if exists "read links of open quiz" on public.quiz_set_questions;
create policy "read links of open quiz"
  on public.quiz_set_questions for select
  to authenticated
  using (
    exists (select 1 from public.quiz_sets s
             where s.id = quiz_set_questions.quiz_set_id and s.is_open)
    or app_hidden.is_teacher()
  );

drop policy if exists "teacher manage links" on public.quiz_set_questions;
create policy "teacher manage links"
  on public.quiz_set_questions for all
  to authenticated
  using (app_hidden.is_teacher())
  with check (app_hidden.is_teacher());

grant select on table public.quiz_set_questions to authenticated;
revoke all on table public.quiz_set_questions from anon;


-- =====================================================================
-- 2. ③ 実施回 — quiz_runs
-- =====================================================================

-- 自分のクラス名。profiles の RLS を貫いて引くためのヘルパー。
-- ★ポリシーの中から呼ぶので、quiz_runs は読まない（読むと再帰する）。
create or replace function app_hidden.my_class()
returns text
language sql
stable security definer
set search_path = public, pg_temp
as $$ select class_name from public.profiles where id = auth.uid() $$;

revoke all on function app_hidden.my_class() from public, anon, service_role;
grant execute on function app_hidden.my_class() to authenticated;

create table if not exists public.quiz_runs (
  id           uuid primary key default gen_random_uuid(),
  quiz_set_id  uuid        not null references public.quiz_sets(id) on delete cascade,

  -- 🔴 対象は「条件」ではなく「結果のリスト」で持つ。
  --    どちらも空なら全員。普段は class_names（転入生にも自動で出る）。
  --    ★国籍・エージェント・出席率での絞り込みは、外（Shinro Compass・学生マスタDB）で
  --      決めて student_ids に渡す。ポータルは「この人たちに出す」としか知らない。
  --      profiles にそれらの列を足さない（顔写真を入れないと決めたのと同じ重さの判断）。
  class_names  text[]      not null default '{}',
  student_ids  uuid[]      not null default '{}',

  -- いつ開いた／閉じる。★開始型（押した時刻が opens_at）。
  --   未来の opens_at で入れれば、そのまま予約型になる（列を足さずに後付けできる）。
  opens_at     timestamptz not null default now(),
  closes_at    timestamptz not null,
  duration_min integer,

  -- 取り消し。🔴 回答は消さない（集計から外れるだけ）。
  --   消す実装を作ると、事故のときに取り返しがつかない。
  is_void      boolean     not null default false,
  void_reason  text,
  voided_by    uuid        references public.profiles(id) on delete set null,
  voided_at    timestamptz,

  created_by   uuid        references public.profiles(id) on delete set null,
  created_at   timestamptz not null default now(),

  constraint quiz_runs_window_check check (closes_at > opens_at),
  -- ★小テストの実施回は1クラス（授業中に教師が押す。同じ時間に2クラスの授業はできない）。
  --   アンケート（survey_rounds）は複数クラス可＝粒度が違うので、無理に統一しない。
  constraint quiz_runs_one_class_check check (coalesce(array_length(class_names, 1), 0) <= 1)
);

create index if not exists quiz_runs_by_set  on public.quiz_runs (quiz_set_id, opens_at desc);
create index if not exists quiz_runs_live    on public.quiz_runs (closes_at) where not is_void;

alter table public.quiz_runs enable row level security;

-- 学生: いま自分に開いている回だけ見える。
-- ★このポリシーは quiz_runs を select しない（再帰しない）。
drop policy if exists "student reads own live run" on public.quiz_runs;
create policy "student reads own live run"
  on public.quiz_runs for select
  to authenticated
  using (
    not is_void
    and opens_at <= now() and now() < closes_at
    and (
      (coalesce(array_length(class_names, 1), 0) = 0
       and coalesce(array_length(student_ids, 1), 0) = 0)
      or auth.uid() = any (student_ids)
      or app_hidden.my_class() = any (class_names)
    )
  );

drop policy if exists "teacher manage runs" on public.quiz_runs;
create policy "teacher manage runs"
  on public.quiz_runs for all
  to authenticated
  using (app_hidden.is_teacher())
  with check (app_hidden.is_teacher());

grant select on table public.quiz_runs to authenticated;
revoke all on table public.quiz_runs from anon;


-- =====================================================================
-- 3. ④ 回答が「どの実施回のものか」— attempts.run_id
-- =====================================================================

-- ★列を足すだけ。既存の150行は null のまま＝「実施回の仕組みができる前の記録」。
--   null を「不正」として扱わないこと（過去の記録が消えたように見えるため）。
alter table public.attempts add column if not exists run_id uuid;
alter table public.attempts drop constraint if exists attempts_run_id_fkey;
alter table public.attempts
  add constraint attempts_run_id_fkey
  foreign key (run_id) references public.quiz_runs(id) on delete set null;

create index if not exists attempts_by_run on public.attempts (run_id);

-- ⚠ attempt_drafts / attempt_focus には run_id を足していない。
--   主キーが (student_id, quiz_set_id, ...) なので、列だけ足すと
--   「1人が同じセットを2回受けた」を表せないのに表せるように見える＝嘘になる。
--   主キーの張り替えは既存制約の作り直しなので、このファイルではやらない。
--   ★いまの運用（1人が同じセットを受けるのは1回）では困らない。
--     受け直しを入れると決めたときに、下書きと離席記録もまとめて設計し直すこと。


-- =====================================================================
-- 4. 実施回を動かす RPC
-- =====================================================================

-- ---------- 押す前に対象人数を出す（3段構えの「予防」） ----------
-- ★「1B（28人）で はじめます」＝人数が違えば押す前に気づく。
--   分母は「全員提出したらポップ」にも要るので、同じものが両方に効く。
create or replace function public.run_target_count(
  p_class_names text[] default '{}',
  p_student_ids uuid[] default '{}'
) returns integer
language sql
stable security definer
set search_path = public, pg_temp
as $$
  select case when not app_hidden.is_teacher() then null else (
    select count(*)::int from public.profiles p
     where p.role = 'student'
       and (
         (coalesce(array_length(p_class_names, 1), 0) = 0
          and coalesce(array_length(p_student_ids, 1), 0) = 0)
         or p.id = any (p_student_ids)
         or p.class_name = any (p_class_names)
       )
  ) end
$$;

revoke all on function public.run_target_count(text[], uuid[]) from public;
revoke execute on function public.run_target_count(text[], uuid[]) from anon;
grant execute on function public.run_target_count(text[], uuid[]) to authenticated;


-- ---------- はじめる ----------
create or replace function public.start_quiz_run(
  p_quiz_set_id  uuid,
  p_class_names  text[] default '{}',
  p_student_ids  uuid[] default '{}',
  p_duration_min integer default 20
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_run    quiz_runs%rowtype;
  v_n      integer;
  v_title  text;
begin
  if not app_hidden.is_teacher() then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  if p_duration_min is null or p_duration_min < 1 or p_duration_min > 480 then
    raise exception 'bad duration' using errcode = '22023';
  end if;
  select title into v_title from public.quiz_sets where id = p_quiz_set_id;
  if v_title is null then
    raise exception 'no such quiz set' using errcode = '22023';
  end if;

  insert into public.quiz_runs
        (quiz_set_id, class_names, student_ids, opens_at, closes_at, duration_min, created_by)
  values (p_quiz_set_id, coalesce(p_class_names, '{}'), coalesce(p_student_ids, '{}'),
          now(), now() + make_interval(mins => p_duration_min), p_duration_min, auth.uid())
  returning * into v_run;

  v_n := public.run_target_count(v_run.class_names, v_run.student_ids);

  return jsonb_build_object(
    'run_id', v_run.id, 'quiz_set_id', v_run.quiz_set_id, 'title', v_title,
    'class_names', to_jsonb(v_run.class_names), 'target_count', v_n,
    'opens_at', v_run.opens_at, 'closes_at', v_run.closes_at);
end $$;

revoke all on function public.start_quiz_run(uuid, text[], uuid[], integer) from public;
revoke execute on function public.start_quiz_run(uuid, text[], uuid[], integer) from anon;
grant execute on function public.start_quiz_run(uuid, text[], uuid[], integer) to authenticated;


-- ---------- 早く閉じる ----------
create or replace function public.close_quiz_run(p_run_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare v_run quiz_runs%rowtype;
begin
  if not app_hidden.is_teacher() then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  update public.quiz_runs
     set closes_at = least(closes_at, now())
   where id = p_run_id
  returning * into v_run;
  if v_run.id is null then
    raise exception 'no such run' using errcode = '22023';
  end if;
  return jsonb_build_object('run_id', v_run.id, 'closes_at', v_run.closes_at);
end $$;

revoke all on function public.close_quiz_run(uuid) from public;
revoke execute on function public.close_quiz_run(uuid) from anon;
grant execute on function public.close_quiz_run(uuid) to authenticated;


-- ---------- 取り消す（クラスを間違えて開いたときの「回復」） ----------
-- 🔴 回答は消さない。集計から外れ、学生の画面から消えるだけ。
create or replace function public.void_quiz_run(p_run_id uuid, p_reason text default null)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare v_run quiz_runs%rowtype;
begin
  if not app_hidden.is_teacher() then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  update public.quiz_runs
     set is_void = true, void_reason = p_reason,
         voided_by = auth.uid(), voided_at = now(),
         closes_at = least(closes_at, now())
   where id = p_run_id
  returning * into v_run;
  if v_run.id is null then
    raise exception 'no such run' using errcode = '22023';
  end if;
  return jsonb_build_object('run_id', v_run.id, 'is_void', true, 'voided_at', v_run.voided_at);
end $$;

revoke all on function public.void_quiz_run(uuid, text) from public;
revoke execute on function public.void_quiz_run(uuid, text) from anon;
grant execute on function public.void_quiz_run(uuid, text) to authenticated;


-- ---------- 学生: いま自分に開いている回 ----------
create or replace function public.my_open_runs()
returns jsonb
language sql
stable security definer
set search_path = public, pg_temp
as $$
  select coalesce(jsonb_agg(jsonb_build_object(
           'run_id', r.id, 'quiz_set_id', r.quiz_set_id,
           'title', s.title, 'lesson', s.lesson, 'closes_at', r.closes_at)
         order by r.closes_at), '[]'::jsonb)
    from public.quiz_runs r
    join public.quiz_sets s on s.id = r.quiz_set_id
   where auth.uid() is not null
     and not r.is_void
     and r.opens_at <= now() and now() < r.closes_at
     and (
       (coalesce(array_length(r.class_names, 1), 0) = 0
        and coalesce(array_length(r.student_ids, 1), 0) = 0)
       or auth.uid() = any (r.student_ids)
       or (select class_name from public.profiles where id = auth.uid()) = any (r.class_names)
     )
$$;

revoke all on function public.my_open_runs() from public;
revoke execute on function public.my_open_runs() from anon;
grant execute on function public.my_open_runs() to authenticated;


-- =====================================================================
-- 5. 閉じる判定をサーバー側に置く（端末の時計は当てにしない）
--    ★どちらも p_run_id は既定 null。省くと 2026-09-06 の挙動そのまま＝
--      クライアントを変えずに流せる。
-- =====================================================================

-- 実施回が、その学生にいま開いているか。開いていなければ理由つきで例外。
create or replace function app_hidden.assert_run_open(p_run_id uuid, p_quiz_set_id uuid)
returns void
language plpgsql
stable security definer
set search_path = public, pg_temp
as $$
declare r quiz_runs%rowtype;
begin
  select * into r from public.quiz_runs where id = p_run_id;
  if r.id is null then
    raise exception 'no such run' using errcode = '22023';
  end if;
  if r.quiz_set_id <> p_quiz_set_id then
    raise exception 'run does not belong to this quiz set' using errcode = '22023';
  end if;
  if r.is_void then
    raise exception 'run was cancelled' using errcode = '22023';
  end if;
  if now() < r.opens_at then
    raise exception 'run has not started' using errcode = '22023';
  end if;
  if now() >= r.closes_at then
    raise exception 'run is closed' using errcode = '22023';
  end if;
  if not (
    (coalesce(array_length(r.class_names, 1), 0) = 0
     and coalesce(array_length(r.student_ids, 1), 0) = 0)
    or auth.uid() = any (r.student_ids)
    or app_hidden.my_class() = any (r.class_names)
  ) then
    raise exception 'not a target of this run' using errcode = '42501';
  end if;
end $$;

revoke all on function app_hidden.assert_run_open(uuid, uuid) from public, anon, service_role;
grant execute on function app_hidden.assert_run_open(uuid, uuid) to authenticated;


-- ---------- 提出 ----------
-- 引数が1本増えるので、いったん落としてから作り直す（PostgREST が同名2つで迷わないように）
drop function if exists public.submit_attempt(uuid, jsonb, integer);

create or replace function public.submit_attempt(
  p_quiz_set_id uuid,
  p_answers     jsonb,
  p_duration_ms integer default null,
  p_run_id      uuid    default null
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

  if p_run_id is not null then
    -- ★実施回つきの提出は、実施回の窓で判定する（quiz_sets.is_open は見ない）
    perform app_hidden.assert_run_open(p_run_id, p_quiz_set_id);
  elsif not exists(select 1 from quiz_sets where id = p_quiz_set_id and is_open) then
    raise exception 'quiz not open';
  end if;

  -- ⚠ 読み手は questions.quiz_set_id のまま（冒頭「やらないこと (1)」を見よ）。
  --    quiz_set_questions へ切り替えるのは src/index.html の取得と同時に。
  select count(*) into v_total from questions where quiz_set_id = p_quiz_set_id;
  insert into attempts(student_id, quiz_set_id, score, total, duration_ms, run_id)
    values (auth.uid(), p_quiz_set_id, 0, v_total, p_duration_ms, p_run_id)
    returning id into v_attempt_id;

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
        'is_correct', v_chosen = q.correct_idx, 'explanation', q.explanation);
    else
      v_results := v_results || jsonb_build_object(
        'seq', q.seq, 'chosen', null, 'correct', q.correct_idx,
        'is_correct', false, 'explanation', q.explanation);
    end if;
  end loop;

  update attempts set score = v_score where id = v_attempt_id;
  return jsonb_build_object('attempt_id', v_attempt_id, 'score', v_score,
                            'total', v_total, 'results', v_results);
end $$;

revoke all on function public.submit_attempt(uuid, jsonb, integer, uuid) from public;
revoke execute on function public.submit_attempt(uuid, jsonb, integer, uuid) from anon;
grant execute on function public.submit_attempt(uuid, jsonb, integer, uuid) to authenticated;


-- ---------- 途中保存 ----------
drop function if exists public.save_draft(uuid, uuid, smallint, bigint);

create or replace function public.save_draft(
  p_quiz_set_id uuid,
  p_question_id uuid,
  p_chosen      smallint,
  p_client_seq  bigint default 0,
  p_run_id      uuid   default null
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

  if p_run_id is not null then
    perform app_hidden.assert_run_open(p_run_id, p_quiz_set_id);
  elsif not exists (
    select 1 from public.quiz_sets s where s.id = p_quiz_set_id and s.is_open
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
end $$;

revoke all on function public.save_draft(uuid, uuid, smallint, bigint, uuid) from public;
revoke execute on function public.save_draft(uuid, uuid, smallint, bigint, uuid) from anon;
grant execute on function public.save_draft(uuid, uuid, smallint, bigint, uuid) to authenticated;


-- ---------- 集計（実施回でも絞れるように） ----------
-- ★p_run_id 省略時は 2026-09-06 の挙動そのまま（セット全体の集計）。
--   ヨリソルの「25クラス＝25回ダウンロード」を避けるため、**既定は横断**にしてある。
drop function if exists public.quiz_stats(uuid);

create or replace function public.quiz_stats(p_quiz_set_id uuid, p_run_id uuid default null)
returns jsonb
language sql
stable security definer
set search_path = public, pg_temp
as $$
  select case when not app_hidden.is_teacher() then jsonb_build_object('error','forbidden') else
  jsonb_build_object(
    'attempts', coalesce((
      select jsonb_agg(jsonb_build_object(
        'student_no', p.student_no, 'name', p.display_name,
        'score', a.score, 'total', a.total, 'at', a.submitted_at,
        'run_id', a.run_id) order by a.submitted_at desc)
      from attempts a join profiles p on p.id = a.student_id
      where a.quiz_set_id = p_quiz_set_id
        and (p_run_id is null or a.run_id = p_run_id)
        -- 🔴 取り消された実施回は集計から外す（回答そのものは消していない）
        and not exists (select 1 from quiz_runs r where r.id = a.run_id and r.is_void)
      ), '[]'::jsonb),
    'by_question', coalesce((
      select jsonb_agg(jsonb_build_object('seq', q.seq, 'n', c.n, 'ok', c.ok) order by q.seq)
      from (select aa.question_id, count(*) n, count(*) filter (where aa.is_correct) ok
            from attempt_answers aa join attempts a on a.id = aa.attempt_id
            where a.quiz_set_id = p_quiz_set_id
              and (p_run_id is null or a.run_id = p_run_id)
              and not exists (select 1 from quiz_runs r where r.id = a.run_id and r.is_void)
            group by aa.question_id) c
      join questions q on q.id = c.question_id), '[]'::jsonb),
    -- ★離席の記録は個人別を返さない（クラス全体の合計だけ）。
    --   attempt_focus は実施回を持たないので、ここはセット単位のまま。
    'focus', (
      select jsonb_build_object(
        'students', coalesce(count(*) filter (where away_count > 0), 0),
        'events',   coalesce(sum(away_count), 0))
      from attempt_focus where quiz_set_id = p_quiz_set_id),
    'runs', coalesce((
      select jsonb_agg(jsonb_build_object(
        'run_id', r.id, 'class_names', to_jsonb(r.class_names),
        'opens_at', r.opens_at, 'closes_at', r.closes_at, 'is_void', r.is_void)
        order by r.opens_at desc)
      from quiz_runs r where r.quiz_set_id = p_quiz_set_id), '[]'::jsonb)
  ) end
$$;

revoke all on function public.quiz_stats(uuid, uuid) from public;
revoke execute on function public.quiz_stats(uuid, uuid) from anon;
grant execute on function public.quiz_stats(uuid, uuid) to authenticated;


-- =====================================================================
-- 6. アンケートの実施回 — survey_rounds（★器だけ。切り替えは段階2）
-- =====================================================================

-- 粒度は小テストと違う＝**複数クラス可**（月×学年で1本）。
-- 進路の月次アンケートは「1年生全員に1本 → 教師画面でクラス別に見る」。
-- ★クラスごとに5本作ると全体の傾向が出せなくなる（ヨリソルの縦割りと同じ形）。
create table if not exists public.survey_rounds (
  id          uuid primary key default gen_random_uuid(),
  -- src/assets/surveys.js の SURVEYS[].key と対応する。定義そのものはDBに持たない
  survey_key  text        not null,
  title       text,
  class_names text[]      not null default '{}',
  student_ids uuid[]      not null default '{}',
  opens_at    timestamptz not null default now(),
  closes_at   timestamptz,
  is_void     boolean     not null default false,
  void_reason text,
  created_by  uuid        references public.profiles(id) on delete set null,
  created_at  timestamptz not null default now(),
  constraint survey_rounds_window_check check (closes_at is null or closes_at > opens_at)
);

create index if not exists survey_rounds_by_key on public.survey_rounds (survey_key, opens_at desc);

alter table public.survey_rounds enable row level security;

drop policy if exists "student reads own live round" on public.survey_rounds;
create policy "student reads own live round"
  on public.survey_rounds for select
  to authenticated
  using (
    not is_void
    and opens_at <= now()
    and (closes_at is null or now() < closes_at)
    and (
      (coalesce(array_length(class_names, 1), 0) = 0
       and coalesce(array_length(student_ids, 1), 0) = 0)
      or auth.uid() = any (student_ids)
      or app_hidden.my_class() = any (class_names)
    )
  );

drop policy if exists "teacher manage rounds" on public.survey_rounds;
create policy "teacher manage rounds"
  on public.survey_rounds for all
  to authenticated
  using (app_hidden.is_teacher())
  with check (app_hidden.is_teacher());

grant select on table public.survey_rounds to authenticated;
revoke all on table public.survey_rounds from anon;

-- 回答に「どの回のものか」を足す。★既存の350行は null のまま。
alter table public.survey_responses add column if not exists round_id uuid;
alter table public.survey_responses drop constraint if exists survey_responses_round_id_fkey;
alter table public.survey_responses
  add constraint survey_responses_round_id_fkey
  foreign key (round_id) references public.survey_rounds(id) on delete set null;

-- 実施回つきの回答は「1人1回1本」。
-- ★round_id が null の行どうしは重複できる（Postgres は null を別物として数える）ので、
--   いまの回答（全部 null）はこの索引に引っかからない。
create unique index if not exists survey_responses_one_per_round
  on public.survey_responses (student_id, round_id);

commit;


-- =====================================================================
-- 流したあとの確認
--   py -X utf8 tests\test_security.py
--   py -X utf8 tests\test_drafts.py --live
--   py -X utf8 tests\test_choices.py --live
--   py -X utf8 tests\test_integrity.py --live
--   py -X utf8 tests\run_e2e_quiz.py
--   py -X utf8 tests\run_e2e_survey.py
--   Supabase の自動セキュリティ診断（get_advisors）→ ERROR 0件
--     ⚠ **public スキーマの RPC が5本増える**ので、許容WARN が 6件 → 11件になる見込み。
--        CLAUDE.md の「合格基準: WARN 6件以下」と、既知の許容WARN一覧を更新すること。
--        増えるのは start_quiz_run / close_quiz_run / void_quiz_run / run_target_count /
--        my_open_runs（すべて関数の中で is_teacher() か auth.uid() を検査している）。
--        ★app_hidden.my_class() と app_hidden.assert_run_open() は数に入れない＝
--          app_hidden は API に公開されないスキーマなので PostgREST から呼べず、advisor の対象外。
--        ※「見込み」なので、流したあとに実物を数えて一覧を書き直すこと。
--
-- 巻き戻し（上から順に）
--   begin;
--   drop function if exists public.my_open_runs();
--   drop function if exists public.void_quiz_run(uuid, text);
--   drop function if exists public.close_quiz_run(uuid);
--   drop function if exists public.start_quiz_run(uuid, text[], uuid[], integer);
--   drop function if exists public.run_target_count(text[], uuid[]);
--   drop function if exists app_hidden.assert_run_open(uuid, uuid);
--   drop trigger if exists questions_sync_set_link on public.questions;
--   drop function if exists app_hidden.sync_quiz_set_question();
--   drop index if exists public.survey_responses_one_per_round;
--   alter table public.survey_responses drop column if exists round_id;
--   drop table if exists public.survey_rounds;
--   alter table public.attempts drop column if exists run_id;
--   drop table if exists public.quiz_runs;
--   drop table if exists public.quiz_set_questions;
--   drop function if exists app_hidden.my_class();
--   -- submit_attempt / save_draft / quiz_stats は引数が変わっているので、
--   -- 引数つきで drop してから db/2026-09-06_multi_choice.sql の 7・8 節と
--   -- db/0000_baseline.sql の quiz_stats を流し直す:
--   drop function if exists public.submit_attempt(uuid, jsonb, integer, uuid);
--   drop function if exists public.save_draft(uuid, uuid, smallint, bigint, uuid);
--   drop function if exists public.quiz_stats(uuid, uuid);
--   commit;
--
-- =====================================================================
-- ★段階2（まだ流さない）— アンケートの一意制約の張り替え
--
--   いま survey_responses には unique (student_id, survey_key) が残っている。
--   これがあるうちは「同じアンケートに月ごとに答える」ができない。
--   ただし外すと **src/assets/api.js の upsert が即エラーになる**
--     api.upsert("survey_responses", "student_id,survey_key", ...)
--     → PostgREST は on_conflict=student_id,survey_key を使うので、
--       その名前の一意制約か索引が実在しないと 42P10 で失敗する。
--
--   なので DB とクライアントを**同時に**変える。手順:
--     1. src/index.html の提出を api.upsert("survey_responses","student_id,round_id",...) に変え、
--        回答に round_id を入れる（実施回が無い運用のアンケートは round を1本作って使う）
--     2. 下の SQL を流す
--     3. py -X utf8 tests\test_surveys.py --live で往復を確認
--
--   begin;
--   alter table public.survey_responses
--     drop constraint if exists survey_responses_student_id_survey_key_key;
--   -- 実施回が無い（round_id が null の）回答は、これまで通り1人1本に保つ
--   create unique index if not exists survey_responses_one_per_key_legacy
--     on public.survey_responses (student_id, survey_key) where round_id is null;
--   commit;
--
--   ⚠ 部分索引は PostgREST の on_conflict では使えない。段階2のあとは
--      round_id 付きの upsert（survey_responses_one_per_round）だけを使うこと。
-- =====================================================================
