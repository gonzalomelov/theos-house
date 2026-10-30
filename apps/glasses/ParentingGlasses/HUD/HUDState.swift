import Foundation

/// One event the HUD reacts to: from the replay file (`hud-replay.json`, recorded detector outputs) or from the live agent.
struct HUDEvent: Decodable, Equatable, Sendable {
  var t: Double
  var kind: String
  var text: String?
  var state: String?
  var hands: Int?
  var liftCm: Double?
  var name: String?
  var source: String?
  var by: String?
  var tool: String?
  var seconds: Double?
  var verdict: String?
  var object: String?
  var what: String?
  var at: String?
  var contents: [String]?
  var entry: Int?
  var ratio: Double?
  var dogScore: Double?
  var babyScore: Double?
  var latencyS: Double?
  var model: String?

  init(t: Double, kind: String, text: String? = nil, state: String? = nil, hands: Int? = nil) {
    self.t = t
    self.kind = kind
    self.text = text
    self.state = state
    self.hands = hands
  }

  enum CodingKeys: String, CodingKey {
    case t, kind, text, state, hands, name, source, by, tool, seconds, verdict, object, what, at, contents, entry, ratio
    case model
    case liftCm = "lift_cm"
    case dogScore = "dog_score"
    case babyScore = "baby_score"
    case latencyS = "latency_s"
  }
}

struct HUDScene: Decodable, Equatable, Sendable {
  let name: String
  let source: String
  var credit: String?
  let at: Double
  let length: Double
}

/// The replay file written by `scripts/glasses_hud_replay.py`.
struct HUDReplay: Decodable, Sendable {
  let durationS: Double
  let note: String
  let scenes: [HUDScene]
  let events: [HUDEvent]

  enum CodingKeys: String, CodingKey {
    case durationS = "duration_s"
    case note, scenes, events
  }
}

/// What the glasses display shows: one card, sent whole to the display each time it changes.
/// `icon` is a Meta Ray-Ban Display `IconName` case name.
struct HUDCard: Equatable, Sendable {
  var icon: String
  var title: String
  var status: String
  var detail: String?
  var meta: String?
  var alert = false
}

/// Folds HUD events into the card the display shows. Pure, so the same logic runs on recorded outputs and live events.
struct HUDState: Equatable, Sendable {
  /// How long the spoken "hand" stays the headline.
  static let voiceHoldS = 1.6

  var scene: String?
  var watchOn = false
  var armedBy: String?
  var armTool: String?
  var armSeconds: Double?
  var reflex: String?
  var hands: Int?
  var liftCm: Double?
  var alarm: String?
  var voicedAt: Double?
  var confirm: String?
  var heldObject: String?
  var heldVerdict: String?
  var lastReply: String?
  var closing = false
  var logged: HUDEvent?
  var dog: HUDEvent?

  mutating func apply(_ event: HUDEvent) {
    switch event.kind {
    case "scene":
      scene = event.name
      alarm = nil
      voicedAt = nil
      confirm = nil
      heldObject = nil
      heldVerdict = nil
      liftCm = nil
      if event.name == "dog" { logged = nil }
    case "armed":
      watchOn = true
      armedBy = event.by
      armTool = event.tool
      armSeconds = event.seconds
    case "closed":
      watchOn = false
      closing = true
      alarm = nil
      lastReply = nil
    case "reflex":
      reflex = event.state
      hands = event.hands
      liftCm = event.liftCm ?? (event.state == "lifted" ? liftCm : nil)
    case "alarm":
      alarm = event.state
      voicedAt = nil
      confirm = nil
    case "clear":
      alarm = nil
      voicedAt = nil
      confirm = nil
    case "confirm":
      confirm = event.verdict
    case "voice":
      voicedAt = event.t
      if alarm == nil { alarm = "off" }
    case "held":
      heldObject = event.object
      heldVerdict = event.verdict
    case "logged":
      logged = event
      watchOn = false
      closing = false
    case "reply":
      lastReply = event.text
    case "dog":
      dog = event
    default:
      break
    }
  }

