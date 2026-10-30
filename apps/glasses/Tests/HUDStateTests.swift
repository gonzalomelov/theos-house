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

// Live agent events map onto the same reducer.
do {
  var state = HUDState()
  for e in HUDState.live(kind: "skill", text: "changing-table armed, watching through the glasses", state: nil, hands: nil,
                         at: 0, current: state) { state.apply(e) }
  expect(state.watchOn && state.armedBy == "agent", "live armed")
  for e in HUDState.live(kind: "state", text: nil, state: "lifted", hands: 1, at: 1, current: state) { state.apply(e) }
  for e in HUDState.live(kind: "chime", text: nil, state: nil, hands: nil, at: 1, current: state) { state.apply(e) }
  expect(state.alarm == "lifted", "live chime while lifted is a hover")
  for e in HUDState.live(kind: "voice", text: "hand", state: nil, hands: nil, at: 2, current: state) { state.apply(e) }
  expect(state.card(at: 2).title == "\u{201C}hand\u{201D}", "live voice")
  for e in HUDState.live(kind: "state", text: nil, state: "on", hands: 1, at: 3, current: state) { state.apply(e) }
  expect(state.alarm == nil, "live hand back clears")
  expect(HUDState.live(kind: "hello", text: nil, state: nil, hands: nil, at: 0, current: state).isEmpty, "unknown kind")
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
