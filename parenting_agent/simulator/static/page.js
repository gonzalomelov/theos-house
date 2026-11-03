"use strict";
const SCENES = [
  ["evening", "21:30", "Tue", {en: "Plan for tonight", es: "El plan de esta noche"}],
  ["sleep", "21:45", "Tue", {en: "Ceci asks to sleep", es: "Ceci pide dormir"}],
  ["cry", "02:50", "Wed", {en: "Theo cries", es: "Theo llora"}],
  ["feed", "03:20", "Wed", {en: "Gonza's voice note", es: "La nota de voz de Gonza"}],
  ["morning", "07:30", "Wed", {en: "Morning", es: "La mañana"}],
  ["grandma", "11:00", "Wed", {en: "Grandma asks the Echo", es: "La abuela le pregunta al Echo"}],
  ["humid", "15:10", "Wed", {en: "Humidity rises to 71%", es: "La humedad sube a 71%"}],
  ["dry", "17:40", "Wed", {en: "Humidity falls to 49.5%", es: "La humedad baja a 49,5%"}],
  ["carseat", "18:10", "Wed", {en: "Help with the car seat", es: "Ayuda con la silla del auto"}],
  ["evening2", "21:30", "Wed", {en: "The next evening", es: "La noche siguiente"}],
];
const NIGHT = ["evening", "sleep", "cry", "feed", "morning"];
const T = {
  en: {locale: "en-US", simulated: "Simulated", lead: "A home agent for two new parents. Gonza and Ceci are first-time parents and Theo is their newborn, simulated here. Meta's Muse Spark Open decides live what the home does and who gets told, and nothing here reaches a real house.",
    play: "Play one night", stop: "Stop", playing: (i, n, s) => `${i} of ${n}: ${s}`, nightDone: "That was one night, and every step was decided live. Send any home event below, or write from a phone.", sure: "Press again to start over", restarted: "Started over in English.", deep: "See how it thinks", plain: "Back to plain", empty: "Nothing yet. The agent writes first.",
    send2: "Send a home event", humLabel: "Nursery humidity", tempLabel: "Nursery temperature", cry: "Crying heard", dog: "Barking heard", plug: (n, s) => `${n} plug ${s}`, am: "Morning check", pm: "Evening check", h1: "Clock +1 hour", h6: "Clock +6 hours", sent: "Event sent", reset: "Start over", phoneG: "Gonza's phone", phoneC: "Ceci's phone", writeG: "Write as Gonza", writeC: "Write as Ceci", send: "Send", asleep: "Nothing sent to this phone", house: "Theo's house, simulated",
    parents: "Parents' room", theo: "Theo's room", kitchen: "Kitchen", living: "Living room", dehum: "Dehumidifier", echo: "Echo", warmer: "Bottle warmer", light: "Desk light", vacuum: "Robot vacuum",
    on: "On", off: "Off", humidityWord: "humidity", wet: "wet", dirty: "dirty", trace: "What Muse is doing", traceEmpty: "Press Play one night, or send any home event. What Muse chooses shows up here as it happens.",
    memory: "What Muse remembers", memoryEmpty: "Nothing yet. Plans it keeps will stay here across days.", log: "Theo's log", rail: "Moments from the story", thinking: "Muse is deciding", failed: "Muse didn't answer this one. Press another moment, or start over.",
    took: (s, t) => `${s} s, ${t} tokens`, by: "Decided by Muse Spark Open", byIn: s => `Decided by Muse Spark Open in ${s} s`, nothing: "Muse looked and chose to do nothing.", decided: "Muse's note", woke: "Muse woke itself up, as it had planned", gate: "Fixed safety reply from code. No model was asked.",
    humid: v => `Nursery humidity reads ${v}%`, heat: v => `Nursery temperature reads ${v} °C`, plugSet: (n, v) => `Someone switched the ${n} plug ${v}`, heard: {"baby crying": "Crying heard", "dog barking": "Barking heard"}, checks: {morning: "Morning check", evening: "Evening check"}, atHome: {sound: "At home, this event comes from Perception Encoder Audio on the microphone. Here you sent it.", sensor: "At home, this event comes from the sensor built on Meta's Muse Gadget SDK. Here you sent it."}, coachBy: "In the recording: SAM 3.1 watches and MMS-TTS speaks", duty: "On duty",
    foot: "Simulated: Theo, the sounds, the sensors, the plugs and the phones. Typed here: Gonza's voice note. Recorded: the car seat session on Meta's glasses kit simulator, with a rendered car seat. Live: what the agent does, chosen by Muse Spark Open each time. Fixed safety replies come from code, before Muse is asked. Not medical advice.",
    models: "Meta models. Live on this page: Muse Spark Open. In the car seat recording: SAM 3.1, MMS-TTS and the glasses kit. At home only: Perception Encoder Audio and the sensor on the Muse Gadget SDK.",
    rec: "Recorded on Meta's glasses kit simulator", recNote: "A rendered car seat, shortened from a real session. SAM 3.1 checks each step on camera, and the coach speaks through MMS-TTS. It never says the seat is safe. The glasses display is in Spanish.", close: "Close", end: "That's the story. Keep sending events, write from a phone, or start over.", busy: "Setting up your own simulated home", voice: "Voice note, typed here", wrote: "wrote", ended: "This session ended. Press Start over.",
    tools: {GetLiveContext: "Looked at the home", HassTurnOn: "Turned on", HassTurnOff: "Turned off", HassVacuumStart: "Started the vacuum", HassVacuumReturnToBase: "Sent the vacuum home", notify: "Messaged", say_on_echo: "Spoke on the Echo", log_baby_event: "Wrote in Theo's log", read_baby_log: "Read Theo's log", baby_summary: "Read Theo's totals", remember: "Remembered", forget: "Forgot", start_car_seat_coach: "Started the car seat coach", wake_me_at: "Asked to be woken later", next_feed: "Worked out the next feed", HassListAddItem: "Added to the list", set_on_duty: "Changed who is on duty"},
    kinds: {feeding: "Feed", diaper: "Diaper", sleep: "Sleep", bath: "Bath", note: "Note"},},
  es: {locale: "es-UY", simulated: "Simulado", lead: "Un agente del hogar para dos padres primerizos. Gonza y Ceci son padres por primera vez y Theo es su recién nacido, simulado acá. Muse Spark Open de Meta decide en vivo qué hace la casa y a quién le avisa, y nada de esto llega a una casa real.",
    play: "Reproducir una noche", stop: "Parar", playing: (i, n, s) => `${i} de ${n}: ${s}`, nightDone: "Esa fue una noche, y cada paso se decidió en vivo. Enviá cualquier evento de la casa abajo, o escribí desde un teléfono.", sure: "Tocá de nuevo para reiniciar", restarted: "Empezó de nuevo en español.", deep: "Ver cómo piensa", plain: "Volver a lo simple", empty: "Nada todavía. El agente escribe primero.",
    send2: "Enviar un evento de la casa", humLabel: "Humedad del cuarto", tempLabel: "Temperatura del cuarto", cry: "Se oye llanto", dog: "Se oyen ladridos", plug: (n, s) => `Enchufe ${n} ${s}`, am: "Revisión de la mañana", pm: "Revisión de la noche", h1: "Reloj +1 hora", h6: "Reloj +6 horas", sent: "Evento enviado", reset: "Empezar de nuevo", phoneG: "Teléfono de Gonza", phoneC: "Teléfono de Ceci", writeG: "Escribir como Gonza", writeC: "Escribir como Ceci", send: "Enviar", asleep: "No llegó nada a este teléfono", house: "La casa de Theo, simulada",
    parents: "Dormitorio", theo: "Cuarto de Theo", kitchen: "Cocina", living: "Living", dehum: "Deshumidificador", echo: "Echo", warmer: "Mamaderas", light: "Luz del escritorio", vacuum: "Aspiradora",
    on: "On", off: "Off", humidityWord: "humedad", wet: "pis", dirty: "caca", trace: "Lo que está haciendo Muse", traceEmpty: "Tocá Reproducir una noche, o enviá cualquier evento de la casa. Lo que elige Muse aparece acá a medida que ocurre.",
    memory: "Lo que Muse recuerda", memoryEmpty: "Nada todavía. Los planes que guarde quedan acá de un día para otro.", log: "Registro de Theo", rail: "Momentos de la historia", thinking: "Muse está decidiendo", failed: "Muse no respondió a este. Tocá otro momento o empezá de nuevo.",
    took: (s, t) => `${s} s, ${t} tokens`, by: "Lo decidió Muse Spark Open", byIn: s => `Lo decidió Muse Spark Open en ${s} s`, nothing: "Muse miró y eligió no hacer nada.", decided: "Nota de Muse, escrita en inglés", woke: "Muse se despertó sola, como había planeado", gate: "Respuesta fija de seguridad, desde el código. No se le preguntó a ningún modelo.",
    humid: v => `La humedad del cuarto marca ${v}%`, heat: v => `La temperatura del cuarto marca ${v} °C`, plugSet: (n, v) => `Alguien puso el enchufe ${n} en ${v}`, heard: {"baby crying": "Se oye llanto", "dog barking": "Se oyen ladridos"}, checks: {morning: "Revisión de la mañana", evening: "Revisión de la noche"}, atHome: {sound: "En casa, este evento viene de Perception Encoder Audio en el micrófono. Acá lo enviaste vos.", sensor: "En casa, este evento viene del sensor hecho con el Muse Gadget SDK de Meta. Acá lo enviaste vos."}, coachBy: "En la grabación: SAM 3.1 mira y MMS-TTS habla", duty: "De turno",
    foot: "Simulado: Theo, los sonidos, los sensores, los enchufes y los teléfonos. Escrita acá: la nota de voz de Gonza. Grabado: la sesión de la silla del auto en el simulador del kit de lentes de Meta, con una silla renderizada. En vivo: lo que hace el agente, elegido por Muse Spark Open cada vez. Las respuestas fijas de seguridad vienen del código, antes de preguntarle a Muse. No es consejo médico.",
    models: "Modelos de Meta. En vivo en esta página: Muse Spark Open. En la grabación de la silla: SAM 3.1, MMS-TTS y el kit de lentes. Solo en casa: Perception Encoder Audio y el sensor con el Muse Gadget SDK.",
    rec: "Grabado en el simulador del kit de lentes de Meta", recNote: "Una silla renderizada, acortado de una sesión real. SAM 3.1 revisa cada paso con la cámara y el coach habla con MMS-TTS. Nunca dice que la silla es segura.", close: "Cerrar", end: "Esa es la historia. Seguí enviando eventos, escribí desde un teléfono o empezá de nuevo.", busy: "Preparando tu propia casa simulada", voice: "Nota de voz, escrita acá", wrote: "escribió", ended: "Esta sesión terminó. Tocá Empezar de nuevo.",
    tools: {GetLiveContext: "Miró la casa", HassTurnOn: "Prendió", HassTurnOff: "Apagó", HassVacuumStart: "Arrancó la aspiradora", HassVacuumReturnToBase: "Mandó la aspiradora a la base", notify: "Le escribió a", say_on_echo: "Habló por el Echo", log_baby_event: "Anotó en el registro de Theo", read_baby_log: "Leyó el registro de Theo", baby_summary: "Leyó los totales de Theo", remember: "Guardó", forget: "Olvidó", start_car_seat_coach: "Arrancó el coach de la silla", wake_me_at: "Pidió que la despierten más tarde", next_feed: "Calculó la próxima comida", HassListAddItem: "Agregó a la lista", set_on_duty: "Cambió quién está de turno"},
    kinds: {feeding: "Comida", diaper: "Pañal", sleep: "Sueño", bath: "Baño", note: "Nota"},},
};
const WHO = {gonza: "Gonza", ceci: "Ceci"};
const $ = id => document.getElementById(id);
let lang = "en", state = null, stream = null, seq = 0, busy = false, seen = {gonza: 0, ceci: 0}, runs = new Map(), shownEcho = 0, pressed = null, pending = 0, lastId = null, night = null, nightTimer = 0, deep = false, phone = "gonza", unread = {gonza: false, ceci: false}, resetArmed = 0, editing = new Set();
const t = () => T[lang];
const clockOf = iso => { const [d, tm] = iso.split("T"); const [y, m, day] = d.split("-").map(Number); return {date: new Date(Date.UTC(y, m - 1, day, 12)), hm: tm.slice(0, 5), hour: Number(tm.slice(0, 2))}; };
const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.error || "Try again."), {status: r.status});
  return data;
}
function say(text, bad) { const s = $("status"); s.textContent = text || ""; s.classList.toggle("bad", !!bad); }