  /// The card at time `t` (same clock as the events).
  func card(at t: Double) -> HUDCard {
    if let dog, dog.verdict == "near" {
      return HUDCard(
        icon: "exclamationTriangle", title: "Dog near the baby", status: "Dog close to the baby",
        detail: "Gap \(Self.fmt(dog.ratio, 2)) baby sizes · dog \(Self.fmt(dog.dogScore, 2)) · baby \(Self.fmt(dog.babyScore, 2))",
        meta: "\(dog.model ?? "SAM 3.1") · alert to the parents", alert: true)
    }
    if scene == "dog" {
      return HUDCard(icon: "eye", title: "Dog watch", status: "Looking for a dog near the baby", detail: nil,
                     meta: "SAM 3.1 · dog, baby, bassinet, play mat")
    }
    if let logged {
      let contents = (logged.contents ?? []).joined(separator: " and ")
      return HUDCard(
        icon: "checkmarkCircle", title: "Logged",
        status: "\((logged.what ?? "change").capitalized) at \(logged.at ?? "?")\(contents.isEmpty ? "" : " · \(contents)")",
        detail: lastReply, meta: "Read back from Baby Buddy · entry \(logged.entry.map(String.init) ?? "?")")
    }
    if closing {
      return HUDCard(icon: "pencil", title: "Done", status: "Logging the change", detail: nil,
                     meta: "Watch closed")
    }
    let lifted = alarm == "lifted"
    let what = lifted ? "Hand lifted\(liftCm.map { " \(Self.fmt($0, 1)) cm" } ?? "") off the baby" : "No hand on the baby"
    if let voicedAt, t - voicedAt < Self.voiceHoldS {
      return HUDCard(icon: "speakerWithThreeArcs", title: "\u{201C}hand\u{201D}", status: what,
                     detail: heldObject.map { "Holding a \($0)" }, meta: "Spoken on the glasses", alert: true)
    }
    if let alarm {
      var meta = voicedAt == nil ? "Tone · \u{201C}hand\u{201D} if it lasts 1.2 s" : "\u{201C}hand\u{201D} spoken"
      if let confirm { meta += " · SAM 3.1: \(confirm)" }
      return HUDCard(icon: "exclamationTriangle", title: alarm == "lifted" ? "Hover" : "Hands off", status: what,
                     detail: heldObject.map { "Holding a \($0)" }, meta: meta, alert: true)
    }
    if let heldObject {
      return HUDCard(
        icon: "eye", title: "Changing table", status: "Hand hidden by the \(heldObject)",
        detail: heldVerdict == "on" ? "SAM 3.1 found the hand on the baby" : "SAM 3.1 is looking for the hand",
        meta: watchMeta)
    }
    if watchOn {
      let status: String
      switch reflex {
      case "off": status = "No hand on the baby"
      case "lifted": status = "Hand lifting"
      default: status = "Hand on the baby"
      }
      return HUDCard(icon: "eye", title: "Changing table", status: status, detail: lastReply, meta: watchMeta)
    }
    return HUDCard(icon: "smartGlasses", title: "Parenting agent", status: "Say \u{201C}changing time\u{201D}",
                   detail: lastReply, meta: nil)
  }

  private var watchMeta: String {
    var meta = "Watch on"
    if armedBy == "brain" { meta += " · armed by Muse" } else if let armedBy { meta += " · armed by \(armedBy)" }
    if let armSeconds { meta += " in \(Self.fmt(armSeconds, 1)) s" }
    return meta
  }

  /// The live agent's glasses events (`parenting_agent/glasses.py` `to_app`) as HUD events.
  static func live(kind: String, text: String?, state: String?, hands: Int?, at t: Double, current: HUDState) -> [HUDEvent] {
    switch kind {
    case "state":
      var events = [HUDEvent(t: t, kind: "reflex", state: state, hands: hands)]
      if state == "on", current.alarm != nil { events.append(HUDEvent(t: t, kind: "clear")) }
      return events
    case "chime":
      return [HUDEvent(t: t, kind: "alarm", state: current.reflex == "lifted" ? "lifted" : "off")]
    case "voice":
      return [HUDEvent(t: t, kind: "voice", text: text ?? "hand")]
    case "reply":
      return [HUDEvent(t: t, kind: "reply", text: text)]
    case "skill":
      guard let text else { return [] }
      if text.contains("armed") {
        var armed = HUDEvent(t: t, kind: "armed")
        armed.by = "agent"
        return [armed]
      }
      if text.contains("closed") { return [HUDEvent(t: t, kind: "closed")] }
      return []
    default:
      return []
    }
  }

  static func fmt(_ value: Double?, _ digits: Int) -> String {
    guard let value else { return "?" }
    return String(format: "%.\(digits)f", value)
  }
}
