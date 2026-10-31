import Foundation

// Tests for the HUD logic in ParentingGlasses/HUD/HUDState.swift, compiled with it by scripts/test-hud.sh.
// HUDState is Foundation only, so these run on the Mac without the simulator or the DAT SDK.

var failures = 0
var checks = 0

func expect(_ condition: Bool, _ message: String, line: Int = #line) {
  checks += 1
  if !condition {
    failures += 1
    print("FAIL line \(line): \(message)")
  }
}

func event(_ json: String) -> HUDEvent {
  try! JSONDecoder().decode(HUDEvent.self, from: Data(json.utf8))
}

func cards(_ events: [HUDEvent], every step: Double = 0.05, until end: Double) -> [HUDCard] {
  var state = HUDState()
  var out: [HUDCard] = []
  var next = 0
  var t = 0.0
  while t <= end {
    while next < events.count, events[next].t <= t {
      state.apply(events[next])
      next += 1
    }
    let card = state.card(at: t)
    if out.last != card { out.append(card) }
    t += step
  }
  return out
}

// Idle before anything happens.
expect(HUDState().card(at: 0).title == "Parenting agent", "idle card")

// Armed by Muse: the watch card says so, with the arming time.
do {
  var state = HUDState()
  state.apply(event(#"{"t":0.1,"kind":"armed","by":"brain","tool":"start_changing_table","seconds":3.146}"#))
  state.apply(event(#"{"t":0.2,"kind":"reflex","state":"on","hands":1}"#))
  let card = state.card(at: 0.3)
  expect(card.status == "Hand on the baby", "hand on: \(card.status)")
  expect(card.meta == "Watch on · armed by Muse in 3.1 s", "armed meta: \(card.meta ?? "nil")")
  expect(!card.alert, "no alert while a hand is on")
}

// Hands off: alarm, then "hand" holds the headline for voiceHoldS, then the alarm card says it was spoken, then clear.
do {
  var state = HUDState()
  state.apply(event(#"{"t":0,"kind":"armed","by":"brain"}"#))
  state.apply(event(#"{"t":1,"kind":"alarm","state":"off","episode":1}"#))
  expect(state.card(at: 1).title == "Hands off", "alarm card")
  expect(state.card(at: 1).alert, "alarm is an alert")
  state.apply(event(#"{"t":1.5,"kind":"confirm","verdict":"off","episode":1}"#))
  state.apply(event(#"{"t":2.2,"kind":"voice","text":"hand","episode":1}"#))
  expect(state.card(at: 2.3).title == "\u{201C}hand\u{201D}", "voice headline")
  expect(state.card(at: 2.2 + HUDState.voiceHoldS + 0.01).title == "Hands off", "back to the alarm after the hold")
  expect(state.card(at: 4).meta == "\u{201C}hand\u{201D} spoken · SAM 3.1: off", "spoken meta: \(state.card(at: 4).meta ?? "nil")")
  state.apply(event(#"{"t":4.5,"kind":"clear","episode":1}"#))
  expect(state.card(at: 4.5).status == "Hand on the baby", "cleared")
}

// Hover: a lifted alarm shows the recorded lift.
do {
  var state = HUDState()
  state.apply(event(#"{"t":0,"kind":"armed","by":"brain"}"#))
  state.apply(event(#"{"t":1,"kind":"reflex","state":"lifted","hands":2,"lift_cm":1.81}"#))
  state.apply(event(#"{"t":1,"kind":"alarm","state":"lifted","episode":2}"#))
  expect(state.card(at: 1).title == "Hover", "hover card")
  expect(state.card(at: 1).status == "Hand lifted 1.8 cm off the baby", "lift: \(state.card(at: 1).status)")
  state.apply(event(#"{"t":1.2,"kind":"reflex","state":"lifted","hands":2,"lift_cm":null}"#))
  expect(state.card(at: 1.2).status == "Hand lifted 1.8 cm off the baby", "keeps the last lift while lifted")
}

// Held diaper: hidden hand, SAM 3.1 finds it, then the hover keeps "holding a diaper".
do {
  var state = HUDState()
  state.apply(event(#"{"t":0,"kind":"armed","by":"brain"}"#))
  state.apply(event(#"{"t":0,"kind":"scene","name":"held diaper","source":"x"}"#))
  state.apply(event(#"{"t":0.2,"kind":"held","object":"diaper","verdict":"on","model":"SAM 3.1"}"#))
  let held = state.card(at: 0.2)
  expect(held.status == "Hand hidden by the diaper", "held status")
  expect(held.detail == "SAM 3.1 found the hand on the baby", "held detail")
  state.apply(event(#"{"t":1.6,"kind":"alarm","state":"lifted","episode":1}"#))
  expect(state.card(at: 1.6).detail == "Holding a diaper", "hover while holding")
}

// A new scene clears the alarm and the held object.
do {
  var state = HUDState()
  state.apply(event(#"{"t":0,"kind":"armed","by":"brain"}"#))
  state.apply(event(#"{"t":1,"kind":"alarm","state":"off"}"#))
  state.apply(event(#"{"t":2,"kind":"scene","name":"hover","source":"x"}"#))
  expect(state.alarm == nil, "scene clears the alarm")
  expect(state.card(at: 2).title == "Changing table", "watch card after the scene change")
}

// Done: closing, then the logged entry read back with Muse's line.
do {
  var state = HUDState()
  state.apply(event(#"{"t":0,"kind":"armed","by":"brain"}"#))
  state.apply(event(#"{"t":1,"kind":"closed"}"#))
  expect(state.card(at: 1).status == "Logging the change", "closing card")
  state.apply(event(#"{"t":1.5,"kind":"logged","what":"diaper","at":"04:59","contents":["dirty"],"entry":174}"#))
  expect(state.card(at: 1.5).detail == nil, "no stale reply on the logged card")
  state.apply(event(#"{"t":1.9,"kind":"reply","text":"4 hand alerts this change. Logged diaper at 04:59, dirty."}"#))
  let card = state.card(at: 2)
  expect(card.status == "Diaper at 04:59 · dirty", "logged: \(card.status)")
  expect(card.meta == "Read back from Baby Buddy · entry 174", "read back meta")
  expect(card.detail == "4 hand alerts this change. Logged diaper at 04:59, dirty.", "Muse line")
}

// Dog near the baby wins over everything and replaces the logged card on its scene.
do {
  var state = HUDState()
  state.apply(event(#"{"t":0,"kind":"logged","what":"diaper","at":"04:59","contents":["dirty"],"entry":174}"#))
  state.apply(event(#"{"t":1,"kind":"scene","name":"dog","source":"x"}"#))
  expect(state.card(at: 1).title == "Dog watch", "dog scene before the verdict")
  state.apply(event(#"{"t":1.4,"kind":"dog","verdict":"near","ratio":0.134,"alert":true,"dog_score":0.938,"baby_score":0.898,"model":"SAM 3.1"}"#))
  let card = state.card(at: 1.4)
  expect(card.title == "Dog near the baby" && card.alert, "dog card")
  expect(card.detail == "Gap 0.13 baby sizes · dog 0.94 · baby 0.90", "dog detail: \(card.detail ?? "nil")")
  var far = HUDState()
  far.apply(event(#"{"t":0,"kind":"scene","name":"dog","source":"x"}"#))
  far.apply(event(#"{"t":0,"kind":"dog","verdict":"far","ratio":2.1}"#))
  expect(far.card(at: 0).title != "Dog near the baby", "a far dog does not alert")
}

// Live agent events (parenting_agent/glasses.py to_app) map onto the same reducer, in the order the agent sends them.
do {
  var state = HUDState()
  func feed(_ json: String, at t: Double) {
    for e in HUDState.live(event(json), at: t, current: state) { state.apply(e) }
  }
  feed(#"{"kind":"skill","text":"changing-table armed, watching through the glasses"}"#, at: 0)
  feed(#"{"kind":"armed","by":"brain","seconds":3.12,"tool":"start_changing_table"}"#, at: 0)
  feed(#"{"kind":"state","state":"on","hands":1,"lift_cm":0.1,"stream_s":4.2,"frame_unix":1000.5}"#, at: 0.1)
  expect(state.armedBy == "brain", "the skill's own armed does not hide Muse: \(state.armedBy ?? "nil")")
  expect(state.card(at: 0.1).meta == "Watch on · armed by Muse in 3.1 s", "live armed meta: \(state.card(at: 0.1).meta ?? "nil")")
  expect(state.card(at: 0.1).status == "Hand on the baby", "live hand on")
  feed(#"{"kind":"state","state":"off","hands":0,"stream_s":5}"#, at: 1)
  feed(#"{"kind":"alarm","state":"off","episode":1,"stream_s":5}"#, at: 1)
  feed(#"{"kind":"chime","stream_s":5}"#, at: 1)
  expect(state.card(at: 1).title == "Hands off", "live alarm")
  feed(#"{"kind":"confirm","verdict":"off","episode":1,"model":"SAM 3.1"}"#, at: 1.5)
  feed(#"{"kind":"voice","text":"hand","stream_s":5,"frame_unix":1001.2}"#, at: 2.2)
  expect(state.card(at: 2.3).title == "\u{201C}hand\u{201D}", "live voice")
  feed(#"{"kind":"clear","episode":1}"#, at: 3)
  feed(#"{"kind":"state","state":"lifted","hands":1,"lift_cm":2.44}"#, at: 4)
  feed(#"{"kind":"alarm","state":"lifted","episode":2}"#, at: 4)
  expect(state.card(at: 4).status == "Hand lifted 2.4 cm off the baby", "live hover: \(state.card(at: 4).status)")
  feed(#"{"kind":"clear","episode":2}"#, at: 5)
  feed(#"{"kind":"held","verdict":"on","object":"diaper","model":"SAM 3.1"}"#, at: 6)
  expect(state.card(at: 6).status == "Hand hidden by the diaper", "live held: \(state.card(at: 6).status)")
  feed(#"{"kind":"state","state":"on","hands":0,"held":"on"}"#, at: 6.2)
  feed(#"{"kind":"state","state":"on","hands":1}"#, at: 6.3)
  expect(state.card(at: 6.3).status == "Hand hidden by the diaper", "one MediaPipe frame keeps the hidden-hand card")
  feed(#"{"kind":"state","state":"on","hands":1}"#, at: 7.4)
  expect(state.card(at: 7.4).status == "Hand on the baby", "a second of MediaPipe seeing the hand again ends it")
  var unnamed = HUDState()
  for e in HUDState.live(event(#"{"kind":"armed","by":"brain"}"#), at: 0, current: unnamed) { unnamed.apply(e) }
  for e in HUDState.live(event(#"{"kind":"held","verdict":"on","object":null}"#), at: 1, current: unnamed) { unnamed.apply(e) }
  expect(unnamed.card(at: 1).status == "Hands hidden from MediaPipe", "held look with nothing named: \(unnamed.card(at: 1).status)")
  expect(unnamed.card(at: 1).detail == "SAM 3.1 found the hand on the baby", "held look found the hand")
  feed(#"{"kind":"skill","text":"changing-table closed after 300 frames"}"#, at: 8)
  expect(state.card(at: 8).status == "Logging the change", "live closing")
  feed(#"{"kind":"logged","what":"diaper","at":"19:20","contents":["dirty"],"entry":230}"#, at: 8.5)
  feed(#"{"kind":"reply","text":"3 hand alerts. Logged diaper at 19:20, dirty."}"#, at: 9)
  expect(state.card(at: 9).meta == "Read back from Baby Buddy · entry 230", "live read back")
  feed(#"{"kind":"dog","verdict":"no_dog"}"#, at: 10)
  expect(state.card(at: 10).title == "Logged", "no dog keeps the logged card")
  feed(#"{"kind":"dog","verdict":"near","ratio":0.1,"dog_score":0.93,"baby_score":0.88,"model":"SAM 3.1","stream_s":40}"#, at: 11)
  expect(state.card(at: 11).title == "Dog near the baby", "live dog")
  expect(HUDState.live(event(#"{"kind":"hello"}"#), at: 0, current: state).isEmpty, "unknown kind")
  expect(event(#"{"kind":"voice","frame_unix":1001.25}"#).frameUnix == 1001.25, "frame time decodes")
}


// Agent cards (parenting_agent/hud_cards.py): shown whole, in the parent's language, replaced by a newer camera check.
do {
  var state = HUDState()
  func feed(_ json: String, at t: Double) {
    for e in HUDState.live(event(json), at: t, current: state) { state.apply(e) }
  }
  feed(#"{"kind":"hello","wearer":"gonza","name":"Gonza","lang":"es"}"#, at: 0)
  expect(state.lang == "es", "the hello sets the language")
  expect(state.card(at: 0).title == "Agente de crianza", "idle card in Spanish: \(state.card(at: 0).title)")
  feed(#"{"kind":"card","card":{"topic":"next_feed","icon":"clock","title":"Próxima toma","status":"Cerca de las 11:40 · en 20 min","detail":"Cada 3 h 05 min más o menos","alert":false,"sticky":false,"lang":"es"},"cause":"next_feed","agent_unix":1000.0}"#, at: 1)
  let feedCard = state.card(at: 1)
  expect(feedCard.title == "Próxima toma" && feedCard.icon == "clock" && feedCard.status == "Cerca de las 11:40 · en 20 min", "agent card shown whole")
  expect(state.card(at: 60).title == "Próxima toma", "an agent card stays until something newer, no timer wakes the display")
  feed(#"{"kind":"skill","skill":"bath","text":"bath armed, watching through the glasses"}"#, at: 61)
  expect(state.card(at: 61.1).title == "Baño", "a new watch replaces an older agent card, in Spanish: \(state.card(at: 61.1).title)")
  feed(#"{"kind":"card","card":{"topic":"nap","icon":"bedSide","title":"Modo siesta","status":"Siesta desde las 11:30","alert":false,"sticky":false}}"#, at: 71)
  feed(#"{"kind":"state","state":"on","hands":1}"#, at: 71.5)
  expect(state.card(at: 72).title == "Modo siesta", "an unchanged hand state does not hide a new agent card")
  feed(#"{"kind":"alarm","state":"off","episode":1}"#, at: 73)
  expect(state.card(at: 73).title == "Manos afuera", "a camera alarm always wins over an agent card: \(state.card(at: 73).title)")
  feed(#"{"kind":"clear","episode":1}"#, at: 74)
  expect(state.card(at: 74).title == "Modo siesta", "a card holds agentHoldS over the watch states")
  feed(#"{"kind":"state","state":"off","hands":0}"#, at: 78)
  expect(state.card(at: 78).title != "Modo siesta", "then a newer camera check replaces it: \(state.card(at: 78).title)")
  expect(HUDState.live(event(#"{"kind":"voice","skill":"car-seat","step":"lap_guides","text":"Slide the lap belt"}"#), at: 75, current: state).isEmpty,
         "the car seat coach's speech is never the changing table's hand")
}

// A red flag: above everything, never dimmed (its meta line changes before Meta's 20 s dim), until acknowledged.
do {
  var state = HUDState()
  state.apply(event(#"{"t":0,"kind":"hello","lang":"es"}"#))
  state.apply(event(#"{"t":1,"kind":"card","card":{"topic":"red_flag","icon":"phoneHandsetArrowUpRight","title":"Llamá al 911 ya","status":"Puede ser una emergencia","detail":"Contales lo que ves","meta":"911","alert":true,"sticky":true}}"#))
  let first = state.card(at: 1)
  expect(first.title == "Llamá al 911 ya" && first.alert && first.action == "Entendido", "red flag card with its button")
  expect(first.meta == "911 · hace 0:00", "red flag meta: \(first.meta ?? "nil")")
  expect(state.card(at: 14).meta == first.meta, "no change inside 15 s")
  expect(state.card(at: 16).meta == "911 · hace 0:15", "changes before the 20 s dim: \(state.card(at: 16).meta ?? "nil")")
  var t = 1.0
  var last = first
  var unchanged = 0.0
  while t < 120 {
    let now = state.card(at: t)
    unchanged = now == last ? unchanged + 0.5 : 0
    expect(unchanged < Double(20), "the red flag card never goes 20 s without a change (at \(t))")
    last = now
    t += 0.5
  }
  state.apply(event(#"{"t":20,"kind":"alarm","state":"off","episode":1}"#))
  state.apply(event(#"{"t":21,"kind":"dog","verdict":"near","ratio":0.1}"#))
  state.apply(event(#"{"t":22,"kind":"card","card":{"topic":"next_feed","icon":"clock","title":"Próxima toma","status":"x"}}"#))
  expect(state.card(at: 22).title == "Llamá al 911 ya", "nothing replaces a red flag")
  state.apply(event(#"{"t":30,"kind":"red_flag_clear","by":"parent"}"#))
  expect(state.card(at: 30).title != "Llamá al 911 ya", "the parent's acknowledgement clears it")
}

// The live script picks the scene playing at a feed time.
do {
  let json = #"{"feed":"hud-live-feed","duration_s":20,"scenes":[{"name":"one hand","source":"live","at":0,"length":10},{"name":"dog","source":"live","at":10,"length":10}],"say":[{"at":1,"text":"changing time"}]}"#
  let script = try! JSONDecoder().decode(HUDLiveScript.self, from: Data(json.utf8))
  expect(script.scene(at: 3)?.name == "one hand" && script.scene(at: 12)?.name == "dog", "live scenes")
}

// The committed replay file: decodes, is ordered, and shows every check the HUD is for, in order.
do {
  let path = CommandLine.arguments.dropFirst().first ?? "ParentingGlasses/HUD/hud-replay.json"
  let replay = try! JSONDecoder().decode(HUDReplay.self, from: Data(contentsOf: URL(fileURLWithPath: path)))
  expect(replay.events.map(\.t) == replay.events.map(\.t).sorted(), "events in time order")
  expect(replay.durationS >= 10 && replay.durationS <= 20, "10 to 20 s: \(replay.durationS)")
  let shown = cards(replay.events, until: replay.durationS)
  let wanted: [(String, (HUDCard) -> Bool)] = [
    ("armed by Muse", { $0.meta?.contains("armed by Muse") == true && $0.status == "Hand on the baby" }),
    ("hands off", { $0.title == "Hands off" && $0.status == "No hand on the baby" }),
    ("hand spoken", { $0.title == "\u{201C}hand\u{201D}" }),
    ("hover", { $0.title == "Hover" && $0.status.hasPrefix("Hand lifted") }),
    ("held diaper", { $0.status == "Hand hidden by the diaper" }),
    ("logged read back", { $0.title == "Logged" && $0.meta?.hasPrefix("Read back from Baby Buddy") == true }),
    ("dog near the baby", { $0.title == "Dog near the baby" }),
  ]
  var from = 0
  for (name, matches) in wanted {
    if let index = shown[from...].firstIndex(where: matches) {
      from = index
    } else {
      expect(false, "replay never shows \(name) after card \(from)")
    }
  }
  expect(shown.filter { $0.title == "\u{201C}hand\u{201D}" }.count >= 1, "hand spoken at least once")
}

print("\(checks - failures) of \(checks) checks passed")
exit(failures == 0 ? 0 : 1)