function words() {
  const w = t();
  document.documentElement.lang = lang;
  $("simTag").textContent = w.simulated; $("lead").textContent = w.lead; $("reset").textContent = resetArmed ? w.sure : w.reset; $("models").textContent = w.models; $("tab-gonza").textContent = "Gonza"; $("tab-ceci").textContent = "Ceci"; $("deep").textContent = deep ? w.plain : w.deep; $("play").textContent = night ? w.stop : w.play;
  const other = lang === "en" ? "Español" : "English"; $("lang").textContent = other; $("lang").lang = lang === "en" ? "es" : "en";
  $("ph-g").textContent = w.phoneG; $("ph-c").textContent = w.phoneC; $("house-title").textContent = w.house;
  $("tr-t").textContent = w.trace; $("me-t").textContent = w.memory; $("log-t").textContent = w.log; $("rail-t").textContent = w.rail; $("foot").textContent = w.foot;
  $("rec-title").textContent = w.rec; $("rec-note").textContent = w.recNote; $("rec-close").textContent = w.close;
  $("ct-t").textContent = w.send2; $("l-hum").textContent = w.humLabel; $("l-temp").textContent = w.tempLabel; $("b-cry").textContent = w.cry; $("b-dog").textContent = w.dog; $("b-am").textContent = w.am; $("b-pm").textContent = w.pm; $("b-1h").textContent = w.h1; $("b-6h").textContent = w.h6;
  document.querySelectorAll("[data-t]").forEach(n => { n.textContent = w[n.dataset.t]; });
  for (const [id, label] of [["phone-gonza", w.writeG], ["phone-ceci", w.writeC]]) {
    const f = $(id).querySelector("form"); f.querySelector("input").placeholder = label; f.querySelector("input").setAttribute("aria-label", label); f.querySelector("button").textContent = w.send;
  }
  showTrack();
  draw();
}

