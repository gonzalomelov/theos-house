"use strict";
const SCENES = [
  ["evening", "21:30", "Tue", {en: "Plan for tonight", es: "El plan de esta noche"}],
  ["sleep", "21:45", "Tue", {en: "Ceci asks to sleep", es: "Ceci pide dormir"}],
  ["cry", "02:50", "Wed", {en: "Theo cries", es: "Theo llora"}],
  ["feed", "03:20", "Wed", {en: "Gonza's voice note", es: "La nota de voz de Gonza"}],
  ["morning", "07:30", "Wed", {en: "Morning", es: "La mañana"}],
  ["grandma", "11:00", "Wed", {en: "Grandma asks the Echo", es: "La abuela le pregunta al Echo"}],
  ["humid", "15:10", "Wed", {en: "Humidity rises to 71%", es: "La humedad sube a 71%"}],
  ["recipe", "16:30", "Wed", {en: "Grandma's recipe", es: "La receta de la abuela"}],
  ["dry", "17:40", "Wed", {en: "Humidity falls to 49.5%", es: "La humedad baja a 49,5%"}],
  ["carseat", "18:10", "Wed", {en: "Help with the car seat", es: "Ayuda con la silla del auto"}],
  ["evening2", "21:30", "Wed", {en: "The next evening", es: "La noche siguiente"}],
];
const ORDER = SCENES.map(s => s[0]);
const T = {
  en: {locale: "en-US", simulated: "Simulated", lead: "Gonza and Ceci are expecting their first baby in December. Here it is already December: press Play and watch their home agent get them through a night and the next day with Theo, a newborn simulated on this page. Muse, Meta's AI, decides live, and nothing here reaches a real house.",
    play: "Play the story", stop: "Stop", playing: (i, n, s) => `${i} of ${n}: ${s}`, storyDone: "That was a night and a day, every step decided live. Now send any home event, write from a phone, or try the models below.", past: "past", alarmWord: "Alarm", restarted: "Started over, in a new home.", langNow: "New messages will be in English. Earlier ones stay as they were written.", deep: "See how it thinks", plain: "Back to plain", empty: "Nothing yet. The agent writes first.",
    send2: "Send a home event", humLabel: "Nursery humidity", tempLabel: "Nursery temperature", cry: "Crying heard", dog: "Barking heard", plug: (n, s) => `${n} plug ${s}`, am: "Morning check", pm: "Evening check", h1: "Clock +1 hour", h6: "Clock +6 hours", sent: "Event sent", reset: "Start over", phoneG: "Gonza's phone", phoneC: "Ceci's phone", writeG: "Write as Gonza", writeC: "Write as Ceci", send: "Send", asleep: "Nothing sent to this phone", house: "Theo's house, simulated",
    parents: "Parents' room", theo: "Theo's room", kitchen: "Kitchen", living: "Living room", dehum: "Dehumidifier", echo: "Echo", warmer: "Bottle warmer", light: "Desk light", vacuum: "Robot vacuum",
    on: "On", off: "Off", humidityWord: "humidity", wet: "wet", dirty: "dirty", trace: "What Muse is doing", traceEmpty: "Press Play the story, or send any home event. What Muse chooses shows up here as it happens.",
    memory: "What Muse remembers", memoryEmpty: "Nothing yet. Plans it keeps will stay here across days.", log: "Theo's log", rail: "Moments from the story", thinking: "Muse is deciding", failed: "Muse didn't answer this one. Press another moment, or start over.",
    took: (s, t) => `${s} s, ${t} tokens`, by: "Decided by Muse Spark Open", byIn: s => `Decided by Muse Spark Open in ${s} s`, nothing: "Muse looked and chose to do nothing.", decided: "Muse's note", woke: "Muse woke itself up, as it had planned", gate: "A safety reply, written in advance.", gateDeep: "Only this fixed line went out. No model was asked.", source: "See the guidance",
    humid: v => `Nursery humidity reads ${v}%`, heat: v => `Nursery temperature reads ${v} °C`, plugSet: (n, v) => `Someone switched the ${n} plug ${v}`, heard: {"baby crying": "Crying heard", "dog barking": "Barking heard", "doorbell ringing": "Doorbell heard"}, checks: {morning: "Morning check", evening: "Evening check"}, atHome: {sound: "At home, this event comes from Perception Encoder Audio on the microphone. Here you sent it.", sensor: "At home, this event comes from the sensor built on Meta's Muse Gadget SDK. Here you sent it."}, coachBy: "In the recording: SAM 3.1 watches and MMS-TTS speaks", duty: "On duty",
    foot: "Simulated: Theo and his feeds, the sounds, the sensors, the plugs and the phones. Typed here: Gonza's voice note. Computed earlier: Perception Encoder Audio and SAM 3.1 on the clips below. Recorded: the car seat session on Meta's glasses kit simulator, with a rendered car seat. Live: what the agent does, chosen by Muse Spark Open each time. Fixed safety replies come from code, before Muse is asked. Not medical advice.",
    models: "Meta models. Live on this page: Muse Spark Open. Computed earlier, results here: Perception Encoder Audio and SAM 3.1. In the car seat recording: SAM 3.1, MMS-TTS and the glasses kit. At home only: the sensor on the Muse Gadget SDK.",
    rec: "Recorded on Meta's glasses kit simulator", recNote: "A rendered car seat, shortened from a real session. SAM 3.1 checks each step on camera, and the coach speaks through MMS-TTS. It never says the seat is safe. The voice and the glasses display are in Spanish, and the English is under the video.", close: "Close", end: "That's the story. Keep sending events, write from a phone, or start over.", busy: "Setting up your own simulated home", voice: "Voice note, typed here", wrote: "wrote", ended: "That home had timed out, so this is a fresh one.",
    tools: {GetLiveContext: "Looked at the home", HassTurnOn: "Turned on", HassTurnOff: "Turned off", HassVacuumStart: "Started the vacuum", HassVacuumReturnToBase: "Sent the vacuum home", notify: "Messaged", say_on_echo: "Spoke on the Echo", log_baby_event: "Wrote in Theo's log", read_baby_log: "Read Theo's log", baby_summary: "Read Theo's totals", remember: "Remembered", forget: "Forgot", start_car_seat_coach: "Started the car seat coach", wake_me_at: "Muse set a reminder for itself", vacuum_identify: "Asked the vacuum to say here it is", next_feed: "Worked out the next feed", HassListAddItem: "Added to the list", set_on_duty: "Changed who is on duty", preview_family_recipe: "Showed the recipe as a preview"},
    toolOther: "Used one of its tools", recOpen: "Watch the car seat clip again", queued: n => `Muse is still deciding. ${n} waiting, they go in order.`, already: "That one is already waiting.", queueFull: "Too many waiting. Give Muse a moment.", seePhones: "See the phones", planWord: "Plan", noteWord: "Handover note",
    kinds: {feeding: "Feed", diaper: "Diaper", sleep: "Sleep", bath: "Bath", note: "Note"},
    feedsOff: "Stop Theo's simulated feeds", feedsOn: "Resume Theo's simulated feeds", feedsNote: "Nobody logs a feed now. Move the clock, and see what the home does.", feedsSim: "simulated", endedTitle: {warmer_off_at: "The bottle warmer turned itself off", vacuum_off_at: "The vacuum finished"}, gapTitle: "No feed in the log for a long time", fixed: "Fixed line from code", fixedTo: "to", result: "What came back", metaT: "What Meta's models do here", metaSum: "Each model and its proof", metaLead: "Only Muse runs live on this page. The others ran earlier, on our own machines, and each result here says how it was made.", muse: ["Muse Spark Open", "Live", "Decides every step in this page and in our home, through tools. Every step shows under What Muse is doing."], pe: ["Perception Encoder Audio", "Computed earlier", "On this recording, through the camera's audio channel: a baby crying, at 99.9%. At home, on Nov 3, it heard a cry played in the room through a real Tapo microphone. That's one test, not a rate."], sam: ["SAM 3.1", "Computed earlier", "Honey shows the hands, teal the baby. The hand alarm at the changing table, on 80 recordings: 33 of 51 caught within 2.5 s, 42 within 5 s, and no false alarms in 29. The bath isn't claimed: it missed too many. A generated clip, no real baby."], gadget: ["Muse Gadget SDK", "Real, at home", "The humidity and temperature sensor in Theo's room runs on Gadget SDK firmware and reports to Home Assistant. In our home, Muse read it and switched a real plug. Here the readings are simulated."], tts: ["MMS-TTS", "Computed earlier", "Meta's voice model says the coach's lines. This one was generated on our server, nothing is added to it."], archLink: "See the architecture", where: "In Uruguay, where this home is, the emergency number is 911.",
    now: "now", refused: "Stopped by a check in code, not sent", wait: "Muse is deciding. The buttons come back when it finishes.", left: (n, s) => `${n} events left in this home.${s === null || s > 5 ? "" : ` Start over makes a new one, ${s} more this hour.`}`, night2: (d, m) => `On duty, ${m} ${d}`, months: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], finished: "Finished. Close it to go on.",
    toSenses: "Try Meta's models on recorded sounds and a generated clip", seT: "Meta's models on recorded sounds and a generated clip", seNote: "Perception Encoder Audio and SAM 3.1 are too heavy for this page, so they ran earlier on our Mac, on these clips: the sounds are real recordings, the changing table video is generated. Sending a result puts it in as the event the home would send, and Muse decides live what to do and what to remember.", seBy: {audio: "Computed earlier by Perception Encoder Audio", frame: "Computed earlier by SAM 3.1"}, seSend: "Send to Muse", seNone: "Nothing reached its threshold, so this wakes nobody.", heardAs: {cry: "a baby crying", dog: "a dog barking", doorbell: "a doorbell", splash: "water"}, seHeard: (what, p) => `It heard ${what}, at ${p}%.`, seFrame: {"hands-on": "Hands on the baby", "hands-off": "Hands leave the baby"}, seAudio: {cry: "A newborn crying", dog: "A dog barking", doorbell: "A doorbell", kitchen: "A kitchen"}, seSaw: {on: "Its verdict: a hand is on the baby.", off: "Its verdict: no hand is on the baby.", unsure: "Its verdict: it can't tell."}, seMasks: n => `Honey shows ${n} hand masks, teal shows the baby. Original on the left.`, seGen: "A generated clip, no real baby.", computed: "This result was computed earlier by Meta's model on a saved clip. Muse's decision below is live.", camera: p => `SAM 3.1 at ${p.camera}: ${p.saw}`,},
  es: {locale: "es-UY", simulated: "Simulado", lead: "Gonza y Ceci esperan su primer bebé para diciembre. Acá ya es diciembre: apretá Play y mirá cómo el agente de su casa los ayuda a pasar una noche y el día siguiente con Theo, un recién nacido simulado en esta página. Muse, la IA de Meta, decide en vivo, y nada de esto llega a una casa real.",
    play: "Reproducir la historia", stop: "Parar", playing: (i, n, s) => `${i} de ${n}: ${s}`, storyDone: "Eso fue una noche y un día, cada paso decidido en vivo. Ahora enviá cualquier evento de la casa, escribí desde un teléfono o probá los modelos de abajo.", past: "pasó", alarmWord: "Alarma", restarted: "Empezó de nuevo, en otra casa.", langNow: "Los mensajes nuevos van en español. Los anteriores quedan como se escribieron.", deep: "Ver cómo piensa", plain: "Volver a lo simple", empty: "Nada todavía. El agente escribe primero.",
    send2: "Enviar un evento de la casa", humLabel: "Humedad del cuarto", tempLabel: "Temperatura del cuarto", cry: "Se oye llanto", dog: "Se oyen ladridos", plug: (n, s) => `Enchufe ${n} ${s}`, am: "Revisión de la mañana", pm: "Revisión de la noche", h1: "Reloj +1 hora", h6: "Reloj +6 horas", sent: "Evento enviado", reset: "Empezar de nuevo", phoneG: "Teléfono de Gonza", phoneC: "Teléfono de Ceci", writeG: "Escribir como Gonza", writeC: "Escribir como Ceci", send: "Enviar", asleep: "No llegó nada a este teléfono", house: "La casa de Theo, simulada",
    parents: "Dormitorio", theo: "Cuarto de Theo", kitchen: "Cocina", living: "Living", dehum: "Deshumidificador", echo: "Echo", warmer: "Mamaderas", light: "Luz del escritorio", vacuum: "Aspiradora",
    on: "On", off: "Off", humidityWord: "humedad", wet: "pis", dirty: "caca", trace: "Lo que está haciendo Muse", traceEmpty: "Tocá Reproducir la historia, o enviá cualquier evento de la casa. Lo que elige Muse aparece acá a medida que ocurre.",
    memory: "Lo que Muse recuerda", memoryEmpty: "Nada todavía. Los planes que guarde quedan acá de un día para otro.", log: "Registro de Theo", rail: "Momentos de la historia", thinking: "Muse está decidiendo", failed: "Muse no respondió a este. Tocá otro momento o empezá de nuevo.",
    took: (s, t) => `${s} s, ${t} tokens`, by: "Lo decidió Muse Spark Open", byIn: s => `Lo decidió Muse Spark Open en ${s} s`, nothing: "Muse miró y eligió no hacer nada.", decided: "Nota de Muse, escrita en inglés", woke: "Muse se despertó sola, como había planeado", gate: "Una respuesta de seguridad, escrita de antemano.", gateDeep: "Solo salió esta línea fija. No se le preguntó a ningún modelo.", source: "Ver la guía",
    humid: v => `La humedad del cuarto marca ${v}%`, heat: v => `La temperatura del cuarto marca ${v} °C`, plugSet: (n, v) => `Alguien puso el enchufe ${n} en ${v}`, heard: {"baby crying": "Se oye llanto", "dog barking": "Se oyen ladridos", "doorbell ringing": "Se oye el timbre"}, checks: {morning: "Revisión de la mañana", evening: "Revisión de la noche"}, atHome: {sound: "En casa, este evento viene de Perception Encoder Audio en el micrófono. Acá lo enviaste vos.", sensor: "En casa, este evento viene del sensor hecho con el Muse Gadget SDK de Meta. Acá lo enviaste vos."}, coachBy: "En la grabación: SAM 3.1 mira y MMS-TTS habla", duty: "De turno",
    foot: "Simulado: Theo y sus comidas, los sonidos, los sensores, los enchufes y los teléfonos. Escrita acá: la nota de voz de Gonza. Calculado antes: Perception Encoder Audio y SAM 3.1 con los clips de abajo. Grabado: la sesión de la silla del auto en el simulador del kit de lentes de Meta, con una silla renderizada. En vivo: lo que hace el agente, elegido por Muse Spark Open cada vez. Las respuestas fijas de seguridad vienen del código, antes de preguntarle a Muse. No es consejo médico.",
    models: "Modelos de Meta. En vivo en esta página: Muse Spark Open. Calculados antes, con el resultado acá: Perception Encoder Audio y SAM 3.1. En la grabación de la silla: SAM 3.1, MMS-TTS y el kit de lentes. Solo en casa: el sensor con el Muse Gadget SDK.",
    rec: "Grabado en el simulador del kit de lentes de Meta", recNote: "Una silla renderizada, acortado de una sesión real. SAM 3.1 revisa cada paso con la cámara y el coach habla con MMS-TTS. Nunca dice que la silla es segura.", close: "Cerrar", end: "Esa es la historia. Seguí enviando eventos, escribí desde un teléfono o empezá de nuevo.", busy: "Preparando tu propia casa simulada", voice: "Nota de voz, escrita acá", wrote: "escribió", ended: "Esa casa había expirado, así que esta es una nueva.",
    tools: {GetLiveContext: "Miró la casa", HassTurnOn: "Prendió", HassTurnOff: "Apagó", HassVacuumStart: "Arrancó la aspiradora", HassVacuumReturnToBase: "Mandó la aspiradora a la base", notify: "Le escribió a", say_on_echo: "Habló por el Echo", log_baby_event: "Anotó en el registro de Theo", read_baby_log: "Leyó el registro de Theo", baby_summary: "Leyó los totales de Theo", remember: "Guardó", forget: "Olvidó", start_car_seat_coach: "Arrancó el coach de la silla", wake_me_at: "Muse se puso un recordatorio", vacuum_identify: "Le pidió a la aspiradora que avise dónde está", next_feed: "Calculó la próxima comida", HassListAddItem: "Agregó a la lista", set_on_duty: "Cambió quién está de turno", preview_family_recipe: "Mostró la receta como vista previa"},
    toolOther: "Usó una de sus herramientas", recOpen: "Ver de nuevo el clip de la silla", queued: n => `Muse sigue decidiendo. ${n} en espera, van en orden.`, already: "Ese ya está en espera.", queueFull: "Hay demasiados en espera. Dale un momento a Muse.", seePhones: "Ver los teléfonos", planWord: "Plan", noteWord: "Nota del cambio",
    kinds: {feeding: "Comida", diaper: "Pañal", sleep: "Sueño", bath: "Baño", note: "Nota"},
    feedsOff: "Parar las comidas simuladas de Theo", feedsOn: "Volver a las comidas simuladas de Theo", feedsNote: "Ahora nadie anota comidas. Mové el reloj y mirá qué hace la casa.", feedsSim: "simulada", endedTitle: {warmer_off_at: "El calentador de mamaderas se apagó solo", vacuum_off_at: "La aspiradora terminó"}, gapTitle: "Hace mucho que no hay comidas en el registro", fixed: "Línea fija, desde el código", fixedTo: "a", result: "Lo que volvió", metaT: "Qué hacen acá los modelos de Meta", metaSum: "Cada modelo y su prueba", metaLead: "En esta página solo Muse corre en vivo. Los otros corrieron antes, en nuestras máquinas, y cada resultado dice cómo se hizo.", muse: ["Muse Spark Open", "En vivo", "Decide cada paso en esta página y en nuestra casa, con herramientas. Cada paso se ve en Lo que está haciendo Muse."], pe: ["Perception Encoder Audio", "Calculado antes", "Con esta grabación, por el canal de audio de la cámara: un bebé llorando, con 99,9%. En casa, el 3 de noviembre, oyó un llanto reproducido en el cuarto con un micrófono Tapo real. Es una prueba, no una tasa."], sam: ["SAM 3.1", "Calculado antes", "Miel marca las manos, verde al bebé. La alarma de manos en el cambiador, con 80 grabaciones: 33 de 51 en menos de 2,5 s, 42 en menos de 5 s, y ninguna falsa en 29. El baño no se afirma: falló demasiado. Un clip generado, sin un bebé real."], gadget: ["Muse Gadget SDK", "Real, en casa", "El sensor de humedad y temperatura del cuarto de Theo corre firmware del Gadget SDK y reporta a Home Assistant. En nuestra casa, Muse lo leyó y prendió un enchufe real. Acá las lecturas son simuladas."], tts: ["MMS-TTS", "Calculado antes", "El modelo de voz de Meta dice las líneas del coach. Esta se generó en nuestro servidor, sin agregarle nada."], archLink: "Ver la arquitectura", where: "En Uruguay, donde está esta casa, el número de emergencias es 911.",
    now: "ahora", refused: "Lo frenó una revisión en el código, no se envió", wait: "Muse está decidiendo. Los botones vuelven cuando termina.", left: (n, s) => `Quedan ${n} eventos en esta casa.${s === null || s > 5 ? "" : ` Empezar de nuevo crea otra, ${s} más esta hora.`}`, night2: (d, m) => `De turno, ${d} ${m}`, months: ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"], finished: "Terminó. Cerralo para seguir.",
    toSenses: "Probá los modelos de Meta con sonidos grabados y un clip generado", seT: "Los modelos de Meta con sonidos grabados y un clip generado", seNote: "Perception Encoder Audio y SAM 3.1 son muy pesados para esta página, así que corrieron antes en nuestra Mac, con estos clips: los sonidos son grabaciones reales, el video del cambiador es generado. Al enviar un resultado entra como el evento que mandaría la casa, y Muse decide en vivo qué hacer y qué recordar.", seBy: {audio: "Calculado antes por Perception Encoder Audio", frame: "Calculado antes por SAM 3.1"}, seSend: "Enviar a Muse", seNone: "Nada llegó a su umbral, así que esto no despierta a nadie.", heardAs: {cry: "un bebé llorando", dog: "un perro ladrando", doorbell: "un timbre", splash: "agua"}, seHeard: (what, p) => `Oyó ${what}, con ${p}%.`, seFrame: {"hands-on": "Manos sobre el bebé", "hands-off": "Las manos dejan al bebé"}, seAudio: {cry: "Un recién nacido llorando", dog: "Un perro ladrando", doorbell: "Un timbre", kitchen: "Una cocina"}, seSaw: {on: "Su veredicto: hay una mano sobre el bebé.", off: "Su veredicto: ninguna mano está sobre el bebé.", unsure: "Su veredicto: no puede saberlo."}, seMasks: n => `Miel marca ${n} máscaras de manos, verde marca al bebé. El original a la izquierda.`, seGen: "Un clip generado, sin un bebé real.", computed: "Este resultado lo calculó antes el modelo de Meta con un clip guardado. La decisión de Muse de abajo es en vivo.", camera: p => `SAM 3.1 en ${p.camera}: ${p.saw}`,},
};
const WHO = {gonza: "Gonza", ceci: "Ceci", echo: "Echo"};
const $ = id => document.getElementById(id);
let lang = "en", state = null, stream = null, seq = 0, busy = false, seen = {gonza: 0, ceci: 0}, runs = new Map(), shownEcho = 0, pressed = null, pending = 0, lastId = null, night = null, nightTimer = 0, deep = false, phone = "gonza", unread = {gonza: false, ceci: false}, resetArmed = 0, editing = new Set(), bootSeq = 0, lastItem = 0, senses = null, waiting = [];
const isoOf = s => `2026-12-${s[2] === "Tue" ? 15 : 16}T${s[1]}:00-03:00`;
const t = () => T[lang];
const clockOf = iso => { const [d, tm] = iso.split("T"); const [y, m, day] = d.split("-").map(Number); return {date: new Date(Date.UTC(y, m - 1, day, 12)), hm: tm.slice(0, 5), hour: Number(tm.slice(0, 2))}; };
// A long address reads as a wall of text on a phone, so it shows as a short link.
const withLinks = (node, text) => String(text).split(/(https?:\/\/\S+)/).forEach((part, i) => {
  if (i % 2) { const a = el("a", t().source); a.href = part; a.target = "_blank"; a.rel = "noopener"; node.append(a); }
  else if (part) node.append(document.createTextNode(part));
});
const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {cache: "no-store"} : {method: "POST", cache: "no-store", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.error || "Try again."), {status: r.status});
  return data;
}
function say(text, bad) { for (const s of [$("status"), $("ct-status")]) { s.textContent = text || ""; s.classList.toggle("bad", !!bad); } }

