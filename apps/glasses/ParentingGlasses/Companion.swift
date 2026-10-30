import Foundation

struct LogLine: Identifiable {
  enum Who { case parent, agent, alert, system }
  let id = UUID()
  let at = Date()
  let who: Who
  let text: String
}

/// Wires the glasses to the agent: sampled frames up, replies down, spoken aloud and shown as text.
@Observable
@MainActor
final class Companion {
  let glasses: GlassesCamera
  let agent = AgentLink()
  @ObservationIgnored private let voice = Voice()

  var lines: [LogLine] = []
  var lastReply = "Say \"changing time\" and the agent starts watching through your glasses."
  var handsState: String?
  var handsCount: Int?
  var spokenCount = 0
  var alerts = 0

  /// The glasses display (HUD). The same card goes to the real display and, in the simulator, to Meta's mock preview.
  let hud = DisplayHUD()
  var hudState = HUDState()
  var hudCard = HUDState().card(at: 0)
  /// Set while the recorded HUD replay runs (Debug only).
  var replay: HUDReplay?
  var replayScene: HUDScene?
  var replayClock: Double = 0
  /// Set while the live HUD run plays its mock feed (Debug only): detectors and the agent run for real.
  var liveScript: HUDLiveScript?
  var liveScene: HUDScene?
  /// The newest card's latency, from the agent receiving the frame to the display accepting the card.
  var lastFrameToCard: Double?
  @ObservationIgnored private let started = Date()
  /// What made each card, for the latency log: the event kind, its frame's arrival and the event's arrival (Unix).
  @ObservationIgnored private var causes: [HUDCard: (kind: String, frameUnix: Double?, eventUnix: Double)] = [:]
  @ObservationIgnored private var hudLog: FileHandle?

  init() {
    let fps = UserDefaults.standard.double(forKey: "sendFPS")
    glasses = GlassesCamera(sendFPS: fps > 0 ? fps : 10)
    glasses.onSample = { [weak self] jpeg in self?.agent.send(frame: jpeg) }
    agent.onEvent = { [weak self] event, data in self?.received(event, data: data) }
    voice.onSpoken = { [weak self] _ in self?.spokenCount += 1 }
    glasses.onSessionStarted = { [weak self] session in self?.hud.attach(to: session) }
    hud.onSent = { [weak self] card, unix in self?.sent(card, at: unix) }
    #if DEBUG
    if UserDefaults.standard.bool(forKey: "hudReplay") { return }
    #endif
    agent.listen()
  }

  private func hudApply(_ events: [HUDEvent], at t: Double, cause: (kind: String, frameUnix: Double?)? = nil) {
    for event in events { hudState.apply(event) }
    let card = hudState.card(at: t)
    if card != hudCard, let cause {  // the newest cause of a card, so a card shown before never lends its old frame
      causes[card] = (cause.kind, cause.frameUnix, Date().timeIntervalSince1970)
    }
    hudCard = card
    hud.show(hudCard)
  }

  /// The display accepted a card: log it with what made it, so frame to card latency can be read from the run.
  private func sent(_ card: HUDCard, at unix: Double) {
    let cause = causes.removeValue(forKey: card)
    if let frame = cause?.frameUnix { lastFrameToCard = unix - frame }
    log(["kind": "sent", "title": card.title, "status": card.status, "detail": card.detail ?? "", "meta": card.meta ?? "",
         "cause": cause?.kind ?? "", "frame_unix": cause?.frameUnix ?? 0, "event_unix": cause?.eventUnix ?? 0, "unix": unix])
  }

  /// Debug runs with -hudLog YES append every agent event, parent line and display send to Documents/hud-live.jsonl.
  private func log(_ row: [String: Any]) {
    #if DEBUG
    guard UserDefaults.standard.bool(forKey: "hudLog") else { return }
    if hudLog == nil, let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first {
      let url = docs.appendingPathComponent("hud-live.jsonl")
      try? Data().write(to: url)
      hudLog = try? FileHandle(forWritingTo: url)
    }
    if let data = try? JSONSerialization.data(withJSONObject: row) {
      hudLog?.write(data + Data("\n".utf8))
    }
    #endif
  }

