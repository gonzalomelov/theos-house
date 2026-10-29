import AVFoundation
import AudioToolbox

/// Plays what the agent says on the phone, which routes to the glasses speakers when they are connected.
@MainActor
final class Voice: NSObject, AVSpeechSynthesizerDelegate {
  private let synthesizer = AVSpeechSynthesizer()
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
    synthesizer.speak(utterance)
  }

  func chime() {
    AudioServicesPlaySystemSound(1057)
  }

  nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
    let text = utterance.speechString
    Task { @MainActor in self.onSpoken?(text) }
  }
}