function words() {
  const w = t();
  document.documentElement.lang = lang;
  $("simTag").textContent = w.simulated; $("lead").textContent = w.lead; $("reset").textContent = w.reset; $("models").textContent = w.models; $("tab-gonza").textContent = "Gonza"; $("tab-ceci").textContent = "Ceci"; $("deep").textContent = deep ? w.plain : w.deep; $("play").textContent = playLabel();
  const other = lang === "en" ? "Español" : "English"; $("lang").textContent = other; $("lang").lang = lang === "en" ? "es" : "en";
  $("ph-g").textContent = w.phoneG; $("ph-c").textContent = w.phoneC; $("house-title").textContent = w.house;
  $("tr-t").textContent = w.trace; $("me-t").textContent = w.memory; $("log-t").textContent = w.log; $("rail-t").textContent = w.rail; $("foot").textContent = w.foot;
  $("rec-title").textContent = w.rec; $("rec-note").textContent = w.recNote; $("rec-close").textContent = w.close;
  $("to-senses").textContent = w.toSenses; $("rec-open").textContent = w.recOpen; $("ct-see").textContent = w.seePhones; $("se-t").textContent = w.seT; $("se-note").textContent = w.seNote; $("ct-t").textContent = w.send2; $("l-hum").textContent = w.humLabel; $("l-temp").textContent = w.tempLabel; $("b-cry").textContent = w.cry; $("b-dog").textContent = w.dog; $("b-am").textContent = w.am; $("b-pm").textContent = w.pm; $("b-1h").textContent = w.h1; $("b-6h").textContent = w.h6;
  document.querySelectorAll("[data-t]").forEach(n => { n.textContent = w[n.dataset.t]; });
  for (const [id, label] of [["phone-gonza", w.writeG], ["phone-ceci", w.writeC]]) {
    const f = $(id).querySelector("form"); f.querySelector("input").placeholder = label; f.querySelector("input").setAttribute("aria-label", label); f.querySelector("button").textContent = w.send;
  }
  showTrack();
  drawMeta();
  drawSenses();
  draw();
}

