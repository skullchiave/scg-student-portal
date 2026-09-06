-- =============================================================================
-- SCG 学生ポータル — データベースのベースライン（設計図）
--
--   対象      : scg-portal / project ref egdcbxzpgwenmfabpodd
--               ap-northeast-1 / PostgreSQL 17.6
--   書き出し日: 2026-09-06
--
-- ■ これは何か
--   これまで Supabase の中にしか存在しなかった構造（表・制約・索引・RLS・
--   ポリシー・関数・権限）を、その時点の実物からそのまま写し取ったもの。
--   ★書き出したのが 2026-09-06 の作業の「後」なので、同日の
--   db/2026-09-06_attempt_drafts.sql と db/2026-09-06_attempt_focus.sql の内容も
--   すでにここに入っている（＝この1本で 2026-09-06 時点の全部が揃う）。
--   その2本を後から流しても害はない（if not exists / or replace で書いてあるため）。
--   データは1行も含まない（構造だけ）。
--
-- ■ 何のために要るか
--   Supabase のプロジェクトを失っても、このファイル1本で同じ構造を組み直せる。
--   「壊れたとき誰が直すか」への答えがこれ。
--   本番を学校名義のアカウントで作り直すときにも、まずこれを流す。
--
-- ■ 組み直せることの確認（2026-09-06 実施）
--   ★「写し取っただけ」で終わらせず、実際に流して通ることを確かめてある。
--   やり方: このファイルのスキーマ名だけ検査用（bl_test / bl_test_hidden）に置き換え、
--           同じDBで begin 〜 rollback で囲んで1回流した。本番の表には触れていない。
--   結果  : 最後まで通り、できたものが現物と一致した。
--           表 9 ／ 制約 29 ／ ポリシー 16 ／ 関数 6 ／ 索引 14（主キー9＋UNIQUE3＋明示2）
--           検査用スキーマは巻き戻し済み（あとで残っていないことも確認した）。
--   ※ 列を足すなど中身を変えたときは、同じ手順でもう一度確かめられる。
--
-- ■ 使い方
--   空の Supabase プロジェクト（auth スキーマがある前提）の SQL Editor に、
--   上から順にそのまま流す。★1回だけ流すファイルで、冪等ではない
--   （2回流すと「既にある」でエラーになる。それで正しい）。
--
-- ■ これ以降の変更のしかた
--   このファイルは書き換えない。スキーマを変えるときは db/ に日付つきの
--   新しいSQLを足していく（例: db/2026-09-06_attempt_drafts.sql）。
--
-- ■ 取り直し方（次に現物と突き合わせるとき）
--   Supabase の SQL Editor で pg_catalog を読んで再生成する。使った問い合わせ:
--     表      : pg_class + pg_attribute + pg_attrdef を format() で組み立て
--     制約    : pg_get_constraintdef(oid)
--     索引    : pg_indexes.indexdef
--     ポリシー: pg_policies
--     関数    : pg_get_functiondef(oid)
--     権限    : information_schema.role_table_grants / has_function_privilege()
--
-- ■ 流す順序（依存関係）
--   スキーマ → 表 → 制約 → 索引 → 関数 → RLS有効化 → ポリシー → 権限
--   ポリシーが app_hidden.is_teacher() を参照するので、関数はポリシーより先。
-- =============================================================================


-- =============================================================================
-- 1. スキーマ
-- =============================================================================

-- 教師判定のヘルパーを置く場所。API に公開されないスキーマにすることで、
-- クライアントから直接呼べないようにしている。
create schema if not exists app_hidden;

-- 2026-09-06 実測: authenticated だけが usage を持つ。
-- anon と service_role には与えない（与えると匿名から教師判定を呼べてしまう）。
grant usage on schema app_hidden to authenticated;


-- =============================================================================
-- 2. 表
-- =============================================================================

