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
  /// Live events only: the Unix time the agent received the frame this event is about (`frame_unix`).
  var frameUnix: Double?
  /// Live hand states only: "on" or "lifted" while the skill follows a hand MediaPipe lost, by its SAM 3.1 region.
  var held: String?
  /// A display card the agent wrote for this parent (`parenting_agent/hud_cards.py`), on "card" events.
  var card: HUDAgentCard?
  /// The wearer's language, on the agent's "hello".
  var lang: String?
  var skill: String?
  var step: String?
  /// What made a card ("next_feed", "nap_mode on") and the Unix time it left the agent.
  var cause: String?
  var agentUnix: Double?

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
    case held, card, lang, skill, step, cause
    case frameUnix = "frame_unix"
    case agentUnix = "agent_unix"
  }

  /// Live agent events carry no `t`, the app stamps them on arrival.
  init(from decoder: Decoder) throws {
    let c = try decoder.container(keyedBy: CodingKeys.self)
    t = try c.decodeIfPresent(Double.self, forKey: .t) ?? 0
    kind = try c.decode(String.self, forKey: .kind)
    text = try c.decodeIfPresent(String.self, forKey: .text)
    state = try c.decodeIfPresent(String.self, forKey: .state)
    hands = try c.decodeIfPresent(Int.self, forKey: .hands)
    liftCm = try c.decodeIfPresent(Double.self, forKey: .liftCm)
    name = try c.decodeIfPresent(String.self, forKey: .name)
    source = try c.decodeIfPresent(String.self, forKey: .source)
    by = try c.decodeIfPresent(String.self, forKey: .by)
    tool = try c.decodeIfPresent(String.self, forKey: .tool)
    seconds = try c.decodeIfPresent(Double.self, forKey: .seconds)
    verdict = try c.decodeIfPresent(String.self, forKey: .verdict)
    object = try c.decodeIfPresent(String.self, forKey: .object)
    what = try c.decodeIfPresent(String.self, forKey: .what)
    at = try c.decodeIfPresent(String.self, forKey: .at)
    contents = try c.decodeIfPresent([String].self, forKey: .contents)
    entry = try c.decodeIfPresent(Int.self, forKey: .entry)
    ratio = try c.decodeIfPresent(Double.self, forKey: .ratio)
    dogScore = try c.decodeIfPresent(Double.self, forKey: .dogScore)
    babyScore = try c.decodeIfPresent(Double.self, forKey: .babyScore)
    latencyS = try c.decodeIfPresent(Double.self, forKey: .latencyS)
    model = try c.decodeIfPresent(String.self, forKey: .model)
    frameUnix = try c.decodeIfPresent(Double.self, forKey: .frameUnix)
    held = try c.decodeIfPresent(String.self, forKey: .held)
    card = try c.decodeIfPresent(HUDAgentCard.self, forKey: .card)
    lang = try c.decodeIfPresent(String.self, forKey: .lang)
    skill = try c.decodeIfPresent(String.self, forKey: .skill)
    step = try c.decodeIfPresent(String.self, forKey: .step)
    cause = try c.decodeIfPresent(String.self, forKey: .cause)
    agentUnix = try c.decodeIfPresent(Double.self, forKey: .agentUnix)
  }
}

/// A card the agent wrote, already short and in the parent's language. `sticky` is a red flag: it stays on the display,
/// above everything, until the parent acknowledges it.
struct HUDAgentCard: Decodable, Equatable, Hashable, Sendable {
  var topic: String
  var icon: String
  var title: String
  var status: String
  var detail: String?
  var meta: String?
  var alert = false
  var sticky = false
  var lang: String?

  enum CodingKeys: String, CodingKey { case topic, icon, title, status, detail, meta, alert, sticky, lang }

  init(topic: String, icon: String, title: String, status: String, detail: String? = nil, meta: String? = nil,
       alert: Bool = false, sticky: Bool = false) {
    self.topic = topic
    self.icon = icon
    self.title = title
    self.status = status
    self.detail = detail
    self.meta = meta
    self.alert = alert
    self.sticky = sticky
  }

