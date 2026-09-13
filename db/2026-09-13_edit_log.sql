-- 2026-09-13  だれが・いつ・どの回を変えたかを残す（きあ依頼）
--
-- ■ なぜ要るか（きあの言葉）
--   「やはりこちらが正本なのだから、マスターを持っている人には編集権を与えたいね。
--     だれがいつ変更したかの変更履歴は取りたい。
--     まぁ、正本をだれかが触って、問題のDBが壊れる可能性もあるが…それは仕方ないね」
--   ＝ 編集できる人を増やす以上、**あとから追える**ようにしておく。
--
-- ■ なぜ「トリガで行単位」ではなく「アプリから1操作1行」なのか
--   行単位のトリガ（questions / question_choices / question_answers に after update）も考えた。
--   やめた理由が2つある:
--     ① 🔴 **本番を壊す側になりうる。** after トリガの中で例外が出ると、
--        元の書き込みごと巻き戻る。履歴の不具合で**学生が提出できなくなる**のは割に合わない。
--     ② 読めない。1回ぶんの編集で数十行出る。知りたいのは
--        「だれが・いつ・どの回を・どう変えたか」の1行であって、列ごとの差分ではない。
--   ★そのかわり **Supabase の画面から直接いじった分は残らない**。
--     そこを触れるのは管理者だけなので、いまは許容する（CLAUDE.md にも書いた）。
--     復元そのものは「Excelに書き出す」が受け持つ（同じ日に入れた）。
--
-- ■ 消えた回の履歴も残す
--   quiz_set_id に外部キーを張らない。張ると回を消したときに
--   **「誰が消したか」の記録ごと消える**。題名も一緒に持っておく。

-- ★このリポの決まり: 移行SQLはトランザクションで囲む（tests/test_db_migrations.py が見ている）
begin;

create table if not exists public.quiz_edit_log (
  id             bigint generated always as identity primary key,
  at             timestamptz not null default now(),
  actor_id       uuid        not null default auth.uid(),
  quiz_set_id    uuid,                       -- ★あえて外部キーを張らない（上の理由）
  quiz_set_title text        not null,
  action         text        not null,
  summary        text        not null,       -- 画面にそのまま出す1行
  detail         jsonb                       -- 直した/足した/消した 問題番号など
);

-- ★本文は入れない。入れるのは問題番号と件数まで（表がむやみに太らないように）
comment on column public.quiz_edit_log.detail is
  '問題番号と件数だけ。設問の本文は入れない（2026-09-13）';

alter table public.quiz_edit_log drop constraint if exists quiz_edit_log_action_check;
alter table public.quiz_edit_log add constraint quiz_edit_log_action_check
  check (action in ('import', 'edit', 'publish', 'unpublish', 'delete_set', 'export'));

create index if not exists quiz_edit_log_at_idx      on public.quiz_edit_log (at desc);
create index if not exists quiz_edit_log_set_idx     on public.quiz_edit_log (quiz_set_id, at desc);

alter table public.quiz_edit_log enable row level security;

-- 読めるのは先生とマスターだけ（app_hidden.is_teacher() は 'teacher' と 'master' の両方が真）
drop policy if exists "teacher read edit log" on public.quiz_edit_log;
create policy "teacher read edit log"
  on public.quiz_edit_log for select to authenticated
  using (app_hidden.is_teacher());

-- 書けるのも先生とマスター。★ただし **自分の名前でしか書けない**
--   （actor_id を他人にして残す、ができないようにする）
drop policy if exists "teacher write edit log" on public.quiz_edit_log;
create policy "teacher write edit log"
  on public.quiz_edit_log for insert to authenticated
  with check (app_hidden.is_teacher() and actor_id = auth.uid());

-- 🔴 直せない・消せない。ポリシーを書かない＝ update / delete は誰にも許されない。
--    履歴を後から書き換えられるなら、履歴を取る意味がない。

grant select, insert on table public.quiz_edit_log to authenticated;
revoke all on table public.quiz_edit_log from anon;

commit;