-- 学生・教師の名簿。id は Supabase Auth のユーザーと1対1。
-- student_no = 学籍番号（疑似メール `学籍番号@MAIL_DOMAIN` の左側と同じ）。
-- ※ 学年の列は無い。所属は class_name（例「A①クラス」）の文字列だけで持っている。
create table public.profiles (
  id uuid not null,
  student_no text not null,
  display_name text not null,
  role text default 'student'::text not null,
  class_name text
);

-- 小テストの「回」。is_open が配信スイッチ（false のあいだ学生には見えない）。
create table public.quiz_sets (
  id uuid default gen_random_uuid() not null,
  title text not null,
  lesson text,
  is_open boolean default false not null,
  created_at timestamp with time zone default now() not null
);

-- 設問。2択（choice_a / choice_b）。
-- ※ 正解列はここに無い。question_answers に分離してある（学生に正解を送らないため）。
-- ※ quiz_set_id への直付け＝いまは設問を回ごとに持つ形で、使い回す器（設問バンク）が無い。
create table public.questions (
  id uuid default gen_random_uuid() not null,
  quiz_set_id uuid not null,
  seq integer not null,
  prompt text not null,
  choice_a text not null,
  choice_b text not null
);

-- 正解。教師だけが読める（RLS「teacher only」）。
create table public.question_answers (
  question_id uuid not null,
  correct text not null
);

-- 提出済みの受験記録。採点は RPC submit_attempt がサーバー側で行う。
create table public.attempts (
  id uuid default gen_random_uuid() not null,
  student_id uuid not null,
  quiz_set_id uuid not null,
  score integer not null,
  total integer not null,
  duration_ms integer,
  submitted_at timestamp with time zone default now() not null
);

-- 提出済みの解答（1問1行）。
create table public.attempt_answers (
  attempt_id uuid not null,
  question_id uuid not null,
  chosen text not null,
  is_correct boolean not null
);

-- 途中保存（下書き）。提出済みの記録とは別物で、提出できたら discard_drafts で捨てる。
-- client_seq は端末側の連番。遅れて届いた古い回答が新しい回答を消さないためのもの。
create table public.attempt_drafts (
  student_id uuid default auth.uid() not null,
  quiz_set_id uuid not null,
  question_id uuid not null,
  chosen text not null,
  client_seq bigint default 0 not null,
  updated_at timestamp with time zone default now() not null
);

-- 受験中に画面を離れた回数。個人の証拠には使わず、教師画面はクラス合計しか出さない。
create table public.attempt_focus (
  student_id uuid default auth.uid() not null,
  quiz_set_id uuid not null,
  away_count integer default 0 not null,
  away_ms bigint default 0 not null,
  updated_at timestamp with time zone default now() not null
);

-- アンケートの回答。質問の定義はDBに無く、src/assets/surveys.js の SURVEYS 配列が持つ。
-- survey_key がその配列の key と対応し、answers に回答が jsonb で入る。
-- ※ 一意制約が (student_id, survey_key) なので、再提出は上書きになる（履歴は残らない）。
create table public.survey_responses (
  id uuid default gen_random_uuid() not null,
  student_id uuid default auth.uid() not null,
  survey_key text not null,
  answers jsonb not null,
  submitted_at timestamp with time zone default now() not null
);


-- =============================================================================
-- 3. 制約
-- =============================================================================

-- profiles
alter table public.profiles add constraint profiles_pkey PRIMARY KEY (id);
alter table public.profiles add constraint profiles_student_no_key UNIQUE (student_no);
alter table public.profiles add constraint profiles_role_check CHECK ((role = ANY (ARRAY['student'::text, 'teacher'::text])));
alter table public.profiles add constraint profiles_id_fkey FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- quiz_sets
alter table public.quiz_sets add constraint quiz_sets_pkey PRIMARY KEY (id);

