import SwiftUI

struct ContentView: View {
  @Bindable var companion: Companion
  @State private var draft = ""
  @State private var showSettings = false

  private var glasses: GlassesCamera { companion.glasses }
  private var agent: AgentLink { companion.agent }

  var body: some View {
    #if DEBUG
    if companion.replay != nil || companion.liveScript != nil || companion.dayCaption != nil {
      HUDReplayScreen(companion: companion)
    } else {
      main
    }
    #else
    main
    #endif
  }

  private var main: some View {
    VStack(spacing: 12) {
      header
      preview
      replyCard
      log
      controls
    }
    .padding(.horizontal, 16)
    .padding(.top, 8)
    .background(Color(red: 0.07, green: 0.08, blue: 0.10).ignoresSafeArea())
    .preferredColorScheme(.dark)
    .sheet(isPresented: $showSettings) { SettingsView(companion: companion) }
  }

  private var header: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack {
        VStack(alignment: .leading, spacing: 2) {
          Text("Parenting agent").font(.title2.bold())
          Text("Ray-Ban Meta head camera").font(.subheadline).foregroundStyle(.secondary)
        }
        Spacer()
        Button { showSettings = true } label: { Image(systemName: "gearshape").font(.title3) }
          .accessibilityLabel("Settings")
      }
      HStack(spacing: 6) {
        Chip(text: (glasses.isMock ? "Mock glasses · " : "Glasses · ") + (glasses.isStreaming ? "live" : glasses.streamText),
             on: glasses.isStreaming)
        Chip(text: agent.connected ? "Agent connected" : "Agent offline", on: agent.connected)
        Chip(text: "\(Int(glasses.sendFPS)) fps · \(agent.framesSent) sent", on: agent.framesSent > 0)
      }
      if let mic = companion.micStatus {
        Text(mic).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
      }
    }
  }

  private var preview: some View {
    ZStack(alignment: .topLeading) {
      RoundedRectangle(cornerRadius: 16).fill(Color.black)
      if let image = glasses.preview {
        Image(uiImage: image).resizable().scaledToFit().clipShape(RoundedRectangle(cornerRadius: 16))
      } else {
        Text(glasses.message ?? "Glasses camera off").foregroundStyle(.secondary).padding()
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      }
      HStack(spacing: 6) {
        Circle().fill(glasses.isStreaming ? Color.red : Color.gray).frame(width: 8, height: 8)
        Text("HEAD CAMERA").font(.caption.bold())
      }
      .padding(.horizontal, 8).padding(.vertical, 4)
      .background(.black.opacity(0.6), in: Capsule())
      .padding(10)
      if let state = companion.handsState {
        VStack {
          Spacer()
          HStack {
            Text(state == "on" ? "Hand on the baby" : state == "off" ? "No hand on the baby" : "Looking")
              .font(.caption.bold())
              .padding(.horizontal, 8).padding(.vertical, 4)
              .background((state == "on" ? Color.green : state == "off" ? Color.orange : Color.gray).opacity(0.85), in: Capsule())
            Spacer()
          }
        }
        .padding(10)
      }
    }
    .frame(height: 210)
  }

  private var replyCard: some View {
    HStack(alignment: .top, spacing: 10) {
      Image(systemName: "speaker.wave.2.fill").foregroundStyle(.tint)
      Text(companion.lastReply)
        .font(.title3.weight(.semibold))
        .frame(maxWidth: .infinity, alignment: .leading)
        .lineLimit(5)
        .minimumScaleFactor(0.7)
    }
    .padding(14)
    .background(Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 14))
    .accessibilityIdentifier("lastReply")
  }

  private var log: some View {
    ScrollViewReader { proxy in
      ScrollView {
        VStack(alignment: .leading, spacing: 6) {
          ForEach(companion.lines) { line in
            HStack(alignment: .top, spacing: 8) {
              Text(line.at, format: .dateTime.hour(.twoDigits(amPM: .omitted)).minute().second())
                .font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
              Text(label(line.who)).font(.caption.bold()).foregroundStyle(color(line.who))
              Text(line.text).font(.caption)
            }
            .id(line.id)
          }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
      }
      .onChange(of: companion.lines.count) {
        if let last = companion.lines.last { proxy.scrollTo(last.id, anchor: .bottom) }
      }
    }
    .frame(maxHeight: .infinity)
  }

  private var controls: some View {
    VStack(spacing: 8) {
      if !glasses.isStreaming {
        HStack {
          Button("Connect glasses") {
            if glasses.registration != .registered { glasses.register() }
            Task { await companion.connect() }
          }
          .buttonStyle(.borderedProminent)
          #if DEBUG
          Button("Mock glasses") { Task { await companion.runDemo() } }.buttonStyle(.bordered)
          #endif
        }
      }
      HStack {
        ForEach(["changing time", "done", "bath time"], id: \.self) { phrase in
          Button(phrase) { companion.say(phrase) }.buttonStyle(.bordered).font(.callout)
        }
      }
      HStack {
        TextField("Talk to the agent", text: $draft)
          .textFieldStyle(.roundedBorder)
          .onSubmit(send)
        Button(action: send) { Image(systemName: "arrow.up.circle.fill").font(.title2) }
      }
      if let error = agent.lastError {
        Text(error).font(.caption2).foregroundStyle(.orange)
      }
    }
    .padding(.bottom, 4)
  }

  private func send() {
    companion.say(draft)
    draft = ""
  }

  private func label(_ who: LogLine.Who) -> String {
    switch who {
    case .parent: return "You"
    case .agent: return "Agent"
    case .alert: return "Alert"
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

struct Chip: View {
  let text: String
  let on: Bool

  var body: some View {
    Text(text)
      .font(.caption2.weight(.semibold))
      .lineLimit(1)
      .padding(.horizontal, 8).padding(.vertical, 4)
      .background((on ? Color.green : Color.gray).opacity(0.25), in: Capsule())
      .foregroundStyle(on ? Color.green : Color.secondary)
  }
}

struct SettingsView: View {
  let companion: Companion
  @AppStorage("agentURL") private var agentURL = "http://127.0.0.1:8766"
  @AppStorage("agentToken") private var agentToken = ""
  @AppStorage("sendFPS") private var sendFPS = 10.0
  @AppStorage("micSource") private var micSource = MicSource.hfp.rawValue
  @Environment(\.dismiss) private var dismiss

  var body: some View {
    NavigationStack {
      Form {
        Section("Agent on your computer") {
          TextField("http://192.0.2.10:8766", text: $agentURL)
            .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
          SecureField("Pairing token", text: $agentToken)
        }
        Section("Frames to the agent") {
          Stepper("\(Int(sendFPS)) per second", value: $sendFPS, in: 1...15)
        }
        Section {
          Picker("Microphone", selection: $micSource) {
            ForEach([MicSource.hfp, .stream, .glassesASR, .off]) { Text($0.label).tag($0.rawValue) }
          }
        } header: {
          Text("Your voice")
        } footer: {
          Text("Heard by Muse Spark Open, the agent's model. Only words for the agent count: \"changing time\", an answer it is waiting for, or anything after \"agente\". Takes effect at the next connect.")
        }
      }
      .navigationTitle("Settings")
      .toolbar {
        Button("Done") {
          companion.glasses.setSendFPS(sendFPS)
          companion.agent.listen()
          dismiss()
        }
      }
    }
  }
}
