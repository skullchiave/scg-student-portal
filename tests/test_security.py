# -*- coding: utf-8 -*-
"""セキュリティ回帰テスト — scg-student-portal

「安全性の担保」を毎回機械的に再検証するためのテスト。スキーマやポリシーを
変更したら必ず実行すること。全部 PASS しない状態でデプロイしてはいけない。

このリポで一番重い検査なので、既定でskipにはしない：
  - 単体で実行     … python tests/test_security.py
                      → 引数なしでも常に本物のDBを叩く（従来どおり）
  - discoverで実行 … py -X utf8 -m unittest discover -s tests -p "test_*.py"
                      → 既定ではskip（他のテストに巻き込んで落とさないため）。
                        本気で回すには環境変数 SP_LIVE=1 を付ける
  DBに接続できない環境（ネットワークが無い等）では、live扱いのときも
  自動的にskipへ倒れる（FAILにはしない）。

使い方: python tests/test_security.py
依存:   標準ライブラリのみ
"""
import sys, os, re, json, io, subprocess, unittest
import urllib.request
import urllib.error
import urllib.parse

# discoverで他のtest_*.pyと同じプロセスに同居する時、全員が無条件に
# sys.stdout を包み直すと、先に包んだ方のラッパーがGCで下敷きのbufferを
# 道連れに閉じてしまい "I/O operation on closed file" になる。
# すでにutf-8ならそのまま使う（-X utf8 実行なら通常ここに来る）。
if getattr(sys.stdout, "encoding", "").lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_creds import get_teacher_no, get_teacher_pw, get_student_no, get_student_pw, NO_ENV_MSG

BASE = "https://egdcbxzpgwenmfabpodd.supabase.co"
ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVnZGNieHpwZ3dlbm1mYWJwb2RkIiwi"
        "cm9sZSI6ImFub24iLCJpYXQiOjE3ODgzNTcwNDYsImV4cCI6MjEwMzkzMzA0Nn0.m908C67Nh4KsYnH_LWvP4wAjOtxI79hhE-BKS1MCxX0")
QUIZ_SET = "c75def6b-7623-4d86-8540-0c5b081ecf7c"

# 単体実行(__main__)なら引数なしでも必ずlive。discover経由は SP_LIVE=1 か --live が要る。
RUN_LIVE = (__name__ == "__main__") or os.environ.get("SP_LIVE") == "1" or "--live" in sys.argv


def req(path, token=None, body=None, extra=None, method=None):
    """method を省くと、body があれば POST・無ければ GET（従来どおり）。
    ★PATCH/DELETE を使うときだけ明示する。X-HTTP-Method-Override は効かない（2026-09-12 実測）。"""
    headers = {"apikey": ANON, "Content-Type": "application/json"}
    if extra: headers.update(extra)
    if token: headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=20) as res:
            return res.status, json.loads(res.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "null")


def login(no, pw):
    st, body = req("/auth/v1/token?grant_type=password",
                   body={"email": f"{no}@stu.scg-portal.jp", "password": pw})
    return body.get("access_token") if st == 200 else None


