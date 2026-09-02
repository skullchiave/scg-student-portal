/* scg-student-portal API層
 * ライブラリ依存ゼロ。Supabase REST を fetch で直接叩く。
 * ・ANON_KEY は「公開して良い鍵」（行単位アクセス制御=RLSが実際の門番。鍵は住所にすぎない）
 * ・全リクエストに自動再送（指数バックオフ+ジッタ）→ 教室で150台が一斉タップしても自然に分散する
 */
const SB_URL = "https://egdcbxzpgwenmfabpodd.supabase.co";
const SB_ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVnZGNieHpwZ3dlbm1mYWJwb2RkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgzNTcwNDYsImV4cCI6MjEwMzkzMzA0Nn0.m908C67Nh4KsYnH_LWvP4wAjOtxI79hhE-BKS1MCxX0";
const MAIL_DOMAIN = "stu.scg-portal.jp"; // 学籍番号→内部メールアドレス変換（実在しない管理用ドメイン）

/* ログインは localStorage で持続化する（重要）:
 * Supabaseのサインイン APIには同一IPからの回数制限がある。学校Wi-Fiで全員が
 * 同時にログインし直すと弾かれるため、「一度ログインしたら保持」が正しい運用。
 * 小テスト当日はログイン済みの状態で開くだけ → データAPIには制限がなく150同時OK（実測済）。 */
let _store = localStorage;
try { _store.setItem("_t", "1"); _store.removeItem("_t"); } catch (e) { _store = sessionStorage; }

const api = {
  token: _store.getItem("sp_token") || null,
  profile: JSON.parse(_store.getItem("sp_profile") || "null"),

  /* 再送つきfetch: 429/5xx/ネットワーク断は最大4回リトライ */
  async _fetch(path, opts = {}, tries = 4) {
    const headers = Object.assign({
      "apikey": SB_ANON,
      "Content-Type": "application/json",
    }, opts.headers || {});
    if (this.token) headers["Authorization"] = "Bearer " + this.token;
    let lastErr = null;
    for (let i = 0; i < tries; i++) {
      try {
        const res = await fetch(SB_URL + path, Object.assign({}, opts, { headers }));
        if (res.status === 429 || res.status >= 500) {
          lastErr = new Error("server busy: " + res.status);
        } else {
          return res; // 4xx（認証エラー等）は再送しない
        }
      } catch (e) {
        lastErr = e; // ネットワーク断
      }
      // 指数バックオフ + ジッタ: 0.6s→1.2s→2.4s（±50%乱数）
      const wait = 600 * Math.pow(2, i) * (0.5 + Math.random());
      await new Promise(r => setTimeout(r, wait));
    }
    throw lastErr;
  },

  async login(studentNo, password) {
    const email = studentNo.trim().toLowerCase() + "@" + MAIL_DOMAIN;
    const res = await this._fetch("/auth/v1/token?grant_type=password", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      if (body.error_code === "invalid_credentials" || res.status === 400)
        throw new Error("番号かパスワードがちがいます");
      throw new Error("ログインできませんでした（" + res.status + "）");
    }
    const data = await res.json();
    this.token = data.access_token;
    _store.setItem("sp_token", this.token);
    if (data.refresh_token) _store.setItem("sp_refresh", data.refresh_token);
    // プロフィール取得
    const p = await this._fetch("/rest/v1/profiles?select=student_no,display_name,role,class_name&id=eq." + data.user.id);
    const rows = await p.json();
    if (!rows.length) throw new Error("プロフィールが見つかりません");
    this.profile = rows[0];
    _store.setItem("sp_profile", JSON.stringify(this.profile));
    return this.profile;
  },

  logout() {
    this.token = null; this.profile = null;
    _store.removeItem("sp_token");
    _store.removeItem("sp_profile");
    _store.removeItem("sp_refresh");
  },

  /* トークン失効時: リフレッシュトークンで静かにログインし直す。だめなら再ログインへ */
  async _refresh() {
    const rt = _store.getItem("sp_refresh");
    if (!rt) return false;
    try {
      const res = await this._fetch("/auth/v1/token?grant_type=refresh_token", {
        method: "POST", body: JSON.stringify({ refresh_token: rt }),
      }, 2);
      if (!res.ok) return false;
      const data = await res.json();
      this.token = data.access_token;
      _store.setItem("sp_token", this.token);
      if (data.refresh_token) _store.setItem("sp_refresh", data.refresh_token);
      return true;
    } catch (e) { return false; }
  },

  async _authed(path, opts) {
    let res = await this._fetch(path, opts);
    if (res.status === 401 && await this._refresh()) {
      res = await this._fetch(path, opts); // 新トークンで1回だけやり直す
    }
    if (res.status === 401) { this.logout(); location.reload(); throw new Error("再ログインしてください"); }
    return res;
  },

  async get(path) {
    const res = await this._authed(path);
    if (!res.ok) throw new Error("読み込みに失敗しました（" + res.status + "）");
    return res.json();
  },

  async rpc(name, args) {
    const res = await this._authed("/rest/v1/rpc/" + name, {
      method: "POST", body: JSON.stringify(args || {}),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.message || "送信に失敗しました（" + res.status + "）");
    }
    return res.json();
  },
};