-- questions
alter table public.questions add constraint questions_pkey PRIMARY KEY (id);
alter table public.questions add constraint questions_quiz_set_id_seq_key UNIQUE (quiz_set_id, seq);
alter table public.questions add constraint questions_quiz_set_id_fkey FOREIGN KEY (quiz_set_id) REFERENCES quiz_sets(id) ON DELETE CASCADE;

-- question_answers
alter table public.question_answers add constraint question_answers_pkey PRIMARY KEY (question_id);
alter table public.question_answers add constraint question_answers_correct_check CHECK ((correct = ANY (ARRAY['a'::text, 'b'::text])));
alter table public.question_answers add constraint question_answers_question_id_fkey FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE;

-- attempts
alter table public.attempts add constraint attempts_pkey PRIMARY KEY (id);
alter table public.attempts add constraint attempts_student_id_fkey FOREIGN KEY (student_id) REFERENCES profiles(id) ON DELETE CASCADE;
alter table public.attempts add constraint attempts_quiz_set_id_fkey FOREIGN KEY (quiz_set_id) REFERENCES quiz_sets(id) ON DELETE CASCADE;

-- attempt_answers
alter table public.attempt_answers add constraint attempt_answers_pkey PRIMARY KEY (attempt_id, question_id);
alter table public.attempt_answers add constraint attempt_answers_chosen_check CHECK ((chosen = ANY (ARRAY['a'::text, 'b'::text])));
alter table public.attempt_answers add constraint attempt_answers_attempt_id_fkey FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE;
alter table public.attempt_answers add constraint attempt_answers_question_id_fkey FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE;

-- attempt_drafts（主キー=学生・回・設問。二重送信で行が増えない形）
alter table public.attempt_drafts add constraint attempt_drafts_pkey PRIMARY KEY (student_id, quiz_set_id, question_id);
alter table public.attempt_drafts add constraint attempt_drafts_chosen_check CHECK ((chosen = ANY (ARRAY['a'::text, 'b'::text])));
alter table public.attempt_drafts add constraint attempt_drafts_student_id_fkey FOREIGN KEY (student_id) REFERENCES profiles(id) ON DELETE CASCADE;
alter table public.attempt_drafts add constraint attempt_drafts_quiz_set_id_fkey FOREIGN KEY (quiz_set_id) REFERENCES quiz_sets(id) ON DELETE CASCADE;
alter table public.attempt_drafts add constraint attempt_drafts_question_id_fkey FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE;

-- attempt_focus
alter table public.attempt_focus add constraint attempt_focus_pkey PRIMARY KEY (student_id, quiz_set_id);
alter table public.attempt_focus add constraint attempt_focus_student_id_fkey FOREIGN KEY (student_id) REFERENCES profiles(id) ON DELETE CASCADE;
alter table public.attempt_focus add constraint attempt_focus_quiz_set_id_fkey FOREIGN KEY (quiz_set_id) REFERENCES quiz_sets(id) ON DELETE CASCADE;

-- survey_responses
alter table public.survey_responses add constraint survey_responses_pkey PRIMARY KEY (id);
alter table public.survey_responses add constraint survey_responses_student_id_survey_key_key UNIQUE (student_id, survey_key);
alter table public.survey_responses add constraint survey_responses_student_id_fkey FOREIGN KEY (student_id) REFERENCES profiles(id) ON DELETE CASCADE;


-- =============================================================================
-- 4. 索引（主キー・UNIQUE が自動で作るもの以外）
-- =============================================================================

CREATE INDEX attempt_drafts_by_set ON public.attempt_drafts USING btree (quiz_set_id, student_id);
CREATE INDEX attempt_focus_by_set ON public.attempt_focus USING btree (quiz_set_id);


-- =============================================================================
-- 5. 関数
--    ポリシーが app_hidden.is_teacher() を参照するので、ポリシーより先に作る。
-- =============================================================================

