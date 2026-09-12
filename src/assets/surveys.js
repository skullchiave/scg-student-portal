/* 学生ポータル アンケート定義（1か所で管理・多言語）
 * index.html（学生の回答画面）と master.html（管理画面の回答一覧）が同じこの配列を読む。
 * 1本足すときは配列に1件追加するだけ。DBの変更は要らない（回答は survey_responses に survey_key で入る）。
 *
 * 項目: key    … 回答の識別子（英小文字・数字・_ のみ。一度公開したら変えない）
 *       sb     … 行の小見出し（英語ラベル）   color … 行の色
 *       title  … 学生に見せる名前 {ja, en}（やさしい日本語・分かち書き）
 *       desc   … 一覧での説明 {ja, en}   intro … 回答画面の前置き {ja, en}（HTML可）
 *       q[]    … 質問。k=回答キー / t="select"|"text" / l=質問文 {ja,en} / sl=教師画面用の短い見出し（日本語）
 *                select は o=[{v:保存する値, ja, en}]（保存されるのは v。言語が変わっても同じ値）
 *                text   は ph=入力例 {ja,en}
 * 言語を足すときは各 {ja,en} にそのコードを足す。無い言語は日本語に落ちる。
 */
const SURVEYS = [
  { key: "shinro_2026", sb: "Career", color: "#2f9e44",
    title: { ja: "しんろアンケート", en: "Career survey" },
    desc:  { ja: "しごと・ぶんや・まち", en: "Job, field, city" },
    intro: { ja: "しょうらいの ことを おしえてください。<br>まだ きまっていなくても、いま おもっていることで OK です。",
             en: "Tell us about your future plans.<br>It is fine if you have not decided yet — just what you think now." },
    q: [
      { k: "job", t: "text", sl: "しごと",
        l:  { ja: "やってみたい しごと", en: "A job you would like to try" },
        ph: { ja: "れい: つうやく、IT エンジニア、ホテルの しごと", en: "e.g. interpreter, IT engineer, hotel work" } },
      { k: "field", t: "select", sl: "ぶんや",
        l: { ja: "すすみたい ぶんや", en: "Field you want to go into" },
        o: [
          { v: "it",       ja: "IT・コンピューター",        en: "IT / computers" },
          { v: "business", ja: "ビジネス・けいえい",        en: "Business / management" },
          { v: "trans",    ja: "つうやく・ほんやく",        en: "Interpreting / translation" },
          { v: "hotel",    ja: "かんこう・ホテル",          en: "Tourism / hotel" },
          { v: "care",     ja: "かいご・いりょう",          en: "Care / medical" },
          { v: "design",   ja: "デザイン・アニメ・アート",  en: "Design / anime / art" },
          { v: "cook",     ja: "りょうり・せいか",          en: "Cooking / confectionery" },
          { v: "auto",     ja: "じどうしゃ・きかい",        en: "Automobile / machinery" },
          { v: "other",    ja: "そのほか",                  en: "Other" },
          { v: "unknown",  ja: "まだ わからない",           en: "Not sure yet" },
        ] },
      { k: "town", t: "text", sl: "まち",
        l:  { ja: "すみたい まち（はたらきたい まち）", en: "City where you want to live or work" },
        ph: { ja: "れい: 東京、大阪、京都", en: "e.g. Tokyo, Osaka, Kyoto" } },
    ] },

  { key: "seikatsu_sumai_2026", sb: "Life", color: "#7b5cd6",
    title: { ja: "すまいの アンケート", en: "Housing survey" },
    desc:  { ja: "いま すんでいる ところ・がっこうまでの じかん", en: "Where you live, commute time" },
    intro: { ja: "いまの せいかつの ことを おしえてください。", en: "Tell us about your daily life." },
    q: [
      { k: "home", t: "select", sl: "すまい",
        l: { ja: "いま どこに すんでいますか", en: "Where do you live now?" },
        o: [
          { v: "dorm",    ja: "がっこうの りょう",       en: "School dormitory" },
          { v: "alone",   ja: "アパート（ひとりで）",    en: "Apartment (alone)" },
          { v: "share",   ja: "アパート（ともだちと）",  en: "Apartment (with friends)" },
          { v: "relative",ja: "しんせきの いえ",         en: "Relative's house" },
          { v: "other",   ja: "そのほか",                en: "Other" },
        ] },
      { k: "commute", t: "select", sl: "つうがく",
        l: { ja: "がっこうまで どのくらい かかりますか", en: "How long is your trip to school?" },
        o: [
          { v: "u15",  ja: "15ふん いか",   en: "Under 15 min" },
          { v: "15_30",ja: "15〜30ぷん",    en: "15–30 min" },
          { v: "30_60",ja: "30〜60ぷん",    en: "30–60 min" },
          { v: "o60",  ja: "60ぷん いじょう", en: "Over 60 min" },
        ] },
      { k: "trouble", t: "text", sl: "こまりごと",
        l:  { ja: "すまいで こまっていることは ありますか", en: "Any problems with your housing?" },
        ph: { ja: "れい: へやが さむい、となりが うるさい（なければ 空欄で OK）", en: "e.g. room is cold, noisy neighbours (leave blank if none)" } },
    ] },

  { key: "seikatsu_kenko_2026", sb: "Life", color: "#0f9b8e",
    title: { ja: "アルバイトと けんこうの アンケート", en: "Part-time job & health survey" },
    desc:  { ja: "はたらく じかん・からだの ちょうし", en: "Working hours, how you feel" },
    intro: { ja: "むりを していないか、おしえてください。<br>こまっている ときは、せんせいが そうだんに のります。",
             en: "Let us know if things are getting too hard.<br>Teachers are here to help." },
    q: [
      { k: "work", t: "select", sl: "アルバイト",
        l: { ja: "アルバイトを していますか", en: "Do you have a part-time job?" },
        o: [
          { v: "none",  ja: "していない",              en: "No" },
          { v: "u10",   ja: "しゅうに 10じかん いか",  en: "Up to 10 hours a week" },
          { v: "10_20", ja: "しゅうに 10〜20じかん",   en: "10–20 hours a week" },
          { v: "20_28", ja: "しゅうに 20〜28じかん",   en: "20–28 hours a week" },
        ] },
      { k: "health", t: "select", sl: "ちょうし",
        l: { ja: "からだの ちょうしは どうですか", en: "How is your health?" },
        o: [
          { v: "good", ja: "とても いい",    en: "Very good" },
          { v: "ok",   ja: "ふつう",         en: "OK" },
          { v: "bad",  ja: "あまり よくない", en: "Not so good" },
        ] },
      { k: "sleep", t: "select", sl: "すいみん",
        l: { ja: "よる よく ねむれていますか", en: "Do you sleep well at night?" },
        o: [
          { v: "yes",       ja: "はい",              en: "Yes" },
          { v: "sometimes", ja: "ときどき ねむれない", en: "Sometimes I cannot sleep" },
          { v: "no",        ja: "よく ねむれない",     en: "I often cannot sleep" },
        ] },
    ] },

  { key: "gakuhi_2026", sb: "Tuition", color: "#c77700",
    title: { ja: "がくひの アンケート", en: "Tuition survey" },
    desc:  { ja: "つぎの がくひの しはらい", en: "Paying the next tuition" },
    intro: { ja: "つぎの がくひの ことを おしえてください。<br>こまっている ときは、はやめに そうだん できます。",
             en: "Tell us about your next tuition payment.<br>If it is difficult, you can talk to us early." },
    q: [
      { k: "payer", t: "select", sl: "はらう人",
        l: { ja: "つぎの がくひは だれが はらいますか", en: "Who will pay the next tuition?" },
        o: [
          { v: "self",    ja: "じぶん（アルバイトの おかね）", en: "Myself (from my part-time job)" },
          { v: "family",  ja: "かぞく",                     en: "My family" },
          { v: "both",    ja: "じぶんと かぞく",             en: "Myself and my family" },
          { v: "unknown", ja: "まだ わからない",             en: "Not sure yet" },
        ] },
      { k: "worry", t: "select", sl: "しんぱい",
        l: { ja: "しはらいに しんぱいが ありますか", en: "Are you worried about paying?" },
        o: [
          { v: "no",   ja: "ない",       en: "No" },
          { v: "some", ja: "すこし ある", en: "A little" },
          { v: "yes",  ja: "ある",       en: "Yes" },
        ] },
      { k: "consult", t: "select", sl: "そうだん",
        l: { ja: "がっこうに そうだん したいですか", en: "Would you like to talk to the school?" },
        o: [
          { v: "yes",   ja: "はい",             en: "Yes" },
          { v: "no",    ja: "いいえ",           en: "No" },
          { v: "later", ja: "あとで かんがえます", en: "I will think about it later" },
        ] },
    ] },
];

/* 教師画面用: 保存された値（v）→ 日本語の選択肢名。昔の回答（日本語の文がそのまま入っている）はそのまま返す */
function optLabel(q, v) {
  if (v == null || v === "") return "";
  if (q.t !== "select" || !q.o) return String(v);
  const hit = q.o.find(o => o.v === v || o.ja === v || o.en === v);
  return hit ? hit.ja : String(v);
}
