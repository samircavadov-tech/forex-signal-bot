// Forex siqnal botunun ani cavab hissəsi (Cloudflare Worker).
// Telegram mesajları webhook ilə buraya gəlir və dərhal cavablandırılır.
// Məlumat (qiymətlər, svoplar, son siqnallar, portfel hesabatı) GitHub-dakı əsas botdan
// hər saat POST /status ilə gəlir və KV-də saxlanılır. Telegram tokeni POST /setup ilə gəlir.

const GREETINGS = ["salam", "slm", "hi", "hello", "hey", "privet", "привет", "/start"];
const GREETING_PHRASES = ["sabahınız xeyir", "sabahiniz xeyir", "günortanız xeyir", "axşamınız xeyir", "axsaminiz xeyir"];
const REPORT_WORDS = ["hesabat", "report", "portfel", "nəticə", "netice"];
const HELP_WORDS = ["/help", "kömək", "komek", "help"];

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/telegram") return telegram(request, env, ctx);
    if (request.method === "POST" && url.pathname === "/status") return status(request, env);
    if (request.method === "POST" && url.pathname === "/setup") return setup(request, env, url);
    return new Response("ok");
  },
};

// ---------- GitHub → Worker ----------
function authorized(request, env) {
  const key = request.headers.get("X-Status-Key") || "";
  return env.STATUS_KEY && key.length === env.STATUS_KEY.length && key === env.STATUS_KEY;
}

async function status(request, env) {
  if (!authorized(request, env)) return new Response("forbidden", { status: 403 });
  const body = await request.text();
  JSON.parse(body); // yalnız etibarlı JSON saxlanılır
  await env.KV.put("status", body);
  return new Response("saved");
}

async function setup(request, env, url) {
  if (!authorized(request, env)) return new Response("forbidden", { status: 403 });
  const { bot_token, chat_ids } = await request.json();
  const old = (await env.KV.get("cfg", "json")) || {};
  const webhook_secret = old.webhook_secret || randomHex(32);
  await env.KV.put("cfg", JSON.stringify({ bot_token, chat_ids, webhook_secret }));
  const r = await fetch(`https://api.telegram.org/bot${bot_token}/setWebhook`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: `${url.origin}/telegram`, secret_token: webhook_secret, allowed_updates: ["message"] }),
  });
  const j = await r.json();
  return new Response(JSON.stringify({ ok: j.ok, description: j.description }), { headers: { "Content-Type": "application/json" } });
}

