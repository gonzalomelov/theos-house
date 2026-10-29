import AVFoundation

/// Plays what the agent says on the phone, which routes to the glasses speakers when they are connected.
@MainActor
final class Voice: NSObject, AVSpeechSynthesizerDelegate {
  private let synthesizer = AVSpeechSynthesizer()
  private let tone = AlertTone()
  #if DEBUG
  private let recorder = UserDefaults.standard.bool(forKey: "recordSpeech") ? SpeechRecorder() : nil
  #endif
  var onSpoken: ((String) -> Void)?

  override init() {
    super.init()
    synthesizer.delegate = self
    try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
    try? AVAudioSession.sharedInstance().setActive(true)
  }

  func speak(_ text: String, urgent: Bool = false) {
    if urgent { synthesizer.stopSpeaking(at: .immediate) }
    let utterance = AVSpeechUtterance(string: text)
    utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
    utterance.rate = urgent ? 0.5 : AVSpeechUtteranceDefaultSpeechRate
    #if DEBUG
    recorder?.queued(utterance, urgent: urgent)
    #endif
    synthesizer.speak(utterance)
  }

  func chime() {
    #if DEBUG
    recorder?.saveTone(tone.wav)
    recorder?.log(["kind": "chime", "file": AlertTone.fileName, "seconds": AlertTone.seconds])
    #endif
    tone.play()
  }

  nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didStart utterance: AVSpeechUtterance) {
    #if DEBUG
    let id = ObjectIdentifier(utterance), at = Date().timeIntervalSince1970
    Task { @MainActor in self.recorder?.played(id, "started", at: at) }
    #endif
  }

  nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
    #if DEBUG
    let id = ObjectIdentifier(utterance), at = Date().timeIntervalSince1970
    Task { @MainActor in self.recorder?.played(id, "cancelled", at: at) }
    #endif
  }

  nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
    let text = utterance.speechString
    #if DEBUG
    let id = ObjectIdentifier(utterance), at = Date().timeIntervalSince1970
    Task { @MainActor in self.recorder?.played(id, "finished", at: at) }
    #endif
    Task { @MainActor in self.onSpoken?(text) }
  }
}

/// The alert tone: two short sine notes (988 Hz then 1319 Hz, 0.13 s each, 5 ms fades) generated in code, so the app
/// ships no sound asset and needs no license for one. It replaces system sound 1057 (Tink), which lasts 0.02 s and
/// was barely audible in the hero run (results/hero/README.md).
@MainActor
final class AlertTone {
  static let fileName = "tone.wav", seconds = 0.26
  let wav: Data
  private var player: AVAudioPlayer?

  init() {
    wav = AlertTone.render()
    player = try? AVAudioPlayer(data: wav)
    player?.volume = 1
    player?.prepareToPlay()
  }

  func play() {
    player?.currentTime = 0
    player?.play()
  }

  static func render(rate: Int = 44100) -> Data {
    let note = Int(Double(rate) * seconds / 2), fade = rate / 200
    var samples: [Int16] = []
    for frequency in [988.0, 1319.0] {
      for i in 0..<note {
        let envelope = min(1, Double(min(i, note - 1 - i)) / Double(fade))
        samples.append(Int16(0.7 * envelope * sin(2 * .pi * frequency * Double(i) / Double(rate)) * Double(Int16.max)))
      }
    }
    var data = Data()
    func put<T: FixedWidthInteger>(_ value: T) { withUnsafeBytes(of: value.littleEndian) { data.append(contentsOf: $0) } }
    let bytes = UInt32(samples.count * 2)
    data.append(contentsOf: Array("RIFF".utf8)); put(36 + bytes); data.append(contentsOf: Array("WAVEfmt ".utf8))
    put(UInt32(16)); put(UInt16(1)); put(UInt16(1)); put(UInt32(rate)); put(UInt32(rate * 2)); put(UInt16(2)); put(UInt16(16))
    data.append(contentsOf: Array("data".utf8)); put(bytes)
    samples.forEach { put($0) }
    return data
  }
}

#if DEBUG
/// Debug only, launch argument -recordSpeech YES. The simulator's screen recording has no audio, so every line the
/// app speaks is also rendered with the same voice and rate to Documents/speech/NNN.wav, and Documents/speech/log.jsonl
/// records when each line started and stopped playing and when the alert tone played (saved once as tone.wav) (Unix seconds, the Mac's clock).
/// scripts/glasses_sim_run.py --audio muxes them onto the screen recording.
@MainActor
final class SpeechRecorder {
  private let folder: URL
  private var count = 0
  private var files: [ObjectIdentifier: String] = [:]
  private var writers: [AVSpeechSynthesizer] = []

  init() {
    folder = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("speech")
    try? FileManager.default.removeItem(at: folder)
    try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
  }

  func log(_ fields: [String: Any]) {
    var row = fields
    if row["t"] == nil { row["t"] = Date().timeIntervalSince1970 }
    guard let data = try? JSONSerialization.data(withJSONObject: row), let line = String(data: data, encoding: .utf8) else { return }
    let url = folder.appendingPathComponent("log.jsonl")
    if let handle = try? FileHandle(forWritingTo: url) {
      handle.seekToEndOfFile()
      handle.write(Data((line + "\n").utf8))
      try? handle.close()
    } else {
      try? Data((line + "\n").utf8).write(to: url)
    }
  }

  func saveTone(_ wav: Data) {
    let url = folder.appendingPathComponent(AlertTone.fileName)
    if !FileManager.default.fileExists(atPath: url.path) { try? wav.write(to: url) }
  }

  func queued(_ utterance: AVSpeechUtterance, urgent: Bool) {
    count += 1
    let name = String(format: "%03d.wav", count)
    files[ObjectIdentifier(utterance)] = name
    log(["kind": "queued", "file": name, "text": utterance.speechString, "urgent": urgent])
    let copy = AVSpeechUtterance(string: utterance.speechString)
    copy.voice = utterance.voice
    copy.rate = utterance.rate
    let writer = AVSpeechSynthesizer()
    writers.append(writer)
    let url = folder.appendingPathComponent(name)
    var file: AVAudioFile?
    writer.write(copy) { [weak self] buffer in
      guard let pcm = buffer as? AVAudioPCMBuffer else { return }
      if pcm.frameLength == 0 {
        file = nil
        Task { @MainActor in
          self?.log(["kind": "rendered", "file": name])
          self?.writers.removeAll { $0 === writer }
        }
        return
      }
      if file == nil {
        file = try? AVAudioFile(forWriting: url, settings: pcm.format.settings, commonFormat: pcm.format.commonFormat,
                                interleaved: pcm.format.isInterleaved)
      }
      try? file?.write(from: pcm)
    }
  }

  func played(_ id: ObjectIdentifier, _ kind: String, at: TimeInterval) {
    log(["kind": kind, "file": files[id] ?? "", "t": at])
  }
}
#endif
