import AVFoundation
import AudioToolbox

/// Plays what the agent says on the phone, which routes to the glasses speakers when they are connected.
@MainActor
final class Voice: NSObject, AVSpeechSynthesizerDelegate {
  private let synthesizer = AVSpeechSynthesizer()
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
    recorder?.log(["kind": "chime", "sound_id": 1057])
    #endif
    AudioServicesPlaySystemSound(1057)
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

#if DEBUG
/// Debug only, launch argument -recordSpeech YES. The simulator's screen recording has no audio, so every line the
/// app speaks is also rendered with the same voice and rate to Documents/speech/NNN.wav, and Documents/speech/log.jsonl
/// records when each line started and stopped playing and when the chime played (Unix seconds, the Mac's clock).
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
