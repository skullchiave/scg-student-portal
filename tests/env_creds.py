# -*- coding: utf-8 -*-
"""デモアカウントの資格情報を .env / 環境変数から読む共通ヘルパー — scg-student-portal

★なぜ要るか（2026-09-12）: このリポは public。以前はデモ用ログインのパスワードを
  テスト・スクリプト11ファイルに平文で直書きしていた。教材1,686問を入れた今、
  直書きは「リポを読めば誰でも先生としてログインし、教材と正解を全部読める」に直結する。
  読む口をここ1つに絞り、以後の変更はここだけで済むようにする。

読む順番: 環境変数が先（CI・自動実行で渡せるように） → 無ければリポ直下の .env。
どちらにも無ければ None を返す（例外にしない・フォールバックの既定値は絶対に作らない。
「無ければ旧パスワードを使う」は塞いだことにならないため）。

呼び出し側（tests/*.py・scripts/*.py・tests/run_e2e_*.py）は、資格情報が None なら
skip（テスト）／エラーを出して終了（スクリプト・ブラウザ実操作）にすること。
🔴 このファイル自身にも、旧パスワード・新パスワードのどちらも書き写さない。
"""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_PATH = os.path.join(_ROOT, ".env")
_dotenv_cache = None


def _load_dotenv():
    """.env を簡易パースして dict にする（外部ライブラリ不要）。無ければ空dict。"""
    global _dotenv_cache
    if _dotenv_cache is not None:
        return _dotenv_cache
    values = {}
    if os.path.exists(_ENV_PATH):
        with open(_ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                values[k] = v
    _dotenv_cache = values
    return values


def get(key):
    """環境変数 → .env の順に探す。無ければ None。"""
    v = os.environ.get(key)
    if v:
        return v
    return _load_dotenv().get(key) or None


def get_teacher_no():
    return get("SP_TEACHER_NO")


def get_teacher_pw():
    return get("SP_TEACHER_PW")


def get_master_no():
    return get("SP_MASTER_NO")


def get_master_pw():
    """マスター（m001〜）。2026-09-12 に画面を3つに分けたときに増えた。
    ★master.html は先生を断るので、あちらを操作する検査はこちらを使うこと。"""
    return get("SP_MASTER_PW")


def get_student_no():
    return get("SP_STUDENT_NO")


def get_student_pw():
    return get("SP_STUDENT_PW")


NO_ENV_MSG = ".env が無いので飛ばしました（.env.example を見てください）"


def write_e2e_creds_js(path):
    """tests/e2e_*.html が読む window.__E2E_CREDS を tmp/ に書き出す（file:// では .env を直接読めないため）。

    値は .env からしか来ない。鍵が無ければその項目は None のまま書く
    （HTML側が「資格情報が読めません」で気づいて止まる。黙って空文字にはしない）。
    戻り値の dict で、呼び出し側（run_e2e_*.py）が必要な鍵の有無を確認できる。
    """
    import json
    creds = {
        "teacherNo": get_teacher_no(),
        "teacherPw": get_teacher_pw(),
        "masterNo": get_master_no(),
        "masterPw": get_master_pw(),
        "studentNo": get_student_no(),
        "studentPw": get_student_pw(),
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("window.__E2E_CREDS = " + json.dumps(creds) + ";\n")
    return creds