function drawClock() {
  const {date, hm, hour} = clockOf(state ? state.clock : "2026-12-15T21:00:00-03:00");
  $("time").textContent = hm;
  $("date").textContent = date.toLocaleDateString(t().locale, {weekday: "long", month: "long", day: "numeric", timeZone: "UTC"});
  document.body.dataset.sky = hour >= 20 || hour < 7 ? "night" : "day";
}

function drawHome() {
  if (!state) return;
  const d = state.home.devices, w = t();
  const hum = parseFloat(d["Nursery climate humidity"].state);
  $("hum").textContent = `${d["Nursery climate humidity"].state}%`; $("hum").classList.toggle("high", hum > 60);
  $("temp").textContent = `${d["Nursery climate temperature"].state} °C`;
  const set = (id, on, room) => { $(id).classList.toggle("on", on); if (room) $(room).classList.toggle("lit", on); };
  const dehum = d["Tapo P110 - Dehumidifier"].state === "on", warm = d["Tapo P110 - Bottle Warmer"].state === "on", lamp = d["Desk light"].state === "on", vac = d["Robot vacuum"].state === "cleaning";
  set("dehum", dehum); set("warmer", warm, "r-kitchen"); set("lamp", lamp); set("vacuum", vac, "r-living"); $("r-theo").classList.toggle("lit", dehum || lamp);
  $("dehum-s").textContent = dehum ? w.on : w.off; $("warmer-s").textContent = warm ? w.on : w.off;
}

