/* 学生ポータル 文言（多言語）— 1か所で管理
 * 画面の文言はここに書き、HTML側は data-i18n="キー" で参照する。JS側は t("キー") / tx({ja,en}) を使う。
 * 言語の追加: ① LANGS に ready:true を付ける ② I18N[コード] を ja と同じキーで埋める
 *            ③ surveys.js の {ja,en} にそのコードを足す。無いキーは日本語に落ちる（画面が空にならない）。
 * 選んだ言語は localStorage "sp_lang" に保存し、次に開いたときもその言語で出る。
 * 翻訳の確認は学校の翻訳確認スタッフ（中国語・ネパール語・ミャンマー語・シンハラ語）に回す前提。
 */
const LANGS = [
  { code: "ja", native: "日本語",   en: "Japanese", ready: true },
  { code: "en", native: "English",  en: "English",  ready: true },
  { code: "zh", native: "中文",     en: "Chinese" },
  { code: "ne", native: "नेपाली",   en: "Nepali" },
  { code: "my", native: "မြန်မာ",   en: "Burmese" },
  { code: "si", native: "සිංහල",   en: "Sinhala" },
  { code: "bn", native: "বাংলা",    en: "Bengali" },
];

const I18N = {
  ja: {
    "app.title": "学生ポータル", "app.for": "for 学生", "app.footer": "SCG 学生ポータル（デモ）",
    "lang.soon": "じゅんびちゅう",
    "login.title": "ログイン", "login.no": "がくせきばんごう（学籍番号）", "login.pw": "パスワード",
    "login.btn": "ログイン", "login.busy": "ログインしています…", "login.need": "番号とパスワードを入れてください",
    "err.badlogin": "番号かパスワードがちがいます", "err.login": "ログインできませんでした（{s}）",
    "err.noprofile": "プロフィールが見つかりません", "err.read": "読み込みに失敗しました（{s}）",
    "err.send": "送信に失敗しました（{s}）", "err.relogin": "再ログインしてください",
    "my.san": "{name} さん", "my.noclass": "クラス未設定",
    "my.now": "いま動きます", "my.soon": "これから作る画面（イメージ）",
    "my.quiz": "テストを うける", "my.quiz.ds": "せんたくしから えらぶ もんだい。すぐに てんすうが でます",
    "my.survey": "アンケートに こたえる", "my.survey.ds": "しんろ・すまい・アルバイト・がくひ の 4つ",
    "my.grades": "せいせき（成績）", "my.grades.ds": "JLPT・JPT・定期試験・模試・出席率",
    "my.news": "おしらせ", "my.news.ds": "試験の日程・休みの期間・大事な連絡",
    "my.jobs": "アルバイト", "my.jobs.ds": "求人と、28時間ルールの注意",
    "my.schools": "しんがく先の情報", "my.schools.ds": "専門学校・大学の一覧と出願の締切",
    "my.voices": "せんぱいの声", "my.voices.ds": "いま進学先にいる卒業生へのインタビュー",
    "my.logout": "ログアウト",
    "q.back": "もどる", "q.loading": "よみこみ中…", "q.none": "いま うけられるテストは ありません",
    // 実施回（先生が「はじめる」を押した回）には おわる じかんが ある
    "q.left": "あと {n}ふん", "q.timeup": "じかんが おわりました。せんせいに いってください。",
    "q.noq": "もんだいが ありません", "q.prompt": "（　）に なにを いれますか。 ",
    "q.next": "つぎへ", "q.submit": "そうしん（送信）", "q.sending": "そうしん中…",
    "q.fail": "そうしんできませんでした。もういちど おしてください。（{msg}）",
    // 下書きの保存ぐあい。「ほぞん」と「そうしん（提出）」は べつのことば にする
    "q.sv.saving": "ほぞん中…", "q.sv.saved": "✓ ここまで ほぞんしました",
    "q.sv.pend": "⚠ {n}もん まだ おくれていません（あとで じどうで おくります）",
    "q.sv.resumed": "まえの つづきから はじめます（{n}もん ほぞんずみ）",
    "r.of": "／ {total} もん せいかい", "r.check": "こたえの かくにん", "r.ans": "こたえ: ", "r.home": "マイページへ もどる",
    "sv.title": "アンケート", "sv.badge.all": "ぜんぶ ていしゅつ済み", "sv.badge.n": "{n}／{t} ていしゅつ済み",
    "sv.none": "いま こたえられる アンケートは ありません",
    "sv.done": "ていしゅつ済み", "sv.doneds": "{d} に ていしゅつ。なおして もういちど だせます",
    "sv.choose": "えらんで ください", "sv.min1": "1つ以上 こたえてください",
    "sv.prev": "ていしゅつ済みです。なおして もういちど そうしん できます。", "sv.resubmit": "なおして そうしん",
    "sv.received": "「{title}」を うけとりました。ありがとうございます！",
    /* しけんの ひ（ログインしなくても見える）。日付は {M}月{D}日（{W}）の形で組む */
    "ex.title": "つぎの しけん", "ex.date": "{M}月{D}日（{W}）",
    "ex.wd": "日,月,火,水,木,金,土", "ex.mn": "1,2,3,4,5,6,7,8,9,10,11,12",
    "ex.days": "あと {n}にち", "ex.today": "きょう です", "ex.tomorrow": "あした です",
    "ex.result": "けっかは {d} に でます", "ex.result.lag": "けっかは あとで でます",
    "ex.inschool": "がっこうで うけます",
    "ex.none": "つぎの しけんは まだ きまっていません",
    "ex.g.1年生": "1ねんせい", "ex.g.2年生": "2ねんせい",
  },
  en: {
    "app.title": "Student Portal", "app.for": "for students", "app.footer": "SCG Student Portal (demo)",
    "lang.soon": "coming soon",
    "login.title": "Log in", "login.no": "Student number", "login.pw": "Password",
    "login.btn": "Log in", "login.busy": "Logging in…", "login.need": "Please enter your number and password.",
    "err.badlogin": "Wrong student number or password.", "err.login": "Could not log in ({s})",
    "err.noprofile": "Profile not found.", "err.read": "Could not load ({s})",
    "err.send": "Could not send ({s})", "err.relogin": "Please log in again.",
    "my.san": "{name}", "my.noclass": "No class set",
    "my.now": "Working now", "my.soon": "Coming soon (mock-ups)",
    "my.quiz": "Take a quiz", "my.quiz.ds": "Choose one answer. You get your score right away.",
    "my.survey": "Answer surveys", "my.survey.ds": "Career, housing, part-time job, tuition — 4 surveys",
    "my.grades": "Grades", "my.grades.ds": "JLPT, JPT, term exams, mock exams, attendance",
    "my.news": "News", "my.news.ds": "Exam dates, holidays, important notices",
    "my.jobs": "Part-time jobs", "my.jobs.ds": "Job openings and the 28-hour rule",
    "my.schools": "Schools & courses", "my.schools.ds": "Vocational schools, universities, deadlines",
    "my.voices": "Senior voices", "my.voices.ds": "Interviews with graduates now at their schools",
    "my.logout": "Log out",
    "q.back": "Back", "q.loading": "Loading…", "q.none": "No quiz is open right now.",
    "q.left": "{n} min left", "q.timeup": "Time is up. Please tell your teacher.",
    "q.noq": "This quiz has no questions.", "q.prompt": "What goes in (  )?  ",
    "q.next": "Next", "q.submit": "Submit", "q.sending": "Sending…",
    "q.fail": "Could not send. Please try again. ({msg})",
    "q.sv.saving": "Saving…", "q.sv.saved": "✓ Saved up to here",
    "q.sv.pend": "⚠ {n} answer(s) not sent yet (will be sent automatically)",
    "q.sv.resumed": "Continuing from where you left off ({n} saved)",
    "r.of": "out of {total} correct", "r.check": "Check your answers", "r.ans": "Answer: ", "r.home": "Back to My Page",
    "sv.title": "Surveys", "sv.badge.all": "All submitted", "sv.badge.n": "{n}/{t} submitted",
    "sv.none": "No surveys are open right now.",
    "sv.done": "Submitted", "sv.doneds": "Submitted on {d}. You can edit and send again.",
    "sv.choose": "Please choose", "sv.min1": "Please answer at least one question.",
    "sv.prev": "Already submitted. You can edit and send again.", "sv.resubmit": "Update & submit",
    "sv.received": "Received “{title}”. Thank you!",
    "ex.title": "Next exams", "ex.date": "{W}, {M} {D}",
    "ex.wd": "Sun,Mon,Tue,Wed,Thu,Fri,Sat",
    "ex.mn": "Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec",
    "ex.days": "{n} days left", "ex.today": "Today", "ex.tomorrow": "Tomorrow",
    "ex.result": "Results on {d}", "ex.result.lag": "Results come later",
    "ex.inschool": "Held at school",
    "ex.none": "The next exam date has not been decided yet.",
    "ex.g.1年生": "Year 1", "ex.g.2年生": "Year 2",
  },
};

