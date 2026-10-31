#if DEBUG
import MWDATMockDevice
import SwiftUI
import UIKit

/// Meta's MockDisplayKit preview of the Meta Ray-Ban Display: the 600 x 600 display surface, transparent outside the
/// content, drawing exactly what the app sent through `MWDATDisplay`.
struct MockDisplayPreview: UIViewRepresentable {
  let glasses: any MockGlasses

  func makeUIView(context: Context) -> UIView {
    let container = UIView()
    container.backgroundColor = .clear
    let preview = glasses.services.display.createPreviewView()
    preview.frame = container.bounds
    preview.autoresizingMask = [.flexibleWidth, .flexibleHeight]
    container.addSubview(preview)
    return container
  }

  func updateUIView(_ uiView: UIView, context: Context) {}
}

/// The simulator screen for the HUD: what the wearer sees, the head camera with the in-lens display over it, and labels
/// that say what is simulated and where every detector output comes from. The recorded replay and the live run
/// (`Companion.runHUDLive`, detectors and agent running) share it.
struct HUDReplayScreen: View {
  let companion: Companion

  private var glasses: GlassesCamera { companion.glasses }
  private var day: Bool { companion.dayCaption != nil }
  private var live: Bool { companion.liveScript != nil || day }

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      simulatedBanner
      lens
      sceneCaption
      events
      Spacer(minLength: 0)
      footer
    }
    .padding(.horizontal, 16)
    .padding(.top, 6)
    .background(Color(red: 0.05, green: 0.05, blue: 0.07).ignoresSafeArea())
    .preferredColorScheme(.dark)
  }

  private var simulatedBanner: some View {
    VStack(alignment: .leading, spacing: 4) {
      HStack(spacing: 6) {
        Text(live ? "LIVE" : "SIMULATED").font(.caption.bold()).padding(.horizontal, 8).padding(.vertical, 3)
          .background(live ? Color.green : Color.orange, in: Capsule()).foregroundStyle(.black)
        Text("Meta Ray-Ban Display HUD").font(.headline)
      }
      if day {
        Text("Live: the family agent running on this Mac, glasses and lens simulated by Meta's mock")
          .font(.caption.bold()).fixedSize(horizontal: false, vertical: true)
        Text("A day compressed: the agent's clock jumps between moments. Telegram captured, house dry.")
          .font(.caption2).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
      } else if live {
        Text("Live: detectors and agent running, glasses and lens simulated by Meta's mock")
          .font(.caption.bold()).fixedSize(horizontal: false, vertical: true)
      }
      Text("Real DAT Display API (MWDATDisplay 1.0.1), drawn by Meta's MockDisplayKit in the iOS simulator. No real glasses.")
        .font(.caption2).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
    }
  }

  /// The wearer's view: the head camera, with the display's light added on top of it the way the additive display
  /// adds light to the world (black adds nothing). The display square is enlarged for legibility, and the world is
  /// dimmed the way the Display Simulator's background brightness setting dims it.
  private var lens: some View {
    GeometryReader { geo in
      let width = geo.size.width
      let height = geo.size.height
      let display = height * 0.94
      ZStack(alignment: .topLeading) {
        Color.black
        if let image = glasses.preview {
          Image(uiImage: image).resizable().scaledToFill().frame(width: width, height: height).clipped()
            .brightness(-0.3)
        }
        if let mock = glasses.mockGlasses {
          MockDisplayPreview(glasses: mock)
            .frame(width: display, height: display)
            .blendMode(.plusLighter)
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(.white.opacity(0.3), lineWidth: 1))
            .offset(x: width - display - (height - display) / 2, y: (height - display) / 2)
        }
        HStack(spacing: 6) {
          Circle().fill(glasses.isStreaming ? Color.red : Color.gray).frame(width: 7, height: 7)
          Text("HEAD CAMERA · DAT MockDeviceKit").font(.system(size: 10, weight: .bold))
        }
        .padding(.horizontal, 8).padding(.vertical, 4)
        .background(.black.opacity(0.6), in: Capsule())
        .padding(8)
      }
      .frame(width: width, height: height)
      .compositingGroup()
      .clipShape(RoundedRectangle(cornerRadius: 16))
    }
    .aspectRatio(4 / 3, contentMode: .fit)
    .overlay(alignment: .bottomTrailing) {
      // Under the lens, so it never covers the head camera label or the card
      Text("600 × 600 in-lens display, enlarged").font(.system(size: 9, weight: .semibold)).foregroundStyle(.secondary)
        .alignmentGuide(.bottom) { $0[.top] - 3 }
    }
    .padding(.bottom, 12)
  }

  private var sceneCaption: some View {
    VStack(alignment: .leading, spacing: 3) {
      if let caption = companion.dayCaption {
        Text("\(caption.name)\(companion.wearer.map { " · \($0.capitalized)'s glasses" } ?? "")").font(.subheadline.bold())
        if !caption.source.isEmpty { Text(caption.source).font(.caption).foregroundStyle(.secondary) }
      } else if let script = companion.liveScript, let scene = companion.liveScene,
         let index = script.scenes.firstIndex(of: scene) {
        Text("Scene \(index + 1) of \(script.scenes.count) · \(scene.name.capitalized)").font(.subheadline.bold())
        Text(scene.source).font(.caption).foregroundStyle(.secondary)
        if let credit = scene.credit { Text(credit).font(.caption2).foregroundStyle(.secondary) }
      } else if let replay = companion.replay, let scene = companion.replayScene,
         let index = replay.scenes.firstIndex(of: scene) {
        Text("Scene \(index + 1) of \(replay.scenes.count) · \(scene.name.capitalized)").font(.subheadline.bold())
        Text("Detector outputs replayed from \(scene.source)").font(.caption).foregroundStyle(.secondary)
        if let credit = scene.credit { Text(credit).font(.caption2).foregroundStyle(.secondary) }
      } else {
        Text(glasses.message ?? "Waiting for the mock glasses camera").font(.subheadline.bold())
      }
      Text("Display \(String(describing: companion.hud.state)) · \(companion.hud.sent) views sent"
           + (live ? " · \(companion.agent.framesSent) frames to the agent" : "")
           + (companion.lastFrameToCard.map { String(format: " · frame to card %.2f s", $0) } ?? ""))
        .font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
      if let error = companion.hud.lastError { Text(error).font(.caption2).foregroundStyle(.orange) }
    }
  }

  private var events: some View {
    VStack(alignment: .leading, spacing: 3) {
      ForEach(companion.lines.suffix(5)) { line in
        HStack(spacing: 6) {
          Text(label(line.who)).font(.caption.bold()).foregroundStyle(color(line.who))
          Text(line.text).font(.caption).lineLimit(1)
        }
      }
    }
  }

  private var footer: some View {
    Text(day
         ? "Camera: our synthetic car seat clip played by DAT MockDeviceKit. The family agent runs here: Muse Spark Open on Baseten, Baby Buddy with the test child, SAM 3.1 on this Mac for the car seat step. The parents' words are typed by the run's script. Real time on screen, the agent's clock jumps between moments of the day."
         : live
         ? "Camera: our synthetic clips and a licensed photo, played by DAT MockDeviceKit. MediaPipe and SAM 3.1 run on this Mac, Muse Spark Open on Baseten, the diaper goes to Baby Buddy (test child). The parent's words are typed by the run's script. Recorded in real time, not edited. Camera dimmed so the additive display reads on video."
         : "Camera: our synthetic clips and a licensed photo. MediaPipe and SAM 3.1 outputs are recorded (Oct 29), not run now. Gaps between scenes shortened. Camera dimmed so the additive display reads on video.")
      .font(.caption2).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
      .padding(.bottom, 4)
  }

  private func label(_ who: LogLine.Who) -> String {
    switch who {
    case .parent: return "You"
    case .agent: return day ? "Agent" : "Muse"
    case .alert: return "Glasses"
    case .system: return "App"
    }
  }

  private func color(_ who: LogLine.Who) -> Color {
    switch who {
    case .parent: return .blue
    case .agent: return .green
    case .alert: return .orange
    case .system: return .secondary
    }
  }
}
#endif
