/* パスワードの「目」— 押している間だけでなく、押すたびに 表示⇔伏せ字 を切り替える（2026-09-12 きあ依頼）
 *
 * ■ なぜ要るか
 *   ・学生はスマホで打つ。伏せ字だけだと、打ち間違いに気づけずログインできない
 *     （日本語学校なので、ローマ字入力そのものに不慣れな学生もいる）
 *   ・先生・マスターは長めのパスワードを手で打つことがある
 *
 * ■ 作り
 *   読み込むだけで、その画面の **すべての input[type=password]** に目のボタンが付く。
 *   ★画面ごとに書かない＝3画面（学生・先生・マスター）で同じ動きを保つため。
 *     あとでパスワード欄が増えても、何もしなくても付く。
 *
 * ■ 見た目
 *   app.css の .pwwrap / .pwbtn を使う。入力欄の中の右端に重ねる
 *   （★.field input{width:100%} が効いているので、横に並べると欄が縮んで崩れる。
 *     2026-09-11 にチェックボックスで同じ崩れ方を踏んでいる）。
 *
 * ■ 文言
 *   i18n.js の t() があれば使う（学生画面は日本語/English を切り替える）。無ければ日本語。
 */
(function () {
  "use strict";

  var SHOWN = "\u{1F441}";     // 👁 いま見えている
  var HIDDEN = "\u{1F576}";    // 🕶 いま伏せている

  function label(on) {
    var key = on ? "pw.hide" : "pw.show";
    var fallback = on ? "パスワードをかくす" : "パスワードを見る";
    try {
      if (typeof t === "function") {
        var s = t(key);
        if (s && s !== key) return s;
      }
    } catch (e) {}
    return fallback;
  }

  function paint(btn, input) {
    var on = input.type === "text";
    btn.textContent = on ? SHOWN : HIDDEN;
    btn.setAttribute("aria-label", label(on));
    btn.setAttribute("title", label(on));
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  }

  function attach(input) {
    if (input.dataset.pwEye === "1") return;      // 二度付けしない
    input.dataset.pwEye = "1";

    var wrap = document.createElement("div");
    wrap.className = "pwwrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    var btn = document.createElement("button");
    btn.type = "button";                           // ★submit にしない（Enterで送信される form の中に居るため）
    btn.className = "pwbtn";
    btn.tabIndex = -1;                             // Tab の流れを邪魔しない（欄→ログインボタン、が自然）
    wrap.appendChild(btn);
    paint(btn, input);

    btn.addEventListener("click", function () {
      input.type = (input.type === "password") ? "text" : "password";
      paint(btn, input);
      input.focus();
    });

    // 言語を切り替えたら読み上げ用の文言も追従する（学生画面の 🌐 メニュー）
    window.addEventListener("sp:lang", function () { paint(btn, input); });
  }

  function attachAll(root) {
    (root || document).querySelectorAll('input[type="password"]').forEach(attach);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { attachAll(); });
  } else {
    attachAll();
  }

  window.attachPasswordEye = attachAll;            // あとから増えた欄にも付けられるように
})();