let LANG = "ja";

/* 文言を返す。無ければ日本語 → キーそのもの。{name} のような穴は vars で埋める */
function t(key, vars) {
  let s = (I18N[LANG] && I18N[LANG][key]);
  if (s == null) s = I18N.ja[key];
  if (s == null) s = key;
  if (vars) Object.keys(vars).forEach(k => { s = s.split("{" + k + "}").join(vars[k]); });
  return s;
}
/* {ja:"…", en:"…"} 型（アンケート定義など）から今の言語の文言を返す。無ければ日本語 */
function tx(obj) {
  if (obj == null) return "";
  if (typeof obj === "string") return obj;
  return obj[LANG] != null ? obj[LANG] : (obj.ja != null ? obj.ja : "");
}
/* 静的なHTMLの文言を貼り替える（data-i18n=テキスト / data-i18n-ph=placeholder） */
function applyI18n(root) {
  const r = root || document;
  r.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.getAttribute("data-i18n")); });
  r.querySelectorAll("[data-i18n-ph]").forEach(el => { el.placeholder = t(el.getAttribute("data-i18n-ph")); });
}
/* 言語を切り替えて保存。画面側は "sp:lang" イベントで動的な部分を描き直す */
function setLang(code, persist) {
  if (!I18N[code]) code = "ja";
  LANG = code;
  document.documentElement.lang = code;
  if (persist !== false) { try { localStorage.setItem("sp_lang", code); } catch (e) {} }
  applyI18n();
  window.dispatchEvent(new CustomEvent("sp:lang", { detail: code }));
}
/* 起動時: 前回選んだ言語があればそれ、無ければ日本語 */
function initLang() {
  let c = null;
  try { c = localStorage.getItem("sp_lang"); } catch (e) {}
  setLang(c && I18N[c] ? c : "ja", false);
}