function drawControls() {
  if (!state) return;
  const d = state.home.devices, w = t();
  for (const [id, out, name, unit] of [["c-hum", "v-hum", "Nursery climate humidity", "%"], ["c-temp", "v-temp", "Nursery climate temperature", " °C"]]) {
    const input = $(id), now = d[name].state;
    if (!editing.has(id)) input.value = now;
    $(out).textContent = input.value + unit;
  }
  document.querySelectorAll("[data-event=switch]").forEach(b => {
    const on = d[b.dataset.device].state === "on", label = b.id === "b-dehum" ? w.dehum : w.warmer;
    b.textContent = w.plug(label, on ? w.off : w.on); b.dataset.to = on ? "off" : "on";
  });
  document.querySelectorAll(".sends button").forEach(b => { b.disabled = busy; });
  $("c-hum").disabled = $("c-temp").disabled = busy;
}

function drawPhones(fresh) {
  if (!state) return;
  for (const p of ["gonza", "ceci"]) {
    const list = [];
    state.sent.filter(m => m.to === p).forEach((m, i) => list.push({at: m.at, text: m.text, key: i}));
    state.said.filter(m => m.from === p && !m.channel.includes("glasses")).forEach(m => list.push({at: m.at, text: m.text, mine: true, voice: m.channel.includes("voice")}));
    list.sort((a, b) => a.at.localeCompare(b.at) || (b.mine ? 1 : 0) - (a.mine ? 1 : 0));
    const box = $("phone-" + p), chat = box.querySelector(".chat"), got = state.sent.filter(m => m.to === p).length;
    chat.textContent = "";
    if (!list.length) chat.append(el("li", t().empty, "none"));
    list.forEach(m => {
      const li = el("li", m.text, m.mine ? "mine" : "");
      if (fresh && !m.mine && m.key >= seen[p]) li.classList.add("fresh");
      li.append(el("small", (m.voice ? t().voice + ", " : "") + clockOf(m.at).hm)); chat.append(li);
    });
    if (fresh && got > seen[p]) { box.classList.remove("lit"); void box.offsetWidth; box.classList.add("lit"); unread[p] = true; showPhone(p); }
    seen[p] = got;
    const screen = box.querySelector(".screen"); screen.scrollTop = screen.scrollHeight;
  }
}