  func say(_ text: String) {
    let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !text.isEmpty else { return }
    add(.parent, text)
    log(["kind": "say", "text": text, "unix": Date().timeIntervalSince1970])
    agent.say(text)
  }

  private func add(_ who: LogLine.Who, _ text: String) {
    lines.append(LogLine(who: who, text: text))
    if lines.count > 40 { lines.removeFirst(lines.count - 40) }
  }

  private func received(_ event: AgentEvent, data: Data) {
    let t = Date().timeIntervalSince(started)
    if let live = try? JSONDecoder().decode(HUDEvent.self, from: data) {
      if event.kind != "state", event.kind != "hello" {
        log(["kind": "event", "event": event.kind, "frame_unix": live.frameUnix ?? 0, "unix": Date().timeIntervalSince1970,
             "text": event.text ?? "", "verdict": live.verdict ?? "", "state": event.state ?? ""])
      }
      hudApply(HUDState.live(live, at: t, current: hudState), at: t, cause: (event.kind, live.frameUnix))
    }
    if event.kind == "voice" {
      Task { [weak self] in
        try? await Task.sleep(for: .seconds(HUDState.voiceHoldS + 0.1))
        guard let self else { return }
        self.hudApply([], at: Date().timeIntervalSince(self.started))
      }
    }
    switch event.kind {
    case "reply":
      guard let text = event.text, !text.isEmpty else { return }
      lastReply = text
      add(.agent, text)
      voice.speak(text)
    case "voice":
      let text = event.text ?? "hand"
      alerts += 1
      lastReply = text
      add(.alert, "said \"\(text)\"")
      voice.speak(text, urgent: true)
    case "chime":
      add(.alert, "chime")
      voice.chime()
    case "state":
      handsState = event.state
      handsCount = event.hands
    case "skill":
      if let text = event.text { add(.system, text) }
    default:
      break
    }
  }

  #if DEBUG
  /// Simulator HUD replay: a mock Meta Ray-Ban Display whose camera plays `MockFeed/hud-feed.mp4` (our synthetic
  /// clips) while the HUD replays recorded detector outputs from `HUD/hud-replay.json`, on the clock of the first
  /// camera frame. No agent and no model run. Both files come from `scripts/glasses_hud_replay.py`.
  func runHUDReplay() async {
    guard
      let feed = Bundle.main.url(forResource: "hud-feed", withExtension: "mp4"),
      let url = Bundle.main.url(forResource: "hud-replay", withExtension: "json")
    else {
      add(.system, "No HUD feed or replay in the app. Run scripts/glasses_hud_replay.py --feed and build again.")
      return
    }
    let replay: HUDReplay
    do {
      replay = try JSONDecoder().decode(HUDReplay.self, from: Data(contentsOf: url))
    } catch {
      add(.system, "HUD replay: \(error.localizedDescription)")
      return
    }
    self.replay = replay
    glasses.onSample = nil
    add(.system, "Mock Meta Ray-Ban Display paired (DAT MockDeviceKit)")
    glasses.pairMockGlasses(feed: feed, model: .metaRayBanDisplay)
    await glasses.start()
    for _ in 0..<150 where glasses.framesIn == 0 { try? await Task.sleep(for: .milliseconds(100)) }
    let lead = UserDefaults.standard.double(forKey: "hudLeadSeconds")
    let clock = Date().addingTimeInterval(-lead)
    var next = 0
    while replayClock <= replay.durationS + 2 {
      replayClock = Date().timeIntervalSince(clock)
      var due: [HUDEvent] = []
      while next < replay.events.count, replay.events[next].t <= replayClock {
        due.append(replay.events[next])
        next += 1
      }
      for event in due {
        switch event.kind {
        case "voice":
          add(.alert, "said \"\(event.text ?? "hand")\"")
          voice.speak(event.text ?? "hand", urgent: true)
        case "chime":
          add(.alert, "tone")
          voice.chime()
        case "scene":
          replayScene = replay.scenes.first { $0.name == event.name }
        case "parent":
          add(.parent, event.text ?? "")
        case "reply":
          add(.agent, event.text ?? "")
        default:
          break
        }
      }
      hudApply(due, at: replayClock)
      try? await Task.sleep(for: .milliseconds(50))
    }
  }