-- 教師かどうか。SECURITY DEFINER なので、profiles の RLS を貫いて判定できる。
CREATE OR REPLACE FUNCTION app_hidden.is_teacher()
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$ select exists(select 1 from profiles where id = auth.uid() and role = 'teacher') $function$;

-- 小テストの提出と採点。★採点は必ずここ（サーバー側）で行う。
-- クライアントで採点する形に変えない（正解を学生に送ることになるため）。
CREATE OR REPLACE FUNCTION public.submit_attempt(p_quiz_set_id uuid, p_answers jsonb, p_duration_ms integer DEFAULT NULL::integer)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_attempt_id uuid;
  v_score int := 0;
  v_total int;
  v_results jsonb := '[]'::jsonb;
  q record;
  v_chosen text;
begin
  if auth.uid() is null then raise exception 'not authenticated'; end if;
  if not exists(select 1 from quiz_sets where id = p_quiz_set_id and is_open) then
    raise exception 'quiz not open';
  end if;
  select count(*) into v_total from questions where quiz_set_id = p_quiz_set_id;
  insert into attempts(student_id, quiz_set_id, score, total, duration_ms)
    values (auth.uid(), p_quiz_set_id, 0, v_total, p_duration_ms) returning id into v_attempt_id;
  for q in
    select qq.id, qq.seq, qa.correct
    from questions qq join question_answers qa on qa.question_id = qq.id
    where qq.quiz_set_id = p_quiz_set_id order by qq.seq
  loop
    v_chosen := p_answers->>(q.id::text);
    if v_chosen is not null and v_chosen in ('a','b') then
      insert into attempt_answers(attempt_id, question_id, chosen, is_correct)
        values (v_attempt_id, q.id, v_chosen, v_chosen = q.correct);
      if v_chosen = q.correct then v_score := v_score + 1; end if;
      v_results := v_results || jsonb_build_object('seq', q.seq, 'chosen', v_chosen, 'correct', q.correct, 'is_correct', v_chosen = q.correct);
    else
      v_results := v_results || jsonb_build_object('seq', q.seq, 'chosen', null, 'correct', q.correct, 'is_correct', false);
    end if;
  end loop;
  update attempts set score = v_score where id = v_attempt_id;
  return jsonb_build_object('attempt_id', v_attempt_id, 'score', v_score, 'total', v_total, 'results', v_results);
end $function$;

-- 途中保存。端末側の client_seq が古い場合は書き込まない（遅れて届いた回答で上書きしない）。
CREATE OR REPLACE FUNCTION public.save_draft(p_quiz_set_id uuid, p_question_id uuid, p_chosen text, p_client_seq bigint DEFAULT 0)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
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

  if not exists (
    select 1 from public.questions q
     where q.id = p_question_id and q.quiz_set_id = p_quiz_set_id
  ) then
    raise exception 'question does not belong to this quiz set' using errcode = '22023';
  end if;

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
   where excluded.client_seq >= d.client_seq;

  select d.client_seq into v_seq
    from public.attempt_drafts d
   where d.student_id = v_student
     and d.quiz_set_id = p_quiz_set_id
     and d.question_id = p_question_id;

  return jsonb_build_object('ok', true, 'client_seq', coalesce(v_seq, 0));
end;
$function$;

-- 提出できたあとの片付け。自分の下書きしか消せない。
CREATE OR REPLACE FUNCTION public.discard_drafts(p_quiz_set_id uuid)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
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
$function$;

-- 受験中に画面を離れた回数の記録。大きい方を採る（戻ってきて再送されても減らない）。
CREATE OR REPLACE FUNCTION public.record_away(p_quiz_set_id uuid, p_away_count integer, p_away_ms bigint DEFAULT 0)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
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
$function$;

-- 教師画面の集計。関数の中で is_teacher() を検査するので、学生が呼んでも forbidden が返る。
CREATE OR REPLACE FUNCTION public.quiz_stats(p_quiz_set_id uuid)
 RETURNS jsonb
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
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
$function$;