function playLabel() {
  const w = t();
  return night ? w.stop : w.play;
}

function drawClock() {
  const {date, hm, hour} = clockOf(state ? state.clock : "2026-12-15T21:00:00-03:00");
  $("time").textContent = hm;
  $("date").textContent = date.toLocaleDateString(t().locale, {weekday: "long", month: "long", day: "numeric", timeZone: "UTC"});
  document.body.dataset.sky = hour >= 20 || hour < 7 ? "night" : "day";
}

function drawHome() {
  if (!state) { for (const id of ["hum", "temp", "dehum-s", "warmer-s"]) $(id).textContent = "…"; return; }
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
  const d = state ? state.home.devices : null, w = t(), off = !state;  // a press while Muse decides waits its turn, it is never lost
  for (const [id, out, name, unit] of [["c-hum", "v-hum", "Nursery climate humidity", "%"], ["c-temp", "v-temp", "Nursery climate temperature", " °C"]]) {
    const input = $(id);
    if (d && !editing.has(id)) input.value = d[name].state;
    $(out).textContent = d ? input.value + unit : "…";
    input.disabled = off;
  }
  document.querySelectorAll("[data-event=switch]").forEach(b => {
    const on = d ? d[b.dataset.device].state === "on" : false, label = b.id === "b-dehum" ? w.dehum : w.warmer;
    b.textContent = w.plug(label, on ? w.off : w.on); b.dataset.to = on ? "off" : "on";
  });
  document.querySelectorAll(".sends button, .say button, .se-send").forEach(b => { b.disabled = off || b.dataset.none === "1"; });
  if (state) { const f = $("b-feeds"); f.textContent = state.feeds_on ? w.feedsOff : w.feedsOn; f.dataset.on = state.feeds_on ? "0" : "1"; }
  $("left").textContent = state ? w.left(state.events_left, state.starts_left ?? null) : "";
  document.body.classList.toggle("busy", busy);
}

