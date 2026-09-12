-- =====================================================================
-- 実施回（quiz_runs）で開いた回の設問を、対象の学生が読めるようにする   2026-09-12
--
-- ■ 何が起きていたか
--   きあがスマホでデモを触って報告: 「もんだいが ありません。って赤字で出て終わった」。
--   調べたら、対象クラスの学生から見て
--     ・my_open_runs      … 1件見える（回は見えている）
--     ・questions の読取り … **0問**        ← ここ
--     ・教師から           … 440問（データはある）
--   ＝**「はじめる」で開いても、学生は設問を1問も読めない。**
--   4月の本丸である実施回が、学生側で機能していなかった。
--
-- ■ 原因（1か所だけ）
--   questions / question_choices の select ポリシーが **quiz_sets.is_open しか見ていない**。
--   実施回は「定義（is_open）は下書きのまま、回だけを時間で開く」という作りなので、
--   is_open は false のまま＝ポリシーに引っかからない。
--
--   ⚠ 誤解しやすいので明記する: **提出側は壊れていない。**
--     submit_attempt / save_draft は p_run_id が来れば app_hidden.assert_run_open で判定し、
--     来ないときだけ is_open を見る、という正しい作りになっていた。読取りだけが取り残されていた。
--
-- ■ なぜ検査をすり抜けたか
--   ブラウザ実操作テスト（run_e2e_quiz.py）は **is_open = true のデモ回**で往復している。
--   実施回で開いた回を学生が解く経路は、一度も通されていなかった。
--   → このファイルと一緒に tests/test_security.py に「実施回で開いた回を学生が読める」を足す。
--
-- ■ 直し方
--   「対象の自分に開いている実施回があるか」を返す関数を1つ足し、両方のポリシーに or で足す。
--   対象の判定は public.my_open_runs() と**同じ条件**にする（2か所で違う判定をしない）。
--
-- ■ 広げすぎていないことの確認
--   ・正解（question_answers）には触らない＝学生からは引き続き読めない
--   ・時間外（opens_at 前・closes_at 後）と取り消し済み（is_void）は false
--   ・対象クラス／対象学生に入っていなければ false
--   ・未ログイン（anon）は auth.uid() が null なので false
-- =====================================================================

begin;

-- 「いま自分に開いている実施回が、この回にあるか」
-- ★判定は public.my_open_runs() と同じ。片方だけ直すと、
--   「一覧には出るのに開けない」「出ないのに開ける」という食い違いが生まれる。
create or replace function app_hidden.has_open_run(p_quiz_set_id uuid)
returns boolean
language sql
stable security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1
      from public.quiz_runs r
     where r.quiz_set_id = p_quiz_set_id
       and auth.uid() is not null
       and not r.is_void
       and r.opens_at <= now() and now() < r.closes_at
       and (
         -- 対象を指定していない回＝全員が対象
         (coalesce(array_length(r.class_names, 1), 0) = 0
          and coalesce(array_length(r.student_ids, 1), 0) = 0)
         or auth.uid() = any (r.student_ids)
         or (select class_name from public.profiles where id = auth.uid()) = any (r.class_names)
       )
  )
$$;

revoke all     on function app_hidden.has_open_run(uuid) from public, anon, service_role;
grant  execute on function app_hidden.has_open_run(uuid) to authenticated;

-- ---- 設問 ----------------------------------------------------------
drop policy if exists "read questions of open quiz" on public.questions;
create policy "read questions of open quiz" on public.questions
  for select to authenticated
  using (
    exists (select 1 from public.quiz_sets s
             where s.id = questions.quiz_set_id and s.is_open)
    or app_hidden.has_open_run(questions.quiz_set_id)
    or app_hidden.is_teacher()
  );

-- ---- 選択肢 --------------------------------------------------------
-- 🔴 ここは**ポリシーの中に副問い合わせを書いてはいけない**。
--    ポリシーの条件式は、その中で触る表の RLS も受ける。
--    素直に `from questions q join quiz_sets s ...` と書くと、
--    **学生には下書きの quiz_sets 行が見えない**ので EXISTS が必ず偽になり、
--    選択肢が1つも読めない（＝画面は「もんだいが ありません」）。
--    2026-09-12 に一度この形で入れて、実際にそうなった。設問側が動いたのは
--    has_open_run（SECURITY DEFINER）を**直接**呼んでいて quiz_sets を経由しないため。
--    → 判定ごと SECURITY DEFINER の関数に包んで、RLS を経由しない形にする。
create or replace function app_hidden.can_read_question(p_question_id uuid)
returns boolean
language sql
stable security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1
      from public.questions q
      join public.quiz_sets  s on s.id = q.quiz_set_id
     where q.id = p_question_id
       and (s.is_open or app_hidden.has_open_run(s.id))
  )
$$;

revoke all     on function app_hidden.can_read_question(uuid) from public, anon, service_role;
grant  execute on function app_hidden.can_read_question(uuid) to authenticated;

drop policy if exists "read choices of open quiz" on public.question_choices;
create policy "read choices of open quiz" on public.question_choices
  for select to authenticated
  using (
    app_hidden.can_read_question(question_choices.question_id)
    or app_hidden.is_teacher()
  );

commit;

-- =====================================================================
-- 流したあとの確認
--   py -X utf8 tests\test_security.py        ← 「実施回で開いた回」の項目が増えている
--   py -X utf8 tests\run_e2e_quiz.py
--   実物: 先生の画面で「はじめる」→ 対象クラスの学生でログイン → 設問が出ること
--
-- 巻き戻し（★元の「is_open だけ見る」に戻す。実施回で開いた回は再び読めなくなる）
--   begin;
--   drop policy if exists "read questions of open quiz" on public.questions;
--   create policy "read questions of open quiz" on public.questions
--     for select to authenticated
--     using (exists (select 1 from public.quiz_sets s
--                     where s.id = questions.quiz_set_id and s.is_open)
--            or app_hidden.is_teacher());
--   drop policy if exists "read choices of open quiz" on public.question_choices;
--   create policy "read choices of open quiz" on public.question_choices
--     for select to authenticated
--     using (exists (select 1 from public.questions q
--                      join public.quiz_sets s on s.id = q.quiz_set_id
--                     where q.id = question_choices.question_id and s.is_open)
--            or app_hidden.is_teacher());
--   drop function if exists app_hidden.has_open_run(uuid);
--   commit;
-- =====================================================================
