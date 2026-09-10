-- =====================================================================
-- 登録した回を消す（回答が入っていないものだけ）  2026-09-11
--
-- ■ なぜ RPC が要るか（画面から DELETE すれば済む話ではない）
--   `attempts` の外部キーは **on delete cascade** で `quiz_sets` にぶら下がっている。
--   つまり **quiz_sets を1行消すと、その回の受験記録も一緒に消える。**
--   ★しかも **cascade は RLS を通らない**（システムが表の持ち主として実行するため）。
--   「学生は自分の回答を消せない」「取り消しても回答は消さない」と決めてあるのに、
--   教師が回を消しただけで回答が消える経路が開いてしまう。
--
--   画面側で「回答が0件なら消す」と書くこともできるが、**それは画面を信じる作り**になる。
--   数えてから消すまでの間に1件入れば、そのまま消える。
--   → **サーバー側で数えて、1件でもあれば例外にする。**
--
-- ■ 消せるもの・消せないもの
--   消せる   : 受験記録が1件も無い回（取り込みを間違えた・二重に登録した、の後始末）
--   消せない : 1件でも受験記録がある回 → 例外。**代わりに「停止」を使う**（is_open = false）
--   ★これは「取り消しは is_void で、回答は消さない」と同じ思想。
--     消す実装を**作らない**のではなく、**消してよい範囲だけに閉じる**。
--
-- ■ 一緒に消えるもの（回答が無い前提なので、どれも失って困らない）
--   questions → question_choices / question_answers / quiz_set_questions（すべて cascade）
--   quiz_runs（cascade）。★受験記録が無いので、実施の記録としても中身が無い
--
-- ■ このファイルの性質
--   関数を1つ足すだけ。既存の表・列・制約には触らない。
-- =====================================================================

begin;

create or replace function public.delete_quiz_set(p_quiz_set_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_title text;
  v_attempts integer;
  v_questions integer;
begin
  if not app_hidden.is_teacher() then
    raise exception 'forbidden' using errcode = '42501';
  end if;

  select title into v_title from public.quiz_sets where id = p_quiz_set_id;
  if v_title is null then
    raise exception 'no such quiz set' using errcode = '22023';
  end if;

  -- 🔴 ここが本体。1件でも受験記録があれば消さない。
  select count(*) into v_attempts from public.attempts where quiz_set_id = p_quiz_set_id;
  if v_attempts > 0 then
    raise exception '受験記録が % 件あるので消せません（停止にしてください）', v_attempts
      using errcode = '23503';
  end if;

  select count(*) into v_questions from public.questions where quiz_set_id = p_quiz_set_id;

  delete from public.quiz_sets where id = p_quiz_set_id;

  return jsonb_build_object('ok', true, 'title', v_title, 'questions', v_questions);
end $$;

revoke all on function public.delete_quiz_set(uuid) from public;
revoke execute on function public.delete_quiz_set(uuid) from anon;
grant execute on function public.delete_quiz_set(uuid) to authenticated;

commit;


-- =====================================================================
-- 流したあとの確認
--   py -X utf8 tests\test_security.py
--   py -X utf8 -m unittest discover -s tests -p "test_db_migrations.py"
--   py -X utf8 tests\run_e2e_qsets_import.py
--     → 「★ダミーを消せた」がこの関数経由で通ること
--
--   ⚠ 許容WARN が 11件 → 12件 になる（public の RPC が1本増えるため）。
--     CLAUDE.md の一覧に delete_quiz_set を書き足してから基準を上げること。
--
-- 巻き戻し
--   begin;
--   drop function if exists public.delete_quiz_set(uuid);
--   commit;
--   ※ 表も列も足していないので、これで完全に元へ戻る。
-- =====================================================================