  /// Simulator live HUD run: a mock Meta Ray-Ban Display whose camera plays `MockFeed/<feed>.mp4` (our synthetic clips and
  /// a licensed photo) through DAT to the real agent, which runs MediaPipe, SAM 3.1 and Muse on the frames and sends its
  /// events back. The display shows what the agent sends. The only scripted part is the parent's words, sent at the feed
  /// times in `HUD/hud-live.json` (`scripts/glasses_hud_live.py`).
  func runHUDLive() async {
    guard
      let url = Bundle.main.url(forResource: "hud-live", withExtension: "json"),
      let script = try? JSONDecoder().decode(HUDLiveScript.self, from: Data(contentsOf: url)),
      let feed = Bundle.main.url(forResource: script.feed, withExtension: "mp4")
    else {
      add(.system, "No live script or feed in the app. Run scripts/glasses_hud_live.py --build-feed and build again.")
      return
    }
    liveScript = script
    add(.system, "Mock Meta Ray-Ban Display paired (DAT MockDeviceKit)")
    glasses.pairMockGlasses(feed: feed, model: .metaRayBanDisplay)
    for _ in 0..<100 where !agent.connected { try? await Task.sleep(for: .milliseconds(100)) }
    await glasses.start()
    for _ in 0..<150 where glasses.framesIn == 0 { try? await Task.sleep(for: .milliseconds(100)) }
    let clock = Date()
    log(["kind": "feed_start", "unix": clock.timeIntervalSince1970])
    var next = 0
    while true {
      let t = Date().timeIntervalSince(clock)
      if liveScene != script.scene(at: t) {
        liveScene = script.scene(at: t)
        log(["kind": "scene", "name": liveScene?.name ?? "", "feed_s": t, "unix": Date().timeIntervalSince1970])
      }
      while next < script.say.count, script.say[next].at <= t {
        say(script.say[next].text)
        next += 1
      }
      if t > script.durationS { break }
      try? await Task.sleep(for: .milliseconds(50))
    }
    log(["kind": "feed_end", "unix": Date().timeIntervalSince1970])
  }

  /// Simulator demo: mock glasses on, the synthetic changing-table clip as their camera, then the parent's two lines.
  /// The launch argument -mockFeed NAME plays MockFeed/NAME.mp4 instead (for example a hover or a touch clip), and
  /// -demoDone TEXT is the parent's closing line instead of "done" (for example "done, it was dirty"), and
  /// -demoAsk TEXT asks one more question after "done" (for example the last diaper, read back from the baby log).
  func runDemo() async {
    let name = UserDefaults.standard.string(forKey: "mockFeed") ?? "changing-table-feed"
    guard let feed = Bundle.main.url(forResource: name, withExtension: "mp4") else {
      add(.system, "No mock feed in the app. Run apps/glasses/scripts/make-mock-feed.sh and build again.")
      return
    }
    add(.system, "Mock Ray-Ban Meta paired (DAT MockDeviceKit)")
    glasses.pairMockGlasses(feed: feed)
    await glasses.start()
    for _ in 0..<100 where !(glasses.isStreaming && agent.connected) { try? await Task.sleep(for: .milliseconds(200)) }
    try? await Task.sleep(for: .seconds(2))
    say("changing time")
    let watch = UserDefaults.standard.double(forKey: "demoWatchSeconds")
    try? await Task.sleep(for: .seconds(watch > 0 ? watch : 20))
    let done = UserDefaults.standard.string(forKey: "demoDone") ?? ""
    say(done.isEmpty ? "done" : done)
    if let question = UserDefaults.standard.string(forKey: "demoAsk"), !question.isEmpty {
      let wait = UserDefaults.standard.double(forKey: "demoAskAfterSeconds")
      try? await Task.sleep(for: .seconds(wait > 0 ? wait : 12))
      say(question)
    }
  }
  #endif
}