function drawPhones(fresh) {
  if (!state) { document.querySelectorAll(".chat").forEach(c => { c.textContent = ""; c.append(el("li", t().busy, "none")); }); return; }
  const lit = [];
  for (const p of ["gonza", "ceci"]) {
    const list = [];
    state.sent.filter(m => m.to === p).forEach((m, i) => list.push({at: m.at, text: m.text, key: i}));
    state.said.filter(m => m.from === p && !m.channel.includes("glasses")).forEach(m => list.push({at: m.at, text: m.text, mine: true, voice: m.channel.includes("voice")}));
    list.sort((a, b) => a.at.localeCompare(b.at) || (b.mine ? 1 : 0) - (a.mine ? 1 : 0));
    const box = $("phone-" + p), chat = box.querySelector(".chat"), got = state.sent.filter(m => m.to === p).length;
    chat.textContent = "";
    if (!list.length) chat.append(el("li", t().empty, "none"));
    list.forEach(m => {
      const li = el("li", undefined, m.mine ? "mine" : "");
      withLinks(li, m.text);
      if (fresh && !m.mine && m.key >= seen[p]) li.classList.add("fresh");
      li.append(el("small", (m.voice ? t().voice + ", " : "") + clockOf(m.at).hm)); chat.append(li);
    });
    if (fresh && got > seen[p]) { box.classList.remove("lit"); void box.offsetWidth; box.classList.add("lit"); unread[p] = true; lit.push(p); }
    seen[p] = got;
    const screen = box.querySelector(".screen"); screen.scrollTop = screen.scrollHeight;
  }
  if (lit.length) showPhone(lit.includes(phone) ? phone : lit[0]);  // whoever is reading keeps their phone when both light up
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

// One line per fact. Muse may keep the rota under its own key too, and then its longer sentence is the one shown.
function factLabel(k) {
  const m = k.match(/^(?:on[ _])?duty[ _](\d{4})[-_ ](\d\d)[-_ ](\d\d)$/i), w = t(), alarm = k.match(/^alarm_\d{8}(\d\d)(\d\d)$/);
  if (k.startsWith("plan_")) return w.planWord;
  if (k.startsWith("duty_note_")) return w.noteWord;
  if (m) return w.night2(Number(m[3]), w.months[Number(m[2]) - 1]);
  if (alarm) return `${w.alarmWord} ${alarm[1]}:${alarm[2]}`;
  const words_ = k.replace(/[_-]+/g, " ").trim();
  return words_.charAt(0).toUpperCase() + words_.slice(1);
}
function drawMemory() {
  const box = $("facts"), w = t(); box.textContent = "";
  if (!state) { box.append(el("dd", w.memoryEmpty, "empty")); $("log").textContent = ""; return; }
  const shown = new Map();
  Object.entries(state.facts).forEach(([k, v]) => { const label = factLabel(k), text = String(v), had = shown.get(label); shown.set(label, had && had.length > text.length ? had : (WHO[text] || text)); });
  if (!shown.size) box.append(el("dd", w.memoryEmpty, "empty"));
  shown.forEach((v, k) => { box.append(el("dt", k)); box.append(el("dd", v)); });
  const log = $("log"); log.textContent = "";
  state.log.slice(-6).reverse().forEach(e => {
    const {hm, date} = clockOf(e.ts), d = e.details || {};
    const what = d.amount_ml ? `${d.amount_ml} ml${d.simulated ? `, ${w.feedsSim}` : ""}` : d.text || (d.solid ? w.dirty : d.wet ? w.wet : "");
    log.append(el("li", `${date.toLocaleDateString(w.locale, {weekday: "short", timeZone: "UTC"})} ${hm} ${w.kinds[e.kind] || e.kind} ${what}`));
  });
}

function drawRail() {
  const rail = $("rail"), played = state ? state.played : [], w = t(); rail.textContent = "";
  const last = played.length ? SCENES.findIndex(s => s[0] === played[played.length - 1]) : -1, next = last + 1;
  SCENES.forEach((scene, i) => {
    const [id, hm, , title] = scene, li = el("li"), b = el("button"); b.type = "button"; b.dataset.id = id;
    // A moment whose time has passed is over: the rail is the story's, and the clock only goes forward.
    const over = state && !played.includes(id) && isoOf(scene) <= state.clock;
    b.append(el("b", played.includes(id) ? "✓" : over ? w.past : hm), el("span", title[lang]));
    if (played.includes(id) || over) b.classList.add("done");
    if (i === next && !over) b.classList.add("next");
    b.disabled = !state || played.includes(id) || over; b.addEventListener("click", () => play(id));
    li.append(b); rail.append(li);
    if (i === next) requestAnimationFrame(() => { const box = rail.getBoundingClientRect(), r = b.getBoundingClientRect(); if (r.left < box.left || r.right > box.right) rail.scrollLeft += r.left - box.left - (box.width - r.width) / 2; });  // only sideways: the page stays where the visitor is
  });
  if (state && next >= SCENES.length && !busy && !night) say(w.end);
  $("play").textContent = playLabel(); $("play").disabled = !state; $("play").classList.toggle("on", !!night);
}

function stepWords(s) {
  const w = t(), a = s.arguments || {}, label = w.tools[s.tool] || w.toolOther, name = String(a.name || "").replace("Tapo P110 - ", "");
  const said = String(a.text || "").replace(/\s*—\s*/g, ", ");  // as the phone shows it
  if (s.fixed) return `${w.fixed}, ${w.fixedTo} ${s.to.map(p => WHO[p] || p).join(", ")}: "${said}"`;
  if (s.refused) return `${w.refused}: "${said || label}"`;
  if (s.tool === "notify") return `${label} ${WHO[a.parent] || a.parent}: "${said}"`;
  if (s.tool === "say_on_echo") return `${label}: "${said}"`;
  if (s.tool.startsWith("HassTurn")) return `${label} ${({Dehumidifier: w.dehum, "Bottle Warmer": w.warmer})[name] || name}`;
  if (s.tool === "remember") return `${label}: ${a.value}`;
  if (s.tool === "forget") return `${label}: ${factLabel(String(a.key || ""))}`;
  if (s.tool === "set_on_duty") return `${label}: ${WHO[a.parent] || a.parent}, ${a.night}`;
  if (s.tool === "wake_me_at" && a.at) return `${label}, ${String(a.at).slice(11, 16)}`;
  if (s.tool === "HassListAddItem" && a.item) return `${label}: ${a.item}`;
  return label;
}

function drawTrace() {
  const box = $("trace"), w = t(); box.textContent = "";
  document.body.classList.toggle("deep", deep);
  $("rec-open").hidden = ![...runs.values()].some(r => r.steps.some(s => s.tool === "start_car_seat_coach"));
  if (!runs.size) { box.append(el("li", w.traceEmpty, "empty")); return; }
  // Newest first by the moment it happened, whatever order the events finished in.
  for (const run of [...runs.values()].sort((a, b) => b.at.localeCompare(a.at) || b.id - a.id)) {
    const li = el("li", undefined, "run"); li.append(el("b", run.title));
    li.append(el("div", clockOf(run.at).hm, "when"));
    if (run.home) li.append(el("p", run.home === "computed" ? w.computed : w.atHome[run.home], "source"));
    li.append(el("pre", JSON.stringify(run.raw), "raw only-deep"));
    const steps = el("ul", undefined, "steps");
    run.steps.forEach(s => {
      const unsent = s.refused || (run.done && s.tool === "notify" && s.result === undefined);  // the trace shows what the phones show
      const item = el("li", undefined, unsent ? "only-deep" : undefined), det = el("details"), sum = el("summary");
      det.open = !!s.open; det.addEventListener("toggle", () => { s.open = det.open; });
      item.append(el("span", stepWords(s), `plain only-plain${s.refused ? " refused" : ""}`));
      if (s.tool === "start_car_seat_coach") item.append(el("span", w.coachBy, "model only-plain"));
      sum.append(document.createTextNode(`${w.tools[s.tool] || w.toolOther}${s.target ? " " + s.target.replace("Tapo P110 - ", "") : ""} `), el("code", s.tool));
      det.append(sum, el("pre", JSON.stringify(s.arguments, null, 1)));
      if (s.result) det.append(el("pre", `${w.result}: ${s.result}`));
      det.classList.add("only-deep");
      item.append(det); steps.append(item);
    });
    li.append(steps);
    if (run.gated) li.append(el("p", w.gateDeep, "decision by only-deep"));
    if (run.failed) li.append(el("p", w.failed, "decision"));
    if (run.done && !run.gated && !run.failed && !run.steps.some(s => s.tool !== "GetLiveContext" && !s.refused)) li.append(el("p", w.nothing, "decision"));
    if (run.text) { const p = el("p", undefined, "decision only-deep"); p.append(el("em", `${w.decided}: `), document.createTextNode(run.text)); li.append(p); }
    if (run.meta) li.append(el("p", w.byIn(run.meta.seconds), "meta by"));
    if (run.meta) li.append(el("p", w.took(run.meta.seconds, run.meta.tokens), "meta only-deep"));
    if (!run.done) li.append(el("p", w.thinking, "meta thinking"));
    box.append(li);
  }
}

function draw(fresh) { drawClock(); drawHome(); drawControls(); drawPhones(fresh); drawEcho(); drawMemory(); drawRail(); drawTrace(); }

function titleOf(e) {
  const p = e.payload || {}, w = t();
  if (e.type === "wake") return w.woke;
  if (e.type === "device_ended") return w.endedTitle[p.key] || w.endedTitle.warmer_off_at;
  if (e.type === "gap_check") return w.gapTitle;
  if (e.type === "camera") return w.camera(p);
  const scene = SCENES.find(s => isoOf(s) === e.happened_at);
  if (scene) { if (pressed && pressed.at === e.happened_at) pressed = null; return scene[3][lang]; }
  if (pressed && e.happened_at >= pressed.at) { const title = pressed.title; pressed = null; return title; }
  if (e.type === "state_changed") {
    if (p.entity_id.includes("humidity")) return w.humid(p.state);
    if (p.entity_id.includes("temperature")) return w.heat(p.state);
    return w.plugSet(p.entity_id.includes("dehumidifier") ? w.dehum : w.warmer, p.state === "on" ? w.on : w.off);
  }
  if (e.type === "sound") {
    const what = String(p.kind).split(",")[0], share = String(p.kind).match(/([\d.]+)%/);
    return share ? `Perception Encoder Audio: ${w.heard[what] || what}, ${share[1]}%` : w.heard[what] || what;
  }
  if (e.type === "schedule") return w.checks[p.name] || p.name;
  if (e.type === "message" && p.from) return `${WHO[p.from] || p.from} ${w.wrote}: "${p.text}"`;
  return w.checks[e.type] || e.type.replaceAll("_", " ");
}
async function refresh(fresh) { try { state = await api("/api/state"); draw(fresh); } catch (err) { if (err.status === 410 && state) { busy = false; stopNight(); state = null; reseed(); await boot(); say(t().ended); } } }

function listen() {
  if (stream) stream.close();
  stream = new EventSource(`/api/stream?after=${seq}`);
  const on = (kind, fn) => stream.addEventListener(kind, m => {
    if (!m.data) return;  // the browser's own connection error, not the agent's
    const item = JSON.parse(m.data);
    if (item.seq <= seq) return;
    seq = item.seq; lastItem = Date.now(); fn(item, item.seq > bootSeq); drawTrace();
  });
  on("event", (e, live) => {
    const p = e.payload || {}, sensor = e.type === "state_changed" && /humidity|temperature/.test(p.entity_id || ""), computed = e.type === "camera" || !!p.computed;
    runs.set(e.event_id, {id: e.event_id, title: titleOf(e), raw: {type: e.type, payload: p}, at: e.happened_at, steps: [], done: false, home: computed ? "computed" : e.type === "sound" ? "sound" : sensor ? "sensor" : ""});
    if (!live) return;
    busy = true; if (!night) say(waiting.length ? t().queued(waiting.length) : t().thinking);
    if (e.type === "sound") { const c = $("cry"); c.classList.remove("on"); void c.getBoundingClientRect(); c.classList.add("on"); setTimeout(() => c.classList.remove("on"), 7500); }
    document.querySelectorAll(".phone").forEach(x => x.classList.remove("lit"));
    document.querySelectorAll(".asleep").forEach(x => { x.textContent = ""; });
    $("echo-bubble").hidden = true;
    refresh(false);
  });
  on("tool_call", (e, live) => { if (live && e.tool === "start_car_seat_coach") openRecording(); const r = runs.get(e.event_id); if (r) r.steps.push({tool: e.tool, arguments: e.arguments, target: (e.tool === "notify" ? WHO[e.arguments.parent] : (e.tool.startsWith("HassTurn") ? e.arguments.name : "")) || ""}); });
  on("tool_result", (e, live) => {
    // Two messages can leave in one turn: each result belongs to its own call, and it holds the words that really went out.
    const r = runs.get(e.event_id), step = r && r.steps.find(s => s.tool === e.tool && s.result === undefined && (e.tool !== "notify" || s.arguments.parent === e.arguments.parent));
    if (step) { step.result = e.result; step.arguments = e.arguments; step.refused = /^(refused|not sent|failed|error)/i.test(String(e.result)); }
    else if (r && (e.tool === "notify" || e.tool === "say_on_echo")) r.steps.push({tool: "fixed", fixed: true, to: [e.arguments.parent || "echo"], arguments: e.arguments});
    if (live) refresh(true);
  });
  on("gate", (e, live) => { const r = runs.get(e.event_id); if (r) r.steps.push({tool: "fixed", fixed: true, to: e.to || [], arguments: {text: e.text}}); if (live) refresh(true); });
  on("decision", e => { const r = runs.get(e.event_id); if (r) { r.text = e.note || e.text; r.meta = {seconds: e.seconds, tokens: e.tokens}; } });
  on("error", e => { const r = runs.get(e.event_id); if (r) r.failed = true; });
  on("done", (e, live) => {
    const r = runs.get(e.event_id); if (r) { r.done = true; r.gated = e.status === "gated"; }
    settle();
    drawRail(); drawControls();
    if (!live) return;
    refresh(true).then(() => {
      if (!state) return;
      const night = clockOf(state.clock).hour < 7 || clockOf(state.clock).hour >= 22;
      if (night) document.querySelectorAll(".phone").forEach(x => { if (!x.classList.contains("lit")) { x.querySelector(".asleep").textContent = t().asleep; const screen = x.querySelector(".screen"); screen.scrollTop = screen.scrollHeight; } });
    });
  });
}
// A run whose ending never arrives can't keep the page locked.
setInterval(() => {
  if (busy && pending === 0 && Date.now() - lastItem > 120000) { runs.forEach(r => { r.done = true; }); lastId = null; settle(); drawRail(); drawControls(); drawTrace(); }
}, 15000);

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
// It stays open when it ends: closing by itself let the next click land on the page behind it.
$("rec-video").addEventListener("ended", () => { $("rec-cap").textContent = t().finished; $("rec-close").focus(); if (night) setTimeout(closeRecording, 1500); });
document.addEventListener("keydown", ev => { if (ev.key === "Escape" && !$("recording").hidden) closeRecording(); });

// Busy until the event this press sent has finished. A wake that fires on the way ends first, and doesn't count.
function settle() {
  busy = pending > 0 || [...runs.values()].some(x => !x.done) || (lastId !== null && !(runs.get(lastId) || {}).done);
  if (!busy && !night && !waiting.length) { const s = $("status").textContent; if (s === t().thinking || /^(Muse is still deciding|Muse sigue decidiendo)/.test(s)) say(""); }
  if (!busy && night) nextOfNight();
  if (!busy && waiting.length) { const next = waiting.shift(); next.run(); }
}
// A press while Muse decides isn't dropped: it waits its turn, and the page says so. The same cry pressed five times is one press.
function press(run, key) {
  if (!busy) return run();
  if (key && waiting.some(q => q.key === key)) { say(t().already); return; }
  if (waiting.length >= 6) { say(t().queueFull, true); return; }
  waiting.push({key, run}); say(t().queued(waiting.length));
}
function jumpToResult() {
  const target = matchMedia("(max-width:640px)").matches ? $("ptabs") : matchMedia("(max-width:1279px)").matches ? $("phone-gonza") : document.querySelector(".stage");
  target.scrollIntoView({behavior: matchMedia("(prefers-reduced-motion:reduce)").matches ? "auto" : "smooth", block: "start"});
}
async function dispatch(path, body, jump) {
  busy = true; pending += 1; lastId = null; if (!night) say(waiting.length ? t().queued(waiting.length) : t().thinking); drawRail(); drawControls();
  if (jump) jumpToResult();
  try { const answer = await api(path, body); lastId = answer.id ?? null; pending -= 1; await refresh(false); settle(); drawRail(); drawControls(); }
  catch (err) { pending -= 1; lastId = null; stopNight(); settle(); pressed = null; say(err.message, true); drawRail(); drawControls(); }
}
function play(id) { stopNight(); return press(() => playScene(id, true), "scene:" + id); }
function playScene(id, jump) { const scene = SCENES.find(s => s[0] === id); pressed = {title: scene[3][lang], at: isoOf(scene)}; return dispatch("/api/scene", {id}, jump); }
// Sent from the controls: the page stays on them, and says what happens there.
function sendEvent(type, payload) { stopNight(); return press(() => dispatch("/api/events", {type, payload}), type === "sound" ? "sound:" + payload.kind : null); }
function openSenses() { $("meta-more").open = true; ($("senses").hidden ? $("meta") : $("senses")).scrollIntoView({behavior: matchMedia("(prefers-reduced-motion:reduce)").matches ? "auto" : "smooth", block: "start"}); }

// Play the story: the same scene events a judge can press, one at a time, each only after Muse finished the last.
function stopNight() { clearTimeout(nightTimer); if (night) { night = null; $("play").textContent = playLabel(); $("play").classList.remove("on"); } }
function nextOfNight() {
  clearTimeout(nightTimer);
  nightTimer = setTimeout(() => {
    if (!night) return;
    if (!$("recording").hidden) { nextOfNight(); return; }  // the car seat clip plays out, and the story waits until it's closed
    if (!night.left.length) { night = null; drawRail(); say(t().storyDone); return; }
    const id = night.left.shift(), title = SCENES.find(s => s[0] === id)[3][lang];
    say(t().playing(night.list.length - night.left.length, night.list.length, title));
    playScene(id);
  }, night && night.started ? 1800 : 0);
  if (night) night.started = true;
}
$("play").addEventListener("click", async () => {
  if (night) { stopNight(); say(""); drawRail(); return; }
  if (!state) return;
  if (busy) { say(t().wait); return; }
  const left = () => ORDER.filter(id => !state.played.includes(id) && isoOf(SCENES.find(s => s[0] === id)) > state.clock);
  if (!left().length) { if (!(await startOver())) return; }
  night = {list: ORDER, left: left(), started: false};
  drawRail(); jumpToResult(); nextOfNight();
});

for (const [id, entity] of [["c-hum", "sensor.nursery_climate_humidity"], ["c-temp", "sensor.nursery_climate_temperature"]]) {
  $(id).addEventListener("pointerdown", () => editing.add(id));
  $(id).addEventListener("input", () => { editing.add(id); drawControls(); });
  $(id).addEventListener("change", async ev => { const value = ev.target.value; ev.target.blur(); await sendEvent("state_changed", {entity_id: entity, state: value}); editing.delete(id); drawControls(); });
}
document.querySelector(".sends").addEventListener("click", async ev => {
  const b = ev.target.closest("button"); if (!b) return;
  if (b.dataset.clock) {
    stopNight();
    press(async () => {
      busy = true; pending += 1; lastId = null; drawRail(); drawControls();
      try { state = await api("/api/clock", {minutes: Number(b.dataset.clock)}); pending -= 1; settle(); draw(); }
      catch (err) { pending -= 1; settle(); say(err.message, true); drawRail(); drawControls(); }
    });
    return;
  }
  if (b.id === "b-feeds") { try { state = await api("/api/feeds", {on: b.dataset.on === "1"}); say(state.feeds_on ? "" : t().feedsNote); draw(); } catch (err) { say(err.message, true); } return; }
  if (b.dataset.event === "sound") sendEvent("sound", {kind: b.dataset.kind});
  if (b.dataset.event === "switch") sendEvent("state_changed", {entity_id: b.dataset.entity, state: b.dataset.to});
  if (b.dataset.event === "schedule") sendEvent("schedule", {name: b.dataset.name});
});

function reseed() { stopNight(); waiting = []; seen = {gonza: 0, ceci: 0}; shownEcho = 0; runs = new Map(); seq = 0; busy = false; pending = 0; lastId = null; editing.clear(); unread = {gonza: false, ceci: false}; showPhone("gonza"); closeRecording(); $("echo-bubble").hidden = true; document.querySelectorAll(".phone").forEach(x => x.classList.remove("lit")); document.querySelectorAll(".asleep").forEach(x => { x.textContent = ""; }); }

async function startOver() {
  say(t().busy);
  try { state = await api("/api/reset", {}); reseed(); say(""); seq = bootSeq = state.seq; listen(); draw(); return true; }
  catch (err) { if (err.status === 410) { state = null; reseed(); await boot(); return !!state; } say(err.message, true); return false; }
}
// One press. It says what happened, and the language button lives elsewhere, so a stray click isn't a surprise.
$("reset").addEventListener("click", async () => { if (await startOver()) say(t().restarted); });
// Changing language keeps the home: what was said stays as it was said, and what comes next follows the page.
$("lang").addEventListener("click", async () => {
  lang = lang === "en" ? "es" : "en";
  try { localStorage.setItem("pa-sim-lang", lang); } catch (e) { /* the choice just isn't kept */ }
  words();
  if (!state) return;
  try {
    await api("/api/lang", {lang}); state.lang = lang;
    if (state.sent.length || state.said.length) say(t().langNow);
  } catch (err) { say(err.message, true); }
});
$("rec-close").addEventListener("click", closeRecording);
$("deep").addEventListener("click", () => { deep = !deep; $("deep").textContent = deep ? t().plain : t().deep; $("deep").setAttribute("aria-pressed", String(deep)); drawTrace(); });
$("ptabs").addEventListener("click", ev => { const b = ev.target.closest("button"); if (b) showPhone(b.dataset.phone); });
for (const p of ["gonza", "ceci"]) {
  $("phone-" + p).querySelector("form").addEventListener("submit", async ev => {
    ev.preventDefault();
    const input = ev.target.querySelector("input"), text = input.value.trim();
    if (!text) return;
    input.value = "";
    stopNight();
    press(() => dispatch("/api/write", {as: p, text}));
  });
}
async function boot() {
  try { const s = localStorage.getItem("pa-sim-lang"); if (s === "es" || s === "en") lang = s; } catch (e) { /* defaults to English */ }
  showPhone(phone); words(); say(t().busy);
  try {
    state = await api("/api/session", {lang});
    if (state.lang !== lang) { await api("/api/lang", {lang}); state.lang = lang; }
    // A page reloaded on a session already running gets its trace back from the start, without replaying sounds or the video.
    say(""); bootSeq = state.seq; seq = 0; seen = {gonza: state.sent.filter(m => m.to === "gonza").length, ceci: state.sent.filter(m => m.to === "ceci").length}; shownEcho = state.sent.filter(m => m.to === "echo").length;
    listen(); draw();
  } catch (err) { say(err.message, true); if (err.status === 503) setTimeout(boot, 20000); }
}

// Meta's models on real recordings: saved results, sent as the event the home would send. Muse decides live.
function drawMeta() {
  const w = t(); $("meta-t").textContent = w.metaT; $("meta-lead").textContent = w.metaLead; $("arch-link").textContent = w.archLink; $("meta-where").textContent = w.where; $("meta-sum").textContent = w.metaSum; const mms = `/static/senses/mms-coach-${lang}.m4a`; if ($("mms").getAttribute("src") !== mms) $("mms").setAttribute("src", mms);
  for (const key of ["muse", "pe", "sam", "gadget", "tts"]) {
    const [name, how, text] = w[key], card = $("m-" + key);
    card.querySelector("h3").textContent = name; card.querySelector(".how").textContent = how; card.querySelector("p.say-it").textContent = text;
  }
}
function drawSenses() {
  if (!senses) return;
  const w = t(), box = $("se-cards"); box.textContent = ""; $("senses").hidden = false;
  const send = (card, id, none) => { const b = el("button", none ? w.seNone : w.seSend, "ghost se-send"); b.type = "button"; if (none) b.dataset.none = "1"; b.addEventListener("click", () => { stopNight(); press(() => dispatch("/api/sense", {id}, true), "sense:" + id); }); card.append(b); };
  senses.audio.forEach(c => {
    const card = el("article", undefined, "se-card"), audio = el("audio"), credit = el("p", undefined, "se-credit"), link = el("a", `${c.title}, ${c.license}`);
    card.append(el("h3", w.seAudio[c.id] || c.title)); audio.controls = true; audio.preload = "none"; audio.src = `/static/senses/${c.file}`; card.append(audio);
    card.append(el("p", w.seBy.audio, "se-model"));
    if (c.heard) card.append(el("p", w.seHeard(w.heardAs[c.heard], Math.min(99.9, Math.floor(c.scores[c.heard].probability * 1000) / 10))));
    link.href = c.page; link.rel = "noopener"; link.target = "_blank"; credit.append(link); card.append(credit);
    send(card, c.id, !c.heard); box.append(card);
  });
  senses.frames.forEach(f => {
    const card = el("article", undefined, "se-card"), pics = el("div", undefined, "se-pics");
    for (const [file, alt] of [[f.file, "original"], [f.mask, "mask"]]) { const img = el("img"); img.src = `/static/senses/${file}`; img.alt = `${w.seFrame[f.id]}, ${alt}`; img.loading = "lazy"; img.width = 640; img.height = 352; pics.append(img); }
    card.append(el("h3", w.seFrame[f.id]), pics, el("p", w.seBy.frame, "se-model"), el("p", w.seSaw[f.verdict]), el("p", `${w.seMasks(f.hands)} ${w.seGen}`, "se-why"));
    send(card, f.id, false); box.append(card);
  });
  drawControls();
}
$("to-senses").addEventListener("click", ev => { ev.preventDefault(); openSenses(); });
$("rec-open").addEventListener("click", openRecording);
$("ct-see").addEventListener("click", jumpToResult);
fetch("/static/senses/senses.json").then(r => r.ok ? r.json() : null).then(data => { senses = data; drawSenses(); if (["#meta", "#senses"].includes(location.hash)) openSenses(); }).catch(() => {});
boot();