-- =============================================================================
-- 6. RLS（行レベルセキュリティ）の有効化
--    ※ 表への grant は Supabase の既定で anon にも付く（下の 8 節）。
--       実際に守っているのは grant ではなく、この RLS とポリシー。
-- =============================================================================

alter table public.profiles          enable row level security;
alter table public.quiz_sets         enable row level security;
alter table public.questions         enable row level security;
alter table public.question_answers  enable row level security;
alter table public.attempts          enable row level security;
alter table public.attempt_answers   enable row level security;
alter table public.attempt_drafts    enable row level security;
alter table public.attempt_focus     enable row level security;
alter table public.survey_responses  enable row level security;


-- =============================================================================
-- 7. ポリシー
-- =============================================================================

-- profiles: 自分の行か、教師なら全員
create policy "read own or teacher" on public.profiles as permissive for select to authenticated
  using (((id = auth.uid()) OR app_hidden.is_teacher()));

-- quiz_sets: 公開中の回だけ。教師は全部
create policy "read open or teacher" on public.quiz_sets as permissive for select to authenticated
  using ((is_open OR app_hidden.is_teacher()));
create policy "teacher manage" on public.quiz_sets as permissive for all to authenticated
  using (app_hidden.is_teacher())
  with check (app_hidden.is_teacher());

-- questions: 公開中の回に属する設問だけ読める
create policy "read questions of open quiz" on public.questions as permissive for select to authenticated
  using (((EXISTS ( SELECT 1
   FROM quiz_sets s
  WHERE ((s.id = questions.quiz_set_id) AND s.is_open))) OR app_hidden.is_teacher()));
create policy "teacher read" on public.questions as permissive for select to authenticated
  using (app_hidden.is_teacher());
create policy "teacher manage" on public.questions as permissive for all to authenticated
  using (app_hidden.is_teacher())
  with check (app_hidden.is_teacher());

-- question_answers: 正解表。教師だけ
create policy "teacher only" on public.question_answers as permissive for all to authenticated
  using (app_hidden.is_teacher())
  with check (app_hidden.is_teacher());

-- attempts / attempt_answers: 自分の受験記録か、教師なら全員
create policy "read own or teacher" on public.attempts as permissive for select to authenticated
  using (((student_id = auth.uid()) OR app_hidden.is_teacher()));
create policy "read own or teacher" on public.attempt_answers as permissive for select to authenticated
  using ((EXISTS ( SELECT 1
   FROM attempts a
  WHERE ((a.id = attempt_answers.attempt_id) AND ((a.student_id = auth.uid()) OR app_hidden.is_teacher())))));

-- attempt_drafts / attempt_focus: 読むだけのポリシーしか作っていない。
-- 書き込みは RPC（save_draft / discard_drafts / record_away）経由のみ。
create policy "own drafts are readable" on public.attempt_drafts as permissive for select to public
  using ((student_id = auth.uid()));
create policy "teachers can read drafts" on public.attempt_drafts as permissive for select to public
  using (app_hidden.is_teacher());
create policy "own focus is readable" on public.attempt_focus as permissive for select to public
  using ((student_id = auth.uid()));
create policy "teachers can read focus" on public.attempt_focus as permissive for select to public
  using (app_hidden.is_teacher());

-- survey_responses: 自分の回答は入れられる・直せる・読める。教師は全員分を読める。
-- ※ delete のポリシーは無い＝学生は自分の回答を消せない（回答数を汚さないため）。
create policy "insert own" on public.survey_responses as permissive for insert to authenticated
  with check ((student_id = auth.uid()));
create policy "update own" on public.survey_responses as permissive for update to authenticated
  using ((student_id = auth.uid()))
  with check ((student_id = auth.uid()));
create policy "read own or teacher" on public.survey_responses as permissive for select to authenticated
  using (((student_id = auth.uid()) OR app_hidden.is_teacher()));


