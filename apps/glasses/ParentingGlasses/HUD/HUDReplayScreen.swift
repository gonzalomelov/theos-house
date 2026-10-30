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

/// The simulator screen for the recorded HUD replay: what the wearer sees, the head camera with the in-lens display
/// over it, and labels that say what is simulated and where every detector output comes from.
struct HUDReplayScreen: View {
  let companion: Companion

  private var glasses: GlassesCamera { companion.glasses }

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
        Text("SIMULATED").font(.caption.bold()).padding(.horizontal, 8).padding(.vertical, 3)
          .background(Color.orange, in: Capsule()).foregroundStyle(.black)
        Text("Meta Ray-Ban Display HUD").font(.headline)
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
            .overlay(alignment: .topTrailing) {
              Text("600 × 600 in-lens display, enlarged").font(.system(size: 9, weight: .semibold))
                .padding(.horizontal, 5).padding(.vertical, 2).background(.black.opacity(0.6), in: Capsule())
                .padding(6)
            }
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
  }

  private var sceneCaption: some View {
    VStack(alignment: .leading, spacing: 3) {
      if let replay = companion.replay, let scene = companion.replayScene,
         let index = replay.scenes.firstIndex(of: scene) {
        Text("Scene \(index + 1) of \(replay.scenes.count) · \(scene.name.capitalized)").font(.subheadline.bold())
        Text("Detector outputs replayed from \(scene.source)").font(.caption).foregroundStyle(.secondary)
        if let credit = scene.credit { Text(credit).font(.caption2).foregroundStyle(.secondary) }
      } else {
        Text(glasses.message ?? "Waiting for the mock glasses camera").font(.subheadline.bold())
      }
      Text("Display \(String(describing: companion.hud.state)) · \(companion.hud.sent) views sent")
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
    Text("Camera: our synthetic clips and a licensed photo. MediaPipe and SAM 3.1 outputs are recorded (Oct 29), not run now. Gaps between scenes shortened. Camera dimmed so the additive display reads on video.")
      .font(.caption2).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
      .padding(.bottom, 4)
  }

  private func label(_ who: LogLine.Who) -> String {
    switch who {
    case .parent: return "You"
    case .agent: return "Muse"
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
