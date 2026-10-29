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

  init() {
    let fps = UserDefaults.standard.double(forKey: "sendFPS")
    glasses = GlassesCamera(sendFPS: fps > 0 ? fps : 10)
    glasses.onSample = { [weak self] jpeg in self?.agent.send(frame: jpeg) }
    agent.onEvent = { [weak self] event in self?.received(event) }
    voice.onSpoken = { [weak self] _ in self?.spokenCount += 1 }
    agent.listen()
  }

  func say(_ text: String) {
    let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !text.isEmpty else { return }
    add(.parent, text)
    agent.say(text)
  }

  private func add(_ who: LogLine.Who, _ text: String) {
    lines.append(LogLine(who: who, text: text))
    if lines.count > 40 { lines.removeFirst(lines.count - 40) }
  }

  private func received(_ event: AgentEvent) {
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
  /// Simulator demo: mock glasses on, the synthetic changing-table clip as their camera, then the parent's two lines.
  func runDemo() async {
    guard let feed = Bundle.main.url(forResource: "changing-table-feed", withExtension: "mp4") else {
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
    say("done")
  }
  #endif
}
