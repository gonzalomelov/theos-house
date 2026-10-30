import Foundation
import MWDATCamera
import MWDATCore
import UIKit

#if DEBUG
import MWDATMockDevice
#endif

/// Decides which glasses frames go to the agent and which refresh the preview. Called on the SDK's frame thread.
final class FrameGate: @unchecked Sendable {
  private let lock = NSLock()
  private var lastSent = Date.distantPast
  private var lastPreview = Date.distantPast
  private var sendInterval: TimeInterval
  private let previewInterval: TimeInterval = 1.0 / 12
  private(set) var framesIn = 0

  init(sendFPS: Double) { sendInterval = 1 / max(sendFPS, 0.5) }

  func setSendFPS(_ fps: Double) {
    lock.lock(); sendInterval = 1 / max(fps, 0.5); lock.unlock()
  }

  /// Returns whether this frame should be sent to the agent and whether it should refresh the preview.
  func tick(now: Date = Date()) -> (send: Bool, preview: Bool, count: Int) {
    lock.lock(); defer { lock.unlock() }
    framesIn += 1
    let send = now.timeIntervalSince(lastSent) >= sendInterval
    if send { lastSent = now }
    let preview = now.timeIntervalSince(lastPreview) >= previewInterval
    if preview { lastPreview = now }
    return (send, preview, framesIn)
  }
}

/// The glasses side: one DAT device session, one camera stream, frames sampled to the agent's rate.
@Observable
@MainActor
final class GlassesCamera {
  var registration: RegistrationState
  var hasDevice = false
  var sessionState: DeviceSessionState = .idle
  var streamState: StreamState = .stopped
  var preview: UIImage?
  var framesIn = 0
  var sendFPS: Double
  var isMock = false
  var message: String?

  @ObservationIgnored var onSample: ((Data) -> Void)?
  /// Called once the device session is up, before the camera starts. The HUD attaches the display here.
  @ObservationIgnored var onSessionStarted: ((DeviceSession) -> Void)?
  #if DEBUG
  @ObservationIgnored private(set) var mockGlasses: (any MockGlasses)?
  #endif
  @ObservationIgnored private let wearables: WearablesInterface
  @ObservationIgnored private let selector: AutoDeviceSelector
  @ObservationIgnored private var session: DeviceSession?
  @ObservationIgnored private var camera: MWDATCamera.Camera?
  @ObservationIgnored private let sessionTokens = ListenerTokenBag()
  @ObservationIgnored private let streamTokens = ListenerTokenBag()
  @ObservationIgnored private let gate: FrameGate
  @ObservationIgnored private var tasks: [Task<Void, Never>] = []

  init(wearables: WearablesInterface = Wearables.shared, sendFPS: Double) {
    self.wearables = wearables
    self.selector = AutoDeviceSelector(wearables: wearables)
    self.registration = wearables.registrationState
    self.sendFPS = sendFPS
    self.gate = FrameGate(sendFPS: sendFPS)
    tasks.append(Task { [weak self] in
      guard let self else { return }
      for await state in wearables.registrationStateStream() { self.registration = state }
    })
    tasks.append(Task { [weak self] in
      guard let self else { return }
      for await device in selector.activeDeviceStream() { self.hasDevice = device != nil }
    })
  }

  var isStreaming: Bool { streamState == .streaming }

  var streamText: String {
    switch streamState {
    case .streaming: return "streaming"
    case .starting: return "starting"
    case .waitingForDevice: return "waiting for glasses"
    case .stopping: return "stopping"
    case .stopped: return "stopped"
    case .paused: return "paused"
    }
  }

  func setSendFPS(_ fps: Double) {
    sendFPS = fps
    gate.setSendFPS(fps)
  }

  /// Real glasses: opens the Meta AI app once so the parent approves this app.
  func register() {
    Task {
      do { try await wearables.startRegistration() } catch { message = "\(error)" }
    }
  }

  func handle(url: URL) {
    Task { _ = try? await wearables.handleUrl(url) }
  }

  #if DEBUG
  /// Simulator and tests: mock glasses from Meta's MockDeviceKit, worn, with a video file as their camera.
  /// `.metaRayBanDisplay` also gives the session a display, rendered on the phone by MockDisplayKit.
  func pairMockGlasses(feed: URL, model: GlassesModel = .rayBanMeta) {
    let kit = MockDeviceKit.shared
    kit.enable()
    do {
      let device = try kit.pairGlasses(model: model)
      mockGlasses = device
      device.powerOn()
      device.unfold()
      device.don()
      device.services.camera.setCameraFeed(fileURL: feed)
      isMock = true
    } catch {
      message = "mock glasses: \(error.localizedDescription)"
    }
  }
  #endif

  /// Starts the device session, then the camera stream once the session is up.
  func start() async {
    guard session == nil else { return }
    for _ in 0..<50 where !hasDevice { try? await Task.sleep(for: .milliseconds(200)) }
    guard hasDevice else {
      message = "No glasses found. Put them on, unfolded, with Developer Mode on in the Meta AI app."
      return
    }
    do {
      let session = try wearables.createSession(deviceSelector: selector)
      self.session = session
      session.statePublisher.listen { [weak self] state in
        Task { @MainActor in self?.sessionChanged(state) }
      }.store(in: sessionTokens)
      session.errorPublisher.listen { [weak self] error in
        Task { @MainActor in self?.message = error.localizedDescription }
      }.store(in: sessionTokens)
      sessionState = .starting
      try session.start()
    } catch {
      message = error.localizedDescription
      session = nil
      sessionState = .idle
    }
  }

  func stop() {
    camera?.stop()
    session?.stop()
  }

  private func sessionChanged(_ state: DeviceSessionState) {
    sessionState = state
    if state == .started, camera == nil {
      if let session { onSessionStarted?(session) }
      Task { await startStream() }
    } else if state == .stopped {
      sessionTokens.clear()
      streamTokens.clear()
      session = nil
      camera = nil
      streamState = .stopped
    }
  }

  private func startStream() async {
    guard let session, camera == nil else { return }
    do {
      if try await wearables.checkPermissionStatus(.camera) != .granted {
        guard try await wearables.requestPermission(.camera) == .granted else {
          message = "Camera permission was not given in the Meta AI app."
          return
        }
      }
      // Decoded frames, the medium size, 15 fps from the glasses. The app samples them down to sendFPS.
      let config = StreamConfiguration(videoCodec: .raw, resolution: .medium, frameRate: 15)
      guard let camera = try session.addCamera(config: config) else {
        message = "The glasses camera could not start. Try again."
        return
      }
      self.camera = camera
      let stream = camera.stream
      stream.statePublisher.listen { [weak self] state in
        Task { @MainActor in self?.streamState = state }
      }.store(in: streamTokens)
      stream.errorPublisher.listen { [weak self] error in
        Task { @MainActor in self?.message = error.localizedDescription }
      }.store(in: streamTokens)
      let gate = self.gate
      stream.videoFramePublisher.listen { [weak self] frame in
        let tick = gate.tick()
        guard tick.send || tick.preview, let image = frame.makeUIImage() else { return }
        let jpeg = tick.send ? image.jpegData(compressionQuality: 0.7) : nil
        Task { @MainActor in
          guard let self else { return }
          self.framesIn = tick.count
          if tick.preview { self.preview = image }
          if let jpeg { self.onSample?(jpeg) }
        }
      }.store(in: streamTokens)
      streamState = .starting
      stream.start()
    } catch {
      message = error.localizedDescription
    }
  }
}