-- =============================================================================
-- 8. 権限
-- =============================================================================

-- 表への grant は Supabase の既定のまま（新しい表を作ると自動で付く形）。
-- anon にも付いているが、RLS のポリシーが1つも当たらないので実際には何も読めない。
grant delete, insert, references, select, trigger, truncate, update on table public.profiles         to anon, authenticated, service_role;
grant delete, insert, references, select, trigger, truncate, update on table public.quiz_sets        to anon, authenticated, service_role;
grant delete, insert, references, select, trigger, truncate, update on table public.questions        to anon, authenticated, service_role;
grant delete, insert, references, select, trigger, truncate, update on table public.question_answers to anon, authenticated, service_role;
grant delete, insert, references, select, trigger, truncate, update on table public.attempts         to anon, authenticated, service_role;
grant delete, insert, references, select, trigger, truncate, update on table public.attempt_answers  to anon, authenticated, service_role;
grant delete, insert, references, select, trigger, truncate, update on table public.attempt_drafts   to anon, authenticated, service_role;
grant delete, insert, references, select, trigger, truncate, update on table public.attempt_focus    to anon, authenticated, service_role;
grant delete, insert, references, select, trigger, truncate, update on table public.survey_responses to anon, authenticated, service_role;

-- 関数は既定のままだと anon にも execute が付く。★必ず revoke してから grant する。
-- （revoke all ... from public だけでは Supabase の既定権限で anon に付き直す）
revoke all on function public.submit_attempt(uuid, jsonb, integer) from public, anon;
grant execute on function public.submit_attempt(uuid, jsonb, integer) to authenticated, service_role;

revoke all on function public.save_draft(uuid, uuid, text, bigint) from public, anon;
grant execute on function public.save_draft(uuid, uuid, text, bigint) to authenticated, service_role;

revoke all on function public.discard_drafts(uuid) from public, anon;
grant execute on function public.discard_drafts(uuid) to authenticated, service_role;

revoke all on function public.record_away(uuid, integer, bigint) from public, anon;
grant execute on function public.record_away(uuid, integer, bigint) to authenticated, service_role;

revoke all on function public.quiz_stats(uuid) from public, anon;
grant execute on function public.quiz_stats(uuid) to authenticated, service_role;

-- is_teacher() だけは service_role にも与えない（2026-09-06 実測の通り）。
revoke all on function app_hidden.is_teacher() from public, anon, service_role;
grant execute on function app_hidden.is_teacher() to authenticated;


-- =============================================================================
-- 9. 書き出したときに気づいたこと（2026-09-06）
--    ※ ここはメモ。流しても何も起きない。
-- =============================================================================
--
-- (1) questions_public というビューは存在しない。
--     CLAUDE.md に「出題は questions_public ビュー」とあるが、実物は questions 表を
--     RLS ポリシー「read questions of open quiz」で絞る形。正解列は question_answers に
--     分離済みなので、学生に正解が渡らない仕組みそのものは効いている。
--     直すのは記述のほう（実装は変えなくてよい）。
--
-- (2) survey_responses の一意制約は (student_id, survey_key)。
--     つまり同じアンケートに再提出すると上書きで、前の回答は残らない。
--     毎月の推移を追う使い方（12月からの進路アンケート）をするなら、
--     対象月を持つ列を足して一意制約を張り替える必要がある。
--     ★運用が始まって回答が入ったあとだと移行が要る。始める前に決めること。
--
-- (3) profiles に学年の列が無い（class_name の文字列だけ）。
--     「1年生にだけアンケートを出す」といった学年での出し分けは、いまの構造では
--     クラス名から判定するしかない。
--
-- (4) 表への grant は anon にも付いているが、これは Supabase の既定で、
--     守っているのは RLS。ポリシーを消すと即座に穴が開く関係になっている。
-- =============================================================================