function showPhone(p) {
  phone = p; unread[p] = false; document.body.dataset.phone = p;
  for (const q of ["gonza", "ceci"]) { const b = $("tab-" + q); b.setAttribute("aria-pressed", String(q === p)); b.classList.toggle("new", unread[q]); }
}

function drawEcho() {
  if (!state) return;
  const said = state.sent.filter(m => m.to === "echo");
  if (said.length > shownEcho) {
    const b = $("echo-bubble"); b.textContent = said[said.length - 1].text; b.hidden = false;
  }
  shownEcho = said.length;
}

function drawMemory() {
  if (!state) return;
  const box = $("facts"), w = t(); box.textContent = "";
  const items = Object.entries(state.facts);
  if (!items.length) box.append(el("dd", w.memoryEmpty, "empty"));
  items.forEach(([k, v]) => { box.append(el("dt", k.replace(/_/g, " ").replace(/^on duty/i, w.duty))); box.append(el("dd", v)); });
  const log = $("log"); log.textContent = "";
  state.log.slice(-6).reverse().forEach(e => {
    const {hm, date} = clockOf(e.ts), d = e.details || {};
    const what = d.amount_ml ? `${d.amount_ml} ml` : d.text || (d.solid ? w.dirty : d.wet ? w.wet : "");
    log.append(el("li", `${date.toLocaleDateString(w.locale, {weekday: "short", timeZone: "UTC"})} ${hm} ${w.kinds[e.kind] || e.kind} ${what}`));
  });
}

function drawRail() {
  const rail = $("rail"), played = state ? state.played : [], w = t(); rail.textContent = "";
  const last = played.length ? SCENES.findIndex(s => s[0] === played[played.length - 1]) : -1, next = last + 1;
  SCENES.forEach(([id, hm, , title], i) => {
    const li = el("li"), b = el("button"); b.type = "button"; b.dataset.id = id;
    b.append(el("b", hm), el("span", title[lang]));
    if (played.includes(id)) b.classList.add("done");
    if (i === next) b.classList.add("next");
    b.disabled = busy || !state; b.addEventListener("click", () => play(id));
    li.append(b); rail.append(li);
    if (i === next) requestAnimationFrame(() => { const box = rail.getBoundingClientRect(), r = b.getBoundingClientRect(); if (r.left < box.left || r.right > box.right) b.scrollIntoView({block: "nearest", inline: "center"}); });
  });
  if (state && next >= SCENES.length && !busy && !night) say(w.end);
  $("play").textContent = night ? w.stop : w.play; $("play").disabled = !state; $("play").classList.toggle("on", !!night);
}

function stepWords(s) {
  const w = t(), a = s.arguments || {}, label = w.tools[s.tool] || s.tool, name = String(a.name || "").replace("Tapo P110 - ", "");
  const said = String(a.text || "").replace(/\s*—\s*/g, ", ");  // as the phone shows it
  if (s.tool === "notify") return `${label} ${WHO[a.parent] || a.parent}: "${said}"`;
  if (s.tool === "say_on_echo") return `${label}: "${said}"`;
  if (s.tool.startsWith("HassTurn")) return `${label} ${({Dehumidifier: w.dehum, "Bottle Warmer": w.warmer})[name] || name}`;
  if (s.tool === "remember") return `${label}: ${a.value}`;
  if (s.tool === "set_on_duty") return `${label}: ${WHO[a.parent] || a.parent}, ${a.night}`;
  if (s.tool === "wake_me_at" && a.at) return `${label}, ${String(a.at).slice(11, 16)}`;
  if (s.tool === "HassListAddItem" && a.item) return `${label}: ${a.item}`;
  return label;
}

