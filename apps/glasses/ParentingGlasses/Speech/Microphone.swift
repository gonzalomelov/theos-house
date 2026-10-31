import AVFoundation
import Foundation

/// Where the parent's voice comes from. See apps/glasses/SPEECH.md for what Meta's DAT 1.0.1 allows.
enum MicSource: String, CaseIterable, Identifiable {
  /// The glasses microphones over Bluetooth HFP (Meta's documented route, not beta). With no glasses connected, iOS
  /// gives the iPhone's own microphone on the same code path: the fallback.
  case hfp
  /// The glasses microphones in band with the DAT camera stream (`StreamConfiguration.audioCodec`, beta in DAT 1.0).
  case stream
  /// Transcribed on the glasses by DAT's Speech capability (`MWDATSpeech`, beta): text, no audio leaves the glasses.
  case glassesASR
  case off
  #if DEBUG
  /// Simulator: recorded audio fed into the same cutter the real microphones feed. Nothing else is mocked.
  case mock
  #endif

  var id: String { rawValue }

  var label: String {
    switch self {
    case .hfp: return "Glasses mic (Bluetooth HFP), iPhone mic without glasses"
    case .stream: return "Glasses mic in the camera stream (DAT beta)"
    case .glassesASR: return "Transcribed on the glasses (DAT Speech, beta)"
    case .off: return "Off, typing only"
    #if DEBUG
    case .mock: return "Recorded audio (simulator)"
    #endif
    }
  }
}

/// Turns any PCM buffer into 16 kHz mono Float32 samples for the cutter.
final class To16k: @unchecked Sendable {
  private let target = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: UtteranceCutter.rate, channels: 1,
                                     interleaved: false)!
  private var converter: AVAudioConverter?
  private var source: AVAudioFormat?

  func convert(_ buffer: AVAudioPCMBuffer) -> [Float] {
    if buffer.format.sampleRate == target.sampleRate, buffer.format.channelCount == 1,
       buffer.format.commonFormat == .pcmFormatFloat32, let data = buffer.floatChannelData {
      return Array(UnsafeBufferPointer(start: data[0], count: Int(buffer.frameLength)))
    }
    if source != buffer.format {
      source = buffer.format
      converter = AVAudioConverter(from: buffer.format, to: target)
    }
    guard let converter else { return [] }
    let capacity = AVAudioFrameCount(Double(buffer.frameLength) * target.sampleRate / buffer.format.sampleRate) + 32
    guard let out = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { return [] }
    var given = false
    var error: NSError?
    converter.convert(to: out, error: &error) { _, status in
      if given {
        status.pointee = .noDataNow
        return nil
      }
      given = true
      status.pointee = .haveData
      return buffer
    }
    guard error == nil, let data = out.floatChannelData else { return [] }
    return Array(UnsafeBufferPointer(start: data[0], count: Int(out.frameLength)))
  }
}

/// The glasses microphones over Bluetooth HFP, as Meta's "Use device microphones and speakers" guide sets it up: the
/// play-and-record session with HFP allowed, the glasses' HFP input preferred, an engine tap. The route must settle
/// before the DAT camera stream starts, so this starts first.
@MainActor
final class HFPMicrophone {
  private let engine = AVAudioEngine()
  private let converter = To16k()
  private(set) var route = "none"

  func start(into cutter: UtteranceCutter) async throws {
    guard await AVAudioApplication.requestRecordPermission() else { throw MicError.denied }
    let session = AVAudioSession.sharedInstance()
    try session.setCategory(.playAndRecord, mode: .default, options: [.allowBluetoothHFP, .defaultToSpeaker])
    try session.setActive(true, options: .notifyOthersOnDeactivation)
    if let glasses = session.availableInputs?.first(where: { $0.portType == .bluetoothHFP }) {
      try session.setPreferredInput(glasses)
    }
    let input = engine.inputNode
    let format = input.outputFormat(forBus: 0)
    let converter = self.converter
    input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
      cutter.feed(converter.convert(buffer), at: Date().timeIntervalSince1970 - Double(buffer.frameLength) / format.sampleRate)
    }
    engine.prepare()
    try engine.start()
    try await Task.sleep(for: .seconds(2))  // Meta: let the HFP route settle before the camera stream starts
    route = session.currentRoute.inputs.first.map { $0.portType == .bluetoothHFP ? "glasses (HFP)" : $0.portName } ?? "none"
  }

  func stop() {
    engine.inputNode.removeTap(onBus: 0)
    engine.stop()
  }
}

/// The camera stream's own audio (DAT beta): the glasses hand the app PCM frames with the video.
final class StreamMicrophone: @unchecked Sendable {
  private let converter = To16k()
  private let cutter: UtteranceCutter

  init(cutter: UtteranceCutter) { self.cutter = cutter }

  func feed(_ buffer: AVAudioPCMBuffer) {
    cutter.feed(converter.convert(buffer), at: Date().timeIntervalSince1970 - Double(buffer.frameLength) / buffer.format.sampleRate)
  }
}

enum MicError: LocalizedError {
  case denied

  var errorDescription: String? { "Microphone permission was not given." }
}

#if DEBUG
/// The simulator's microphone: plays a recorded clip into the cutter in real time, 20 ms at a time, the way the
/// glasses would hand the app its audio. The app never sees the clip's words, only its samples.
final class MockMicrophone: @unchecked Sendable {
  private let converter = To16k()
  private let cutter: UtteranceCutter
  private let queue = DispatchQueue(label: "mock-mic")

  init(cutter: UtteranceCutter) { self.cutter = cutter }

  /// Plays `MockMic/<name>.wav` from the app bundle, then 1 s of silence so the cutter hears the end. Returns the
  /// clip's length, or nil when it is not in the app.
  @discardableResult
  func play(_ name: String, onDone: (@Sendable (Double, Double) -> Void)? = nil) -> Double? {
    guard
      let url = Bundle.main.url(forResource: name, withExtension: "wav"),
      let file = try? AVAudioFile(forReading: url),
      let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(file.length)),
      (try? file.read(into: buffer)) != nil
    else { return nil }
    let samples = converter.convert(buffer) + [Float](repeating: 0, count: Int(UtteranceCutter.rate))
    let seconds = Double(buffer.frameLength) / file.processingFormat.sampleRate
    let cutter = self.cutter
    queue.async {
      let chunk = UtteranceCutter.frame
      let started = Date().timeIntervalSince1970
      var index = 0
      while index < samples.count {
        let due = started + Double(index) / UtteranceCutter.rate
        let wait = due - Date().timeIntervalSince1970
        if wait > 0 { Thread.sleep(forTimeInterval: wait) }
        let end = min(index + chunk, samples.count)
        cutter.feed(Array(samples[index..<end]), at: due)
        index = end
      }
      onDone?(started, seconds)
    }
    return seconds
  }
}
#endif