@unittest.skipUnless(RUN_LIVE, "discover実行時は既定でskip。単体実行(python tests/test_security.py)か SP_LIVE=1 で有効化")
class TestSecurity(unittest.TestCase):
    """本物のDB（デモ環境）を実際に叩いて安全性を検証する"""

    @classmethod
    def setUpClass(cls):
        cls.s_no, cls.s_pw = get_student_no(), get_student_pw()
        cls.t_no, cls.t_pw = get_teacher_no(), get_teacher_pw()
        if not all((cls.s_no, cls.s_pw, cls.t_no, cls.t_pw)):
            raise unittest.SkipTest(NO_ENV_MSG)
        try:
            cls.stok = login(cls.s_no, cls.s_pw)
            cls.ttok = login(cls.t_no, cls.t_pw)
        except (urllib.error.URLError, OSError) as e:
            raise unittest.SkipTest(f"DBに接続できないためskip（{e}）")

    def check(self, name, cond, detail=""):
        print(("  ✅ " if cond else "  ❌ ") + name + (f"  ({detail})" if detail and not cond else ""))
        with self.subTest(name=name):
            self.assertTrue(cond, detail or name)

    def _require_tokens(self):
        if not self.stok or not self.ttok:
            self.skipTest("前提のログインが崩れているため中断（test_00_loginを確認）")

    def test_00_login(self):
        print("\n=== 0. 前提: ログイン ===")
        self.check("学生ログインできる", self.stok is not None)
        self.check("教師ログインできる", self.ttok is not None)

    def test_01_auth(self):
        self._require_tokens()
        print("\n=== 1. 認証まわり ===")
        self.check("誤ったパスワードは拒否される", login(self.s_no, "wrong-pass") is None)
        st, _ = req("/rest/v1/quiz_sets?select=id")
        self.check("未ログインではデータを読めない", st in (200, 401) and (st == 401 or _ == []))

    def test_02_answer_isolation(self):
        self._require_tokens()
        print("\n=== 2. 正解データの遮断（正解は question_answers テーブルに分離されている） ===")
        st, body = req("/rest/v1/question_answers?select=*", self.stok)
        self.check("学生は question_answers(正解テーブル)を読めない", body == [])
        st, body = req("/rest/v1/questions?select=*&limit=1", self.stok)
        self.check("学生は questions(問題文)を読める", st == 200 and len(body) == 1)
        self.check("questions に正解列が存在しない（構造で保証）", body and "correct" not in body[0])
        st, body = req("/rest/v1/question_answers?select=*", self.ttok)
        self.check("教師は question_answers を読める", st == 200 and len(body) > 0)

    def test_03_stats_api(self):
        self._require_tokens()
        print("\n=== 3. 集計APIの権限 ===")
        st, body = req("/rest/v1/rpc/quiz_stats", self.stok, {"p_quiz_set_id": QUIZ_SET})
        self.check("学生は quiz_stats を呼べない(forbidden)", isinstance(body, dict) and body.get("error") == "forbidden")
        st, body = req("/rest/v1/rpc/quiz_stats", self.ttok, {"p_quiz_set_id": QUIZ_SET})
        self.check("教師は quiz_stats を呼べる", isinstance(body, dict) and "attempts" in body)

    def test_04_scoring(self):
        self._require_tokens()
        print("\n=== 4. 採点の正しさ（正解は1番目/2番目が半々＝全問「1番目」なら5/10） ===")
        # ★2026-09-06 に選択肢が2個固定でなくなり、答えは 'a'/'b' から「何番目か」へ変わった
        # 🔴 この検査は以前「検査用の回が公開中のままである」ことを当てにしていた。
        #    2026-09-12、きあがデモを触って「停止」を押した結果、コードは正しいのに落ちた。
        #    ＝**誰かが画面でボタンを押したら落ちる検査**になっていた。
        #    → 自分で開けて、終わったら元の状態へ戻す（他の検査と同じ流儀）。
        st, before = req(f"/rest/v1/quiz_sets?select=is_open&id=eq.{QUIZ_SET}", self.ttok)
        was_open = bool(before[0]["is_open"]) if isinstance(before, list) and before else None
        self.check("検査用の回の状態が読める", was_open is not None, str(before)[:80])
        if was_open is None:
            return
        if not was_open:
            req(f"/rest/v1/quiz_sets?id=eq.{QUIZ_SET}", self.ttok, {"is_open": True},
                method="PATCH")
        try:
            st, qs = req(f"/rest/v1/questions?select=id&quiz_set_id=eq.{QUIZ_SET}", self.stok)
            st, r = req("/rest/v1/rpc/submit_attempt", self.stok,
                        {"p_quiz_set_id": QUIZ_SET, "p_answers": {q["id"]: 1 for q in qs}})
            self.check("採点が正しい（全問「1番目」提出=5/10）",
                       isinstance(r, dict) and r.get("score") == 5 and r.get("total") == 10,
                       str(r)[:120])
            # 範囲外の番号は「未回答」扱いにする（1問の壊れた値で提出全体を落とさない）
            st, r2 = req("/rest/v1/rpc/submit_attempt", self.stok,
                         {"p_quiz_set_id": QUIZ_SET, "p_answers": {q["id"]: 99 for q in qs}})
            self.check("範囲外の番号は未回答あつかい（提出そのものは通る）",
                       isinstance(r2, dict) and r2.get("score") == 0 and r2.get("total") == 10,
                       str(r2)[:80])
        finally:
            # ★元に戻す。検査が環境の状態を変えたままにしない
            if not was_open:
                req(f"/rest/v1/quiz_sets?id=eq.{QUIZ_SET}", self.ttok, {"is_open": False},
                    method="PATCH")

    def test_05_attempts_isolation(self):
        self._require_tokens()
        print("\n=== 5. 他人の解答は見えない ===")
        st, mine = req("/rest/v1/attempts?select=student_id", self.stok)
        uids = {a["student_id"] for a in mine} if isinstance(mine, list) else set()
        self.check("学生のattempts一覧に自分以外が混ざらない", len(uids) <= 1)

    def test_06_write_protection(self):
        self._require_tokens()
        print("\n=== 6. 書き込みの直接改ざん防止 ===")
        st, _ = req("/rest/v1/attempts", self.stok, {"quiz_set_id": QUIZ_SET, "score": 10, "total": 10,
                                                       "student_id": "00000000-0000-0000-0000-000000000000"})
        self.check("学生は attempts に直接insertできない（満点偽造不可）", st in (401, 403))

    def test_07_surveys(self):
        self._require_tokens()
        print("\n=== 7. アンケート（survey_responses） ===")
        UP = {"Prefer": "resolution=merge-duplicates"}
        # ★2026-09-11 の月次化（段階2）以降、一意は (student_id, round_id)。
        #   検査専用の回（survey_key='test_ui' / 題名「検査用」）へ出す＝毎回そこへ上書きされ、行が増えない。
        # ⚠ URL に日本語をそのまま入れると urllib が ascii で送ろうとして落ちる。必ず quote する
        st, rounds = req("/rest/v1/survey_rounds?select=id&survey_key=eq.test_ui&title=eq."
                         + urllib.parse.quote("検査用"), self.stok)
        rid = rounds[0]["id"] if isinstance(rounds, list) and rounds else None
        self.check("検査用の回が読める（学生は自分に開いている回を見られる）", bool(rid), str(rounds)[:120])
        st, _ = req("/rest/v1/survey_responses?on_conflict=student_id,round_id", self.stok,
                    {"round_id": rid, "survey_key": "test_ui", "answers": {"job": "テスト"}}, UP)
        self.check("学生はアンケートを提出できる（本人扱いで保存）", st in (200, 201), str(st))
        st, _ = req("/rest/v1/survey_responses", self.stok,
                    {"student_id": "00000000-0000-0000-0000-000000000000",
                     "survey_key": "test_rls_fake", "answers": {}})
        self.check("学生は他人名義でアンケートを出せない", st in (401, 403))
        # ★別の学生であることが要件なので番号は変える。パスワードは同じ枠のデモ全員に共通（.env の SP_STUDENT_PW）
        st2tok = login("s002", self.s_pw)
        st, rows = req("/rest/v1/survey_responses?select=student_id&survey_key=eq.test_ui", st2tok)
        self.check("学生は他人のアンケート回答を読めない", rows == [], str(rows)[:120])
        st, rows = req("/rest/v1/survey_responses?select=student_id&survey_key=eq.test_ui", self.ttok)
        self.check("教師は全員のアンケート回答を読める", isinstance(rows, list) and len(rows) >= 1)

    def test_08_open_run_reading(self):
        """実施回（はじめる）で開いた回を、対象の学生が読めること／対象外は読めないこと。

        🔴 **ここが無かったせいで、4月の本丸が壊れたまま通っていた**（2026-09-12）。
        きあがスマホで触って「もんだいが ありません」と報告。調べたら、
        questions / question_choices の select ポリシーが **quiz_sets.is_open しか見ておらず**、
        実施回で開いた回（is_open は false のまま）の設問が**1問も読めなかった**。

        ★なぜ検査をすり抜けたか＝ブラウザ実操作テストが **is_open=true のデモ回**しか通っておらず、
          「実施回で開いた回を学生が解く」経路が一度も通されていなかった。
          <u>作った機能の経路を1本も通していない検査は、通っていないのと同じ</u>。

        この検査は**自分で回を開き、最後に必ず取り消す**（残骸を溜めない）。
        """
        self._require_tokens()
        print("\n=== 8. 実施回（はじめる）で開いた回 ===")

        # 学生のクラスを調べ、そのクラス宛に短い回を開く
        st, me = req("/rest/v1/profiles?select=id,class_name", self.stok)
        cls = me[0]["class_name"] if isinstance(me, list) and me else None
        self.check("学生のクラスが取れる", bool(cls), str(me)[:120])
        if not cls:
            return

        # 下書き（is_open=false）の回を1つ借りる。無ければ作らずに skip
        # ⚠ 埋め込みは外部キーを名指しする。quiz_sets→questions の経路が2本あるため
        #   （quiz_set_questions 経由が増えた）。名指ししないと HTTP 300 になる
        st, sets = req("/rest/v1/quiz_sets?select=id,title,questions!questions_quiz_set_id_fkey(count)"
                       "&is_open=eq.false&limit=20", self.ttok)
        target = None
        for s in (sets or []):
            if not isinstance(s, dict):
                continue
            n = s.get("questions")
            if isinstance(n, list) and n and n[0].get("count", 0) > 0:
                target = s
                break
        if not target:
            self.skipTest("設問のある下書きの回が無いのでskip")

        st, r = req("/rest/v1/rpc/start_quiz_run", self.ttok,
                    {"p_quiz_set_id": target["id"], "p_class_names": [cls], "p_duration_min": 1})
        run_id = r.get("run_id") if isinstance(r, dict) else None
        self.check("教師は実施回をはじめられる", bool(run_id), str(r)[:140])
        if not run_id:
            return

        try:
            # 🔴 **学生画面が実際に投げるURLで確かめる**（select=id だけでは足りない）。
            #    2026-09-12、設問は読めるのに**選択肢だけ読めない**状態を作ってしまい、
            #    画面には「もんだいが ありません」と出た（選択肢が2つ未満の設問は出さない作りのため）。
            #    ＝「設問が読めるか」だけを見る検査は、この壊れ方を通してしまう。
            qurl = ("/rest/v1/questions?select=id,seq,prompt,question_choices(idx,label)"
                    "&quiz_set_id=eq." + target["id"] + "&order=seq")
            st, rows = req(qurl, self.stok)
            self.check("★対象クラスの学生は、実施回で開いた回の設問を読める",
                       isinstance(rows, list) and len(rows) > 0, str(rows)[:120])
            withch = sum(1 for q in (rows or []) if q.get("question_choices"))
            self.check("★選択肢も一緒に取れる（ここが欠けると画面は「もんだいが ありません」になる）",
                       withch == len(rows or []) and withch > 0,
                       f"選択肢が付いた設問 {withch}/{len(rows or [])}")

            # 広げすぎていないこと
            st, rows = req("/rest/v1/question_answers?select=question_id&limit=5", self.stok)
            self.check("★正解は読めないまま（ここが緩んだら致命的）", rows == [], str(rows)[:120])

            st, rows = req(qurl)      # 未ログイン
            self.check("未ログインでは読めない", rows == [] or st in (401, 403), str(rows)[:120])

            # 対象外のクラスの学生
            st, others = req("/rest/v1/profiles?select=student_no&class_name=neq."
                             + urllib.parse.quote(cls) + "&limit=1", self.ttok)
            if isinstance(others, list) and others:
                otok = login(others[0]["student_no"], self.s_pw)
                st, rows = req(qurl, otok)
                self.check("★対象外のクラスの学生は読めない", rows == [], str(rows)[:120])
        finally:
            # ★必ず片付ける。「消せないものは溜めない」——回は取り消しで無効にできる
            req("/rest/v1/rpc/void_quiz_run", self.ttok, {"p_run_id": run_id})

        st, rows = req("/rest/v1/questions?select=id&quiz_set_id=eq." + target["id"] + "&limit=5",
                       self.stok)
        self.check("★取り消したら、もう読めない", rows == [], str(rows)[:120])