function drawTrace() {
  const box = $("trace"), w = t(); box.textContent = "";
  document.body.classList.toggle("deep", deep);
  if (!runs.size) { box.append(el("li", w.traceEmpty, "empty")); return; }
  for (const run of [...runs.values()].reverse()) {
    const li = el("li", undefined, "run"); li.append(el("b", run.title));
    li.append(el("div", clockOf(run.at).hm, "when"));
    if (run.home) li.append(el("p", w.atHome[run.home], "source"));
    li.append(el("pre", JSON.stringify(run.raw), "raw only-deep"));
    const steps = el("ul", undefined, "steps");
    run.steps.forEach(s => {
      const item = el("li"), det = el("details"), sum = el("summary");
      det.open = !!s.open; det.addEventListener("toggle", () => { s.open = det.open; });
      item.append(el("span", stepWords(s), "plain only-plain"));
      if (s.tool === "start_car_seat_coach") item.append(el("span", w.coachBy, "model only-plain"));
      sum.append(document.createTextNode(`${w.tools[s.tool] || s.tool}${s.target ? " " + s.target.replace("Tapo P110 - ", "") : ""} `), el("code", s.tool));
      det.append(sum, el("pre", JSON.stringify(s.arguments, null, 1)));
      det.classList.add("only-deep");
      item.append(det); steps.append(item);
    });
    li.append(steps);
    if (run.gate) li.append(el("p", w.gate, "decision by"));
    if (run.failed) li.append(el("p", w.failed, "decision"));
    if (run.done && !run.gate && !run.failed && !run.steps.some(s => s.tool !== "GetLiveContext")) li.append(el("p", w.nothing, "decision"));
    if (run.text) { const p = el("p", undefined, "decision only-deep"); p.append(el("em", `${w.decided}: `), document.createTextNode(run.text)); li.append(p); }
    if (run.meta && !run.gate) li.append(el("p", w.byIn(run.meta.seconds), "meta by"));
    if (run.meta) li.append(el("p", w.took(run.meta.seconds, run.meta.tokens), "meta only-deep"));
    if (!run.done) li.append(el("p", w.thinking, "meta thinking"));
    box.append(li);
  }
}

function draw(fresh) { drawClock(); drawHome(); drawControls(); drawPhones(fresh); drawEcho(); drawMemory(); drawRail(); drawTrace(); }

function titleOf(e) {
  const p = e.payload || {}, w = t();
  if (e.type === "wake") return w.woke;
  if (pressed) { const title = pressed; pressed = null; return title; }
  if (e.type === "state_changed") {
    if (p.entity_id.includes("humidity")) return w.humid(p.state);
    if (p.entity_id.includes("temperature")) return w.heat(p.state);
    return w.plugSet(p.entity_id.includes("dehumidifier") ? w.dehum : w.warmer, p.state === "on" ? w.on : w.off);
  }
  if (e.type === "sound") return w.heard[p.kind] || p.kind;
  if (e.type === "schedule") return w.checks[p.name] || p.name;
  return `${WHO[p.from] || p.from} ${w.wrote}: "${p.text}"`;
}
async function refresh(fresh) { try { state = await api("/api/state"); draw(fresh); } catch (err) { if (err.status === 410) { busy = false; say(t().ended, true); } } }

function listen() {
  if (stream) stream.close();
  stream = new EventSource(`/api/stream?after=${seq}`);
  const on = (kind, fn) => stream.addEventListener(kind, m => { const item = JSON.parse(m.data); seq = Math.max(seq, item.seq); fn(item); drawTrace(); });
  on("event", e => {
    const sensor = e.type === "state_changed" && /humidity|temperature/.test((e.payload || {}).entity_id || "");
    runs.set(e.event_id, {title: titleOf(e), raw: {type: e.type, payload: e.payload}, at: e.happened_at, steps: [], done: false, home: e.type === "sound" ? "sound" : sensor ? "sensor" : ""});
    closeRecording();
    if (e.type === "sound") { const c = $("cry"); c.classList.remove("on"); void c.getBoundingClientRect(); c.classList.add("on"); setTimeout(() => c.classList.remove("on"), 7500); }
    document.querySelectorAll(".phone").forEach(x => x.classList.remove("lit"));
    document.querySelectorAll(".asleep").forEach(x => { x.textContent = ""; });
    $("echo-bubble").hidden = true;
    refresh(false);
  });
  on("tool_call", e => { if (e.tool === "start_car_seat_coach") openRecording(); const r = runs.get(e.event_id); if (r) r.steps.push({tool: e.tool, arguments: e.arguments, target: (e.tool === "notify" ? WHO[e.arguments.parent] : (e.tool.startsWith("HassTurn") ? e.arguments.name : "")) || ""}); });
  on("tool_result", () => refresh(true));
  on("gate", e => { const r = runs.get(e.event_id); if (r) r.gate = true; refresh(true); });
  on("decision", e => { const r = runs.get(e.event_id); if (r) { r.text = e.note || e.text; r.meta = {seconds: e.seconds, tokens: e.tokens}; } });
  on("error", e => { const r = runs.get(e.event_id); if (r) r.failed = true; });
  on("done", e => {
    const r = runs.get(e.event_id); if (r) r.done = true;
    settle();
    drawRail(); drawControls();
    refresh(true).then(() => {
      if (!state) return;
      const night = clockOf(state.clock).hour < 7 || clockOf(state.clock).hour >= 22;
      if (night) document.querySelectorAll(".phone").forEach(x => { if (!x.classList.contains("lit")) { x.querySelector(".asleep").textContent = t().asleep; const screen = x.querySelector(".screen"); screen.scrollTop = screen.scrollHeight; } });
    });
  });
}