  init(from decoder: Decoder) throws {
    let c = try decoder.container(keyedBy: CodingKeys.self)
    topic = try c.decode(String.self, forKey: .topic)
    icon = try c.decode(String.self, forKey: .icon)
    title = try c.decode(String.self, forKey: .title)
    status = try c.decode(String.self, forKey: .status)
    detail = try c.decodeIfPresent(String.self, forKey: .detail)
    meta = try c.decodeIfPresent(String.self, forKey: .meta)
    alert = try c.decodeIfPresent(Bool.self, forKey: .alert) ?? false
    sticky = try c.decodeIfPresent(Bool.self, forKey: .sticky) ?? false
    lang = try c.decodeIfPresent(String.self, forKey: .lang)
  }
}

struct HUDScene: Decodable, Equatable, Sendable {
  let name: String
  let source: String
  var credit: String?
  let at: Double
  let length: Double
}

/// The live run's script (`HUD/hud-live.json`, written by `scripts/glasses_hud_live.py`): which part of the mock feed
/// plays when, and the parent's words, sent at feed times. Nothing in it is a detector output.
struct HUDLiveScript: Decodable, Sendable {
  struct Line: Decodable, Sendable {
    let at: Double
    let text: String
  }

  let feed: String
  let durationS: Double
  let scenes: [HUDScene]
  let say: [Line]

  enum CodingKeys: String, CodingKey {
    case feed, scenes, say
    case durationS = "duration_s"
  }

  func scene(at t: Double) -> HUDScene? {
    scenes.last { $0.at <= t }
  }
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
struct HUDCard: Hashable, Sendable {
  var icon: String
  var title: String
  var status: String
  var detail: String?
  var meta: String?
  var alert = false
  /// One button on the card (a red flag's "Got it"), its label. Taps come back to the app.
  var action: String?
}

/// Folds HUD events into the card the display shows. Pure, so the same logic runs on recorded outputs and live events.
struct HUDState: Equatable, Sendable {
  /// How long the spoken "hand" stays the headline.
  static let voiceHoldS = 1.6
  /// How long MediaPipe must see a hand on the baby again before the hidden-hand card goes.
  static let seenAgainS = 1.0
  /// Meta's display dims after 20 s without a change: a red flag changes its meta line every 15 s, so it never dims.
  static let keepAliveS = 15.0
  /// An agent card holds at least this long over the watch states of a running skill.
  static let agentHoldS = 6.0

  var lang = "en"
  var watchSkill: String?
  var agentCard: HUDAgentCard?
  var agentCardAt: Double?
  var redFlag: HUDAgentCard?
  var redFlagAt: Double?
  /// When the camera checks last changed what they show, so a newer check replaces an older agent card.
  var baseChangedAt = -Double.infinity

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
  var seenSince: Double?
  var lastReply: String?
  var closing = false
  var logged: HUDEvent?
  var dog: HUDEvent?