function randomHex(n) {
  const a = new Uint8Array(n);
  crypto.getRandomValues(a);
  return [...a].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// ---------- Telegram → Worker ----------
async function telegram(request, env, ctx) {
  const cfg = await env.KV.get("cfg", "json");
  if (!cfg || request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== cfg.webhook_secret) {
    return new Response("forbidden", { status: 403 });
  }
  const update = await request.json();
  const msg = update.message || {};
  const chat = String((msg.chat || {}).id || "");
  const text = msg.text || "";
  if (text && cfg.chat_ids.includes(chat)) {
    ctx.waitUntil(handle(env, cfg, chat, msg, text));
  }
  return new Response("ok");
}

async function handle(env, cfg, chat, msg, text) {
  const st = (await env.KV.get("status", "json")) || {};
  const replied = (msg.reply_to_message || {}).text || "";
  let out;
  try {
    const low = text.trim().toLowerCase();
    if (HELP_WORDS.includes(low)) out = help(st);
    else if (REPORT_WORDS.includes(low.replace(/^[\/\s]+|[\s]+$/g, ""))) out = report(st);
    else if (isCalculation(st, text, replied)) out = answer(st, parse(st, text, replied));
    else if (isGreeting(low)) out = welcome(st);
    else out = NOT_CHAT;
  } catch (e) {
    out = "❌ Hesablama alınmadı. Nümunə: <code>EURAUD SELL 0.05 lot 30 pips</code>";
  }
  await fetch(`https://api.telegram.org/bot${cfg.bot_token}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chat, text: out, parse_mode: "HTML", reply_to_message_id: msg.message_id }),
  });
}

// ---------- Mətnlər ----------
const NOT_CHAT =
  "ℹ️ <b>Bu bot yazışma üçün nəzərdə tutulmayıb.</b>\n\n" +
  "Bot yalnız aşağıdakı xidmətləri göstərir:\n" +
  "• 📅 bazar siqnallarının avtomatik göndərilməsi\n" +
  "• 📰 gündəlik iqtisadi xəbər xülasəsi və 📆 aylıq hesabat\n" +
  "• 🧮 gəlir hesablaması — məsələn: <code>EURAUD SELL 0.05 lot 30 pips</code>\n\n" +
  "Anlayışınız üçün təşəkkür edirik.";

function symbols(st) {
  return (st.config && st.config.symbols) || ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
    "XAUUSD", "AUDJPY", "EURGBP", "EURAUD"];
}

function help(st) {
  return "🧮 <b>Hesablama üçün sual nümunələri</b>\n" +
    "• Siqnal mesajına <b>Reply</b> edib yazın: <code>0.05 lot 30 pips</code>\n" +
    "• Və ya birbaşa: <code>EURAUD SELL 0.05 lot 30 pips</code>\n" +
    "• Svopu da hesablamaq üçün gün əlavə edin: <code>... 10 gün</code>\n" +
    "• Siqnalların real nəticəsi: <code>hesabat</code>\n" +
    `Cütlər: ${symbols(st).join(", ")}`;
}

function welcome(st) {
  const now = Date.now() / 1000;
  const recent = (st.signals || []).filter((x) => now - x[0] < 24 * 3600);
  const lines = ["👋 <b>Salam! Forex Siqnal Botuna xoş gəlmisiniz.</b>", "",
    "Bot valyuta bazarını avtomatik izləyir və strategiya şərtləri yarandıqda sizə dərhal siqnal göndərir.", ""];
  if (recent.length) {
    lines.push("📬 <b>Son 24 saatda göndərilən siqnallar:</b>");
    for (const [ts, t] of recent) lines.push(`• ${bakuTime(ts)} — ${t}`);
  } else {
    lines.push("📭 <b>Hazırda aktiv siqnal yoxdur.</b> Yeni siqnal yarandıqda bildiriş alacaqsınız.");
  }
  lines.push("", "🧮 Gəliri hesablamaq üçün siqnal mesajına <b>Reply</b> edib yazın, məsələn: <code>0.05 lot 30 pips</code>");
  return lines.join("\n");
}

function report(st) {
  if (!st.report) return "📊 Hesabat hələ hazır deyil. Bir az sonra yenidən yoxlayın.";
  return st.report + (st.updated ? `\n\n<i>Məlumat yenilənib: ${bakuTime(st.updated)}</i>` : "");
}

function bakuTime(ts) {
  const d = new Date((ts + 4 * 3600) * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getUTCDate())}.${p(d.getUTCMonth() + 1)} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}

// ---------- Tanıma ----------
function isGreeting(low) {
  const first = low.trim().split(/[\s,!.?]+/)[0];
  return GREETINGS.includes(first) || GREETING_PHRASES.some((g) => low.startsWith(g));
}

function findSymbol(st, src) {
  const flat = src.toUpperCase().replace(/\//g, "").replace(/\s/g, "");
  return symbols(st).find((s) => flat.includes(s)) || null;
}

function isCalculation(st, text, replied) {
  const t = text.toLowerCase();
  return /\d\s*(lot|pip)/.test(t) || !!findSymbol(st, text) || (!!replied && /\d/.test(t));
}

function parse(st, text, replied) {
  const t = text.toLowerCase().replace(/,/g, ".");
  const symbol = findSymbol(st, text) || findSymbol(st, replied);
  let side = null;
  for (const src of [text.toUpperCase(), replied.toUpperCase()]) {
    if (src.includes("SELL") || src.includes("SATIŞ")) { side = "SELL"; break; }
    if (src.includes("BUY") || src.includes("ALIŞ")) { side = "BUY"; break; }
  }
  const lotM = t.match(/(\d+(?:\.\d+)?)\s*lot/);
  const pipsM = t.match(/(\d+(?:\.\d+)?)\s*(?:pips|pip|pp|pts|pt)/);
  const daysM = t.match(/(\d+)\s*(?:gün|gun|gecə|gece|day)/);
  const loose = t.match(/\d+(?:\.\d+)?/g) || [];
  const lot = lotM ? +lotM[1] : (loose.find((x) => x.includes(".") && +x < 100) ?? null);
  const pips = pipsM ? +pipsM[1] : (loose.find((x) => !x.includes(".") && +x >= 5 && !(daysM && x === daysM[1])) ?? null);
  const priceM = replied.match(/Qiymət:\s*([\d.]+)/);
  const c = st.config || {};
  return { symbol, side, lot: lot ? +lot : 0.01, pips: pips ? +pips : (c.tp_default || 50),
    days: daysM ? +daysM[1] : null, price: priceM ? +priceM[1] : null };
}

// ---------- Hesablama ----------
function pipSize(sym) { return sym === "XAUUSD" ? 0.1 : sym.endsWith("JPY") ? 0.01 : 0.0001; }

function pipValueUsd(st, sym, price) {
  const p = st.prices || {};
  if (sym === "XAUUSD" || sym.endsWith("USD")) return 10;
  if (sym.startsWith("USD")) return (sym.endsWith("JPY") ? 1000 : 10) / price;
  const quote = sym.slice(3);
  if (quote === "JPY") return p.USDJPY ? 1000 / p.USDJPY : null;
  const r = p[quote + "USD"];
  return r ? 10 * r : null;
}

function swapFor(st, sym) {
  const c = st.config || {};
  if (c.investaz && c.investaz[sym]) return [c.investaz[sym][1], c.investaz[sym][2]];
  const s = (st.swaps || {})[sym];
  return s ? [s.long, s.short] : [null, null];
}

function answer(st, q) {
  const c = st.config || {};
  const usdAzn = c.usd_azn || 1.7;
  const azn = (x) => `${x * usdAzn >= 0 ? "+" : ""}${(x * usdAzn).toFixed(2)} AZN`;
  const sym = q.symbol;
  if (!sym) return help(st);
  const price = q.price || (st.prices || {})[sym];
  if (!price) return `❌ ${sym} üçün qiymət hələ yoxdur, bir az sonra yenidən yoxlayın.`;
  const pv1 = pipValueUsd(st, sym, price);
  if (!pv1) return `❌ ${sym} üçün pips dəyəri hesablanmadı.`;
  const spread = (c.investaz && c.investaz[sym]) ? c.investaz[sym][0] : ((c.default_spread || {})[sym] ?? 2.0);
  const { lot, pips, side } = q;
  const net = +(pips - spread).toFixed(2);
  const usd = net * pv1 * lot;
  const digits = sym.endsWith("JPY") ? 3 : sym === "XAUUSD" ? 2 : 5;

  const lines = [`🧮 <b>HESABLAMA — ${sym}${side ? " " + side : ""}</b>`, `Lot: <b>${lot}</b> | TP: <b>${pips} pips</b>`];
  if (side) {
    const tp = price + (side === "BUY" ? 1 : -1) * pips * pipSize(sym);
    lines.push(`Qiymət: <code>${price.toFixed(digits)}</code> → TP: <code>${tp.toFixed(digits)}</code>`);
  }
  lines.push("",
    `1) Xalis pips: ${pips} − ${spread} (spred) = <b>${net} pips</b>`,
    `2) 1 pips dəyəri: 1 lot = ${pv1.toFixed(2)}$ → ${lot} lot = ${(pv1 * lot).toFixed(4)}$`,
    `3) TP-də gəlir: ${net} × ${(pv1 * lot).toFixed(4)}$ = <b>${usd >= 0 ? "+" : ""}${usd.toFixed(2)}$ = ${azn(usd)}</b>`);

  const [lng, sht] = swapFor(st, sym);
  if (lng !== null && lng !== undefined) {
    lines.push("");
    for (const sd of side ? [side] : ["BUY", "SELL"]) {
      const s = sd === "BUY" ? lng : sht;
      lines.push(`💱 Svop ${sd}: ${s >= 0 ? "+" : ""}${s.toFixed(2)}$/lot/gecə ${s > 0 ? "✅ müsbət" : "❌ mənfi"} → ${lot} lotla gecəyə ${azn(s * lot)}`);
      for (const n of q.days ? [q.days] : [7, 30]) {
        const tot = s * lot * n;
        lines.push(`   ${n} gün açıq qalsa: svop ${azn(tot)} → cəmi <b>${azn(usd + tot)}</b>`);
      }
    }
  }
  // təxmini marja
  const p = st.prices || {};
  const base = sym.slice(0, 3), quote = sym.slice(3);
  let notional = null;
  if (sym === "XAUUSD") notional = 100 * price * lot;
  else if (base === "USD") notional = 100000 * lot;
  else if (quote === "USD") notional = 100000 * price * lot;
  else if (p[base + "USD"]) notional = 100000 * p[base + "USD"] * lot;
  if (notional) {
    const m = (c.margin_rate || {})[sym] ?? 0.02;
    lines.push("", `🏦 Lazımi marja (təxmini, ${m * 100}%): ${(notional * m).toFixed(2)}$ = ${(notional * m * usdAzn).toFixed(2)} AZN`);
  }
  lines.push("", `ℹ️ Pips dəyəri son kursla hesablanır${st.updated ? " (" + bakuTime(st.updated) + ")" : ""}; AZN = ${usdAzn} × USD.`);
  return lines.join("\n");
}