function showTrack() {
  for (const track of $("rec-video").textTracks) track.mode = track.language === lang ? "hidden" : "disabled";
  $("rec-cap").textContent = "";
}
function closeRecording() { const v = $("rec-video"); v.pause(); $("recording").hidden = true; $("rec-cap").textContent = ""; }
function openRecording() {
  const box = $("recording"), v = $("rec-video"); box.hidden = false;
  showTrack();
  v.currentTime = 0; v.muted = false;
  v.play().catch(() => { v.muted = true; v.play().catch(() => {}); });
  $("rec-close").focus();
}
for (const track of $("rec-video").textTracks) track.addEventListener("cuechange", () => {
  if (track.mode !== "hidden") return;
  const cue = track.activeCues && track.activeCues[0]; $("rec-cap").textContent = cue ? cue.text.replace(/<[^>]+>/g, "") : "";
});
$("rec-video").addEventListener("ended", closeRecording);

// Busy until the event this press sent has finished. A wake that fires on the way ends first, and doesn't count.
function settle() {
  busy = pending > 0 || [...runs.values()].some(x => !x.done) || (lastId !== null && !(runs.get(lastId) || {}).done);
  if (!busy && !night) { const s = $("status"); if (s.textContent === t().thinking) say(""); }
  if (!busy && night) nextOfNight();
}
function jumpToResult() {
  if (!matchMedia("(max-width:1279px)").matches) return;
  const target = matchMedia("(max-width:640px)").matches ? $("ptabs") : $("phone-gonza");
  target.scrollIntoView({behavior: matchMedia("(prefers-reduced-motion:reduce)").matches ? "auto" : "smooth", block: "start"});
}
async function dispatch(path, body) {
  if (busy) return;
  busy = true; pending += 1; lastId = null; if (!night) say(t().thinking); drawRail(); drawControls();
  jumpToResult();
  try { const answer = await api(path, body); lastId = answer.id ?? null; pending -= 1; await refresh(false); settle(); drawRail(); drawControls(); }
  catch (err) { pending -= 1; lastId = null; stopNight(); settle(); pressed = null; say(err.message, true); drawRail(); drawControls(); }
}
function play(id) { stopNight(); return playScene(id); }
function playScene(id) { pressed = SCENES.find(s => s[0] === id)[3][lang]; return dispatch("/api/scene", {id}); }
function sendEvent(type, payload) { stopNight(); return dispatch("/api/events", {type, payload}); }

// Play one night: the same scene events a judge can press, one at a time, each only after Muse finished the last.
function stopNight() { clearTimeout(nightTimer); if (night) { night = null; $("play").textContent = t().play; $("play").classList.remove("on"); } }
function nextOfNight() {
  clearTimeout(nightTimer);
  nightTimer = setTimeout(() => {
    if (!night) return;
    if (!night.left.length) { night = null; drawRail(); say(t().nightDone); return; }
    const id = night.left.shift(), title = SCENES.find(s => s[0] === id)[3][lang];
    say(t().playing(NIGHT.length - night.left.length, NIGHT.length, title));
    playScene(id);
  }, night && night.started ? 1800 : 0);
  if (night) night.started = true;
}
$("play").addEventListener("click", async () => {
  if (night) { stopNight(); say(""); drawRail(); return; }
  if (busy || !state) return;
  const played = state.played, begun = played.every((id, i) => id === NIGHT[i]);
  if (!begun || played.length >= NIGHT.length) { if (!(await startOver())) return; }
  night = {left: NIGHT.filter(id => !state.played.includes(id)), started: false};
  drawRail(); jumpToResult(); nextOfNight();
});