  mutating func apply(_ event: HUDEvent) {
    switch event.kind {
    case "armed", "closed", "alarm", "voice", "logged", "held", "clear":
      baseChangedAt = event.t
    case "dog" where event.verdict == "near":
      baseChangedAt = event.t
    case "reflex" where event.state != reflex && watchOn:
      baseChangedAt = event.t
    default:
      break
    }
    switch event.kind {
    case "hello":
      if let lang = event.lang { self.lang = lang == "es" ? "es" : "en" }
    case "card":
      guard let card = event.card else { break }
      if card.sticky {
        redFlag = card
        redFlagAt = event.t
      } else {
        agentCard = card
        agentCardAt = event.t
      }
    case "red_flag_clear":
      redFlag = nil
      redFlagAt = nil
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
      if let skill = event.skill { watchSkill = skill }
      if watchOn, event.by == "agent" { break }  // the skill's own "armed" never hides who armed it
      watchOn = true
      armedBy = event.by
      armTool = event.tool
      armSeconds = event.seconds
      logged = nil
      closing = false
      alarm = nil
      heldObject = nil
      heldVerdict = nil
    case "closed":
      watchOn = false
      closing = true
      alarm = nil
      lastReply = nil
      heldObject = nil
      heldVerdict = nil
    case "reflex":
      reflex = event.state
      hands = event.hands
      liftCm = event.liftCm ?? (event.state == "lifted" ? liftCm : nil)
      if event.held != nil || (event.hands ?? 0) == 0 || event.state != "on" {
        seenSince = nil
      } else if let since = seenSince {
        if event.t - since >= Self.seenAgainS {
          heldObject = nil
          heldVerdict = nil
        }
      } else {
        seenSince = event.t
      }
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

  /// The card at time `t` (same clock as the events). A red flag first, always. Then the camera's own alarms, the
  /// dog near the baby, then the newest agent card until a newer camera check replaces it, then the watch states.
  func card(at t: Double) -> HUDCard {
    if let redFlag {
      let elapsed = max(0, t - (redFlagAt ?? t))
      let shown = Int(elapsed / Self.keepAliveS) * Int(Self.keepAliveS)
      let since = String(format: "%d:%02d", shown / 60, shown % 60)
      return HUDCard(icon: redFlag.icon, title: redFlag.title, status: redFlag.status, detail: redFlag.detail,
                     meta: [redFlag.meta, "\(tr("since")) \(since)"].compactMap { $0 }.joined(separator: " · "),
                     alert: true, action: tr("Got it"))
    }
    let urgent = alarm != nil || (voicedAt.map { t - $0 < Self.voiceHoldS } ?? false) || dog?.verdict == "near"
    if !urgent, let agentCard, let at = agentCardAt, at >= baseChangedAt || t - at < Self.agentHoldS {
      return HUDCard(icon: agentCard.icon, title: agentCard.title, status: agentCard.status, detail: agentCard.detail,
                     meta: agentCard.meta, alert: agentCard.alert)
    }
    return watchCard(at: t)
  }

  /// The camera skills' own card: the dog, the logged change, the alarms and the watch.
  private func watchCard(at t: Double) -> HUDCard {
    if let dog, dog.verdict == "near" {
      return HUDCard(
        icon: "exclamationTriangle", title: tr("Dog near the baby"), status: tr("Dog close to the baby"),
        detail: "Gap \(Self.fmt(dog.ratio, 2)) baby sizes · dog \(Self.fmt(dog.dogScore, 2)) · baby \(Self.fmt(dog.babyScore, 2))",
        meta: "\(dog.model ?? "SAM 3.1") · alert to the parents", alert: true)
    }
    if scene == "dog" {
      return HUDCard(icon: "eye", title: tr("Dog watch"), status: tr("Looking for a dog near the baby"), detail: nil,
                     meta: "SAM 3.1 · dog, baby, bassinet, play mat")
    }
    if let logged {
      let contents = (logged.contents ?? []).joined(separator: " and ")
      return HUDCard(
        icon: "checkmarkCircle", title: tr("Logged"),
        status: "\((logged.what ?? "change").capitalized) at \(logged.at ?? "?")\(contents.isEmpty ? "" : " · \(contents)")",
        detail: lastReply, meta: "Read back from Baby Buddy · entry \(logged.entry.map(String.init) ?? "?")")
    }
    if closing {
      return HUDCard(icon: "pencil", title: tr("Done"), status: tr("Logging the change"), detail: nil,
                     meta: tr("Watch closed"))
    }
    let lifted = alarm == "lifted"
    let what = lifted
      ? (lang == "es" ? "Mano levantada\(liftCm.map { " \(Self.fmt($0, 1)) cm" } ?? "") del bebé"
                      : "Hand lifted\(liftCm.map { " \(Self.fmt($0, 1)) cm" } ?? "") off the baby")
      : tr("No hand on the baby")
    if let voicedAt, t - voicedAt < Self.voiceHoldS {
      return HUDCard(icon: "speakerWithThreeArcs", title: "\u{201C}hand\u{201D}", status: what,
                     detail: heldObject.map { "Holding a \($0)" }, meta: tr("Spoken on the glasses"), alert: true)
    }
    if let alarm {
      var meta = voicedAt == nil ? "Tone · \u{201C}hand\u{201D} if it lasts 1.2 s" : "\u{201C}hand\u{201D} spoken"
      if let confirm { meta += " · SAM 3.1: \(confirm)" }
      return HUDCard(icon: "exclamationTriangle", title: alarm == "lifted" ? tr("Hover") : tr("Hands off"), status: what,
                     detail: heldObject.map { "Holding a \($0)" }, meta: meta, alert: true)
    }
    if heldVerdict != nil || heldObject != nil {
      return HUDCard(
        icon: "eye", title: tr("Changing table"), status: heldObject.map { "Hand hidden by the \($0)" } ?? tr("Hands hidden from MediaPipe"),
        detail: heldVerdict == "on" ? tr("SAM 3.1 found the hand on the baby") : tr("SAM 3.1 is looking for the hand"),
        meta: watchMeta)
    }
    if watchOn {
      let status: String
      switch reflex {
      case "off": status = tr("No hand on the baby")
      case "lifted": status = tr("Hand lifting")
      default: status = tr("Hand on the baby")
      }
      return HUDCard(icon: watchSkill == "bath" ? "dropper" : "eye", title: tr(watchSkill == "bath" ? "Bath" : "Changing table"),
                     status: status, detail: lastReply, meta: watchMeta)
    }
    return HUDCard(icon: "smartGlasses", title: tr("Parenting agent"), status: "Say \u{201C}changing time\u{201D}",
                   detail: lastReply, meta: nil)
  }

  /// The HUD's own words in the wearer's language. Anything not in the table stays as written.
  static let spanish: [String: String] = [
    "Dog near the baby": "Perro cerca del bebé", "Dog close to the baby": "Perro pegado al bebé",
    "Dog watch": "Vigilancia de perro", "Looking for a dog near the baby": "Buscando un perro cerca del bebé",
    "Logged": "Anotado", "Done": "Listo", "Logging the change": "Anotando el cambio", "Watch closed": "Vigilancia cerrada",
    "Spoken on the glasses": "Dicho en los lentes", "Hands hidden from MediaPipe": "Manos ocultas para MediaPipe",
    "SAM 3.1 found the hand on the baby": "SAM 3.1 encontró la mano en el bebé",
    "SAM 3.1 is looking for the hand": "SAM 3.1 busca la mano", "Hand on the baby": "Mano en el bebé",
    "No hand on the baby": "Ninguna mano en el bebé", "Hand lifting": "Mano levantándose",
    "Parenting agent": "Agente de crianza", "Hands off": "Manos afuera", "Hover": "Mano en el aire",
    "Changing table": "Cambiador", "Bath": "Baño", "since": "hace", "Got it": "Entendido",
  ]

  func tr(_ english: String) -> String {
    lang == "es" ? (Self.spanish[english] ?? english) : english
  }

  private var watchMeta: String {
    var meta = "Watch on"
    if armedBy == "brain" { meta += " · armed by Muse" } else if let armedBy { meta += " · armed by \(armedBy)" }
    if let armSeconds { meta += " in \(Self.fmt(armSeconds, 1)) s" }
    return meta
  }

  /// The live agent's glasses events (`parenting_agent/glasses.py` `to_app`) as HUD events at the app's time `t`.
  /// The agent sends the checks themselves (armed, alarm, clear, confirm, held, logged, dog), so they pass through.
  /// The tone and the voice come from the skill's speaker, the hand state from every frame.
  static func live(_ event: HUDEvent, at t: Double, current: HUDState) -> [HUDEvent] {
    var event = event
    event.t = t
    switch event.kind {
    case "state":
      event.kind = "reflex"
      return [event]
    case "armed", "alarm", "clear", "confirm", "held", "logged", "dog", "reply", "card", "red_flag_clear":
      return [event]
    case "hello":
      return event.lang == nil ? [] : [event]
    case "voice":
      if let skill = event.skill, skill != "changing-table", skill != "bath" { return [] }  // the car seat coach has its own cards
      if event.text == nil { event.text = "hand" }
      return [event]
    case "skill":
      guard let text = event.text else { return [] }
      if event.skill == "car-seat" { return [] }
      if text.contains("armed") {
        var armed = HUDEvent(t: t, kind: "armed")
        armed.by = "agent"
        armed.skill = event.skill
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