class TestNoLeakedCredentials(unittest.TestCase):
    """★(2026-09-12) 消したはずの平文パスワードが追跡ファイルに戻ってきていないかを機械で見る。

    DB不要・常に実行（discoverでもskipしない）。理由: このリポは public で、
    以前は11ファイルにデモの平文パスワードが直書きされていた（教材1,686問を入れた日に発覚）。
    「塞いだ」を毎回機械で確かめるための見張り。

    🔴 比較対象そのもの（旧パスワード）は、このファイルにも書かない。
       書いてしまうと grep で拾える形になり、「消した」ことにならないため。
       突き合わせは平文どうしの比較ではなく SHA-256 のハッシュで行う
       （旧パスワードのハッシュ値だけをここに置く。ハッシュから元の文字列は再現できない）。
    """

    # 2026-09-12 に塞いだ旧デモパスワード2件（学生用・教師用）のSHA-256。値そのものはここに置かない。
    _OLD_PW_SHA256 = {
        "ce078c92012a413a7c0cd95080954a2411299ac8446748bdd12db6e2680c4618",
        "cd781ee2b954aaaa0f3644f269771c0a27b14a406073525aaee232326df4b9a5",
    }
    _TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{5,40}")
    _JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def check(self, name, cond, detail=""):
        print(("  ✅ " if cond else "  ❌ ") + name + (f"  ({detail})" if detail and not cond else ""))
        with self.subTest(name=name):
            self.assertTrue(cond, detail or name)

    @classmethod
    def setUpClass(cls):
        # git管理下のファイルだけを見る（.env・tmp/・scratch/等は最初から対象外＝.gitignore済み）
        out = subprocess.run(["git", "ls-files"], cwd=cls._ROOT, capture_output=True, text=True)
        cls._files = [os.path.join(cls._ROOT, p) for p in out.stdout.splitlines() if p.strip()]

    def _read(self, path):
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                return f.read()
        except OSError:
            return ""

    def test_01_old_passwords_gone(self):
        import hashlib
        print("=== 資格情報の見張り（追跡ファイル・DB不要）===")
        hits = []
        for path in self._files:
            text = self._read(path)
            if not text:
                continue
            for tok in set(self._TOKEN_RE.findall(text)):
                if hashlib.sha256(tok.encode()).hexdigest() in self._OLD_PW_SHA256:
                    hits.append(os.path.relpath(path, self._ROOT))
                    break
        self.check("旧デモパスワードの文字列が追跡ファイルに1つも無い", not hits, ",".join(hits[:5]))

    def test_02_no_service_role_key(self):
        import base64
        hits = []
        for path in self._files:
            text = self._read(path)
            if "eyJ" not in text:
                continue
            for tok in self._JWT_RE.findall(text):
                parts = tok.split(".")
                if len(parts) < 2:
                    continue
                padded = parts[1] + "=" * (-len(parts[1]) % 4)
                try:
                    payload = json.loads(base64.urlsafe_b64decode(padded))
                except Exception:
                    continue
                if isinstance(payload, dict) and payload.get("role") == "service_role":
                    hits.append(os.path.relpath(path, self._ROOT))
        self.check("service_role の鍵（JWTのroleがservice_role）が追跡ファイルに無い", not hits, ",".join(hits[:5]))


if __name__ == "__main__":
    if "--live" in sys.argv:
        sys.argv.remove("--live")
    unittest.main(verbosity=2)