for (const [id, entity] of [["c-hum", "sensor.nursery_climate_humidity"], ["c-temp", "sensor.nursery_climate_temperature"]]) {
  $(id).addEventListener("pointerdown", () => editing.add(id));
  $(id).addEventListener("input", () => { editing.add(id); drawControls(); });
  $(id).addEventListener("change", async ev => { const value = ev.target.value; ev.target.blur(); await sendEvent("state_changed", {entity_id: entity, state: value}); editing.delete(id); drawControls(); });
}
document.querySelector(".sends").addEventListener("click", async ev => {
  const b = ev.target.closest("button"); if (!b) return;
  if (b.dataset.clock) { try { state = await api("/api/clock", {minutes: Number(b.dataset.clock)}); draw(); } catch (err) { say(err.message, true); } return; }
  if (b.dataset.event === "sound") sendEvent("sound", {kind: b.dataset.kind});
  if (b.dataset.event === "switch") sendEvent("state_changed", {entity_id: b.dataset.entity, state: b.dataset.to});
  if (b.dataset.event === "schedule") sendEvent("schedule", {name: b.dataset.name});
});

function reseed() { stopNight(); seen = {gonza: 0, ceci: 0}; shownEcho = 0; runs = new Map(); seq = 0; busy = false; pending = 0; lastId = null; editing.clear(); unread = {gonza: false, ceci: false}; showPhone("gonza"); closeRecording(); $("echo-bubble").hidden = true; document.querySelectorAll(".phone").forEach(x => x.classList.remove("lit")); document.querySelectorAll(".asleep").forEach(x => { x.textContent = ""; }); }

async function startOver() {
  say(t().busy);
  try { state = await api("/api/reset", {}); reseed(); say(""); seq = state.seq; listen(); draw(); return true; }
  catch (err) { if (err.status === 410) { state = null; reseed(); await boot(); return !!state; } say(err.message, true); return false; }
}
// Start over takes two presses, so a stray click can't wipe a run.
$("reset").addEventListener("click", async () => {
  if (!resetArmed) { $("reset").textContent = t().sure; resetArmed = setTimeout(() => { resetArmed = 0; $("reset").textContent = t().reset; }, 4000); return; }
  clearTimeout(resetArmed); resetArmed = 0; $("reset").textContent = t().reset;
  await startOver();
});
// One language at a time: changing it mid-run starts over, so the page, the messages and Muse never disagree.
$("lang").addEventListener("click", async () => {
  lang = lang === "en" ? "es" : "en";
  try { localStorage.setItem("pa-sim-lang", lang); } catch (e) { /* the choice just isn't kept */ }
  words();
  if (!state) return;
  try {
    await api("/api/lang", {lang});
    if (runs.size || state.played.length || state.sent.length || state.said.length) { if (await startOver()) say(t().restarted); }
    else state.lang = lang;
  } catch (err) { say(err.message, true); }
});
$("rec-close").addEventListener("click", closeRecording);
$("deep").addEventListener("click", () => { deep = !deep; $("deep").textContent = deep ? t().plain : t().deep; $("deep").setAttribute("aria-pressed", String(deep)); drawTrace(); });
$("ptabs").addEventListener("click", ev => { const b = ev.target.closest("button"); if (b) showPhone(b.dataset.phone); });
for (const p of ["gonza", "ceci"]) {
  $("phone-" + p).querySelector("form").addEventListener("submit", async ev => {
    ev.preventDefault();
    const input = ev.target.querySelector("input"), text = input.value.trim();
    if (!text || busy) return;
    input.value = "";
    stopNight();
    await dispatch("/api/write", {as: p, text});
  });
}
async function boot() {
  try { const s = localStorage.getItem("pa-sim-lang"); if (s === "es" || s === "en") lang = s; } catch (e) { /* defaults to English */ }
  showPhone(phone); words(); say(t().busy);
  try {
    state = await api("/api/session", {lang});
    if (state.lang !== lang) { await api("/api/lang", {lang}); state.lang = lang; }
    say(""); seq = state.seq; seen = {gonza: state.sent.filter(m => m.to === "gonza").length, ceci: state.sent.filter(m => m.to === "ceci").length};
    listen(); draw();
  } catch (err) { say(err.message, true); }
}
boot();
