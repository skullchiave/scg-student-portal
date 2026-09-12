-- =====================================================================
-- 役割を3つにする（学生／先生／マスター）                        2026-09-12
--
-- ■ なぜ（きあ提案）
--   「マスターを新設した方がいい気がしている。
--     アンケートの回答一覧、アンケート作成、テストの登録・公開（実施ではないよ）、
--     お知らせ配信、点検バックアップ ── ここらへんはすべて、先生画面ではいらないよね」
--   → 画面を3つに分ける:
--       学生ポータル（学生用）        src/index.html
--       学生ポータル for 先生          src/teacher.html   ← 授業中に使うものだけ。新しく小さく作る
--       学生ポータル マスター          src/master.html    ← いまの teacher.html がこれになる
--     アカウントも s001〜 / t001〜 / m001〜 と分ける（★IDを見た瞬間に役割が分かる）
--
-- ■ このファイルでやること（画面の話ではなく、土台だけ）
--   ① profiles.role に 'master' を足す（いまの CHECK は student/teacher しか許していない）
--   ② app_hidden.is_teacher() を **master も通す**ようにする
--   ③ app_hidden.is_master() を足す（画面の出し分けと、今後の権限分けのため）
--
-- ■ 🔴 ここがいちばん大事な判断
--   is_teacher() は **18のポリシーと8つの関数**から呼ばれている。
--   master を通さないと、マスターは何も読めず何も書けなくなる。
--   かといって18か所を今すぐ書き換えるのは危ない（1つ落とすと静かに権限が消える）。
--   → **is_teacher() の意味を「職員（先生またはマスター）」に広げる**。名前は変えない。
--     ⚠ 名前と中身がずれるので、ここと CLAUDE.md に必ず書いておく。
--     「先生にはできないが、マスターにはできる」を作るのは **is_master() を使う側**の仕事。
--     いまは権限を分けない（＝画面だけ分ける）。分けるのは「先生ごとのアカウント」と同時。
--
-- ■ 今は誰の権限も減らない
--   既存の teacher はそのまま。master は teacher と同じところまで触れる。
--   ＝この SQL だけでは**何も壊れない**。壊れうるのは、あとで権限を分けるときだけ。
-- =====================================================================

begin;

-- ① 'master' を許す
alter table public.profiles drop constraint if exists profiles_role_check;
alter table public.profiles add  constraint profiles_role_check
  check (role in ('student', 'teacher', 'master'));

-- ② 職員（先生 or マスター）か
--    ★名前は is_teacher のまま＝18のポリシーを書き換えない。中身の意味だけ広げる。
create or replace function app_hidden.is_teacher()
returns boolean
language sql
stable security definer
set search_path = public, pg_temp
as $$
  -- 「先生か」ではなく「**職員か**」。master も通す（2026-09-12）。
  -- 先生とマスターで分けたいところは is_master() を使うこと。
  select exists (
    select 1 from public.profiles
     where id = auth.uid() and role in ('teacher', 'master')
  )
$$;

-- ★ create or replace では前の grant がそのまま残るが、明示的に張り直す
--   （検査 tests/test_db_migrations.py が「app_hidden のヘルパーは anon から呼べない」を見ている。
--     書いてあるかどうかで判定するので、置き換え でも必ず書くこと）
revoke all     on function app_hidden.is_teacher() from public, anon, service_role;
grant  execute on function app_hidden.is_teacher() to authenticated;

-- ③ マスターか（画面の出し分け・今後の権限分け用）
create or replace function app_hidden.is_master()
returns boolean
language sql
stable security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1 from public.profiles where id = auth.uid() and role = 'master'
  )
$$;

revoke all     on function app_hidden.is_master() from public, anon, service_role;
grant  execute on function app_hidden.is_master() to authenticated;

-- ④ 画面が「自分は何者か」を聞くための窓口（profiles は本人の行しか読めないので、それで足りる）
--    ★画面の出し分けにしか使わない。**これで権限を守っているわけではない**。
create or replace function public.my_role()
returns text
language sql
stable security definer
set search_path = public, pg_temp
as $$ select role from public.profiles where id = auth.uid() $$;

revoke all     on function public.my_role() from public;
revoke execute on function public.my_role() from anon;
grant  execute on function public.my_role() to authenticated;

commit;

-- =====================================================================
-- 流したあとの確認
--   select role, count(*) from public.profiles group by role;
--   py -X utf8 tests\test_security.py     ← 既存の権限が1つも変わっていないこと
--
-- 巻き戻し（★'master' の人がいると CHECK を戻せない。先に role を teacher へ直すこと）
--   begin;
--   update public.profiles set role = 'teacher' where role = 'master';
--   alter table public.profiles drop constraint if exists profiles_role_check;
--   alter table public.profiles add  constraint profiles_role_check
--     check (role in ('student', 'teacher'));
--   create or replace function app_hidden.is_teacher() returns boolean
--     language sql stable security definer set search_path = public, pg_temp
--     as $$ select exists(select 1 from profiles where id = auth.uid() and role = 'teacher') $$;
--   drop function if exists app_hidden.is_master();
--   drop function if exists public.my_role();
--   commit;
-- =====================================================================