/* ヘッダー右上の「🌐 言語」ボタン＋メニュー。押すと一覧、選ぶと切替（記憶される） */
function mountLangSwitch(el) {
  if (!el) return;
  el.innerHTML = '<button type="button" class="langbtn" id="langbtn" aria-haspopup="listbox" aria-expanded="false">' +
                 '<span class="ico" aria-hidden="true">🌐</span><span class="cur" id="langcur"></span><span class="car" aria-hidden="true"></span></button>';
  const btn = el.querySelector("#langbtn"), cur = el.querySelector("#langcur");
  const menu = document.createElement("div");
  menu.className = "langmenu"; menu.id = "langmenu"; menu.setAttribute("role", "listbox"); menu.hidden = true;
  document.body.appendChild(menu);           /* ヘッダーの overflow に切られないよう body 直下に置く */
  function paint() {
    const now = LANGS.find(l => l.code === LANG) || LANGS[0];
    cur.textContent = now.native;
    menu.innerHTML = LANGS.map(l =>
      '<button type="button" role="option" data-code="' + l.code + '"' +
      ' class="' + (l.code === LANG ? "cur" : "") + '"' + (l.ready ? "" : " disabled") +
      ' aria-selected="' + (l.code === LANG) + '">' +
      '<span class="nat">' + l.native + '</span>' +
      '<span class="en">' + l.en + (l.ready ? "" : " · " + t("lang.soon")) + '</span></button>').join("");
  }
  function place() {
    const r = btn.getBoundingClientRect();
    menu.style.top = (r.bottom + 8) + "px";
    menu.style.right = Math.max(8, window.innerWidth - r.right) + "px";
  }
  function open() { place(); menu.hidden = false; btn.setAttribute("aria-expanded", "true"); }
  function close() { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); }
  btn.addEventListener("click", e => { e.stopPropagation(); menu.hidden ? open() : close(); });
  menu.addEventListener("click", e => {
    const b = e.target.closest("[data-code]");
    if (!b || b.disabled) return;
    e.stopPropagation();
    setLang(b.getAttribute("data-code"));
    close();
  });
  document.addEventListener("click", close);
  window.addEventListener("scroll", close, { passive: true });
  window.addEventListener("sp:lang", paint);
  paint();
}
