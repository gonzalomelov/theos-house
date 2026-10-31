import Foundation

/// One stretch of speech cut from the microphone: 16 kHz mono samples, with the wall clock of its first and last voiced
/// moments, so the agent can time end of speech to card.
struct Utterance: Sendable {
  let samples: [Float]
  let startUnix: Double
  let endUnix: Double
  var seconds: Double { Double(samples.count) / UtteranceCutter.rate }

  /// 16-bit PCM WAV, the format Muse's ear takes (parenting_agent/voice/ear.py).
  var wav: Data { UtteranceCutter.wav(samples) }
}

/// Cuts a 16 kHz mono microphone stream into utterances with an energy gate, on the phone, so only speech leaves it.
/// 20 ms frames. Speech starts after 3 loud frames in a row (60 ms), keeps 0.2 s before that, and ends after 0.6 s
/// below the gate. Shorter than 0.25 s of voice is a click, not a word. The gate follows the room: 12 dB over the
/// quietest recent level, never under -50 dBFS.
/// While `muted` (the app is speaking through the same glasses) nothing is cut, so the agent never hears itself.
final class UtteranceCutter: @unchecked Sendable {
  static let rate = 16_000.0
  static let frame = 320
  private let startFrames = 3, endFrames = 30, prerollFrames = 10, maxFrames = 750
  private let minVoicedFrames = 12

  private let lock = NSLock()
  private var pending: [Float] = []
  private var preroll: [[Float]] = []
  private var current: [Float] = []
  private var loud = 0, quiet = 0, voiced = 0
  private var inSpeech = false
  private var startUnix = 0.0, lastVoicedUnix = 0.0
  private var floor: Float = -60
  private var muted = false

  /// Called on the feeding thread with each finished utterance.
  var onUtterance: ((Utterance) -> Void)?
  private(set) var dropped = 0

  func setMuted(_ on: Bool) {
    lock.lock(); defer { lock.unlock() }
    muted = on
    if on { reset() }
  }

  /// Feeds samples whose first sample was heard at `unix` (wall clock).
  func feed(_ samples: [Float], at unix: Double) {
    lock.lock()
    var done: [Utterance] = []
    pending += samples
    var offset = 0
    let start = unix - Double(pending.count - samples.count) / Self.rate
    while pending.count - offset >= Self.frame {
      let chunk = Array(pending[offset..<offset + Self.frame])
      let at = start + Double(offset) / Self.rate
      offset += Self.frame
      if muted { continue }
      if let utterance = step(chunk, at: at) { done.append(utterance) }
    }
    pending.removeFirst(offset)
    lock.unlock()
    done.forEach { onUtterance?($0) }
  }

  /// Ends an utterance in progress (the source stopped), as if the speaker went quiet.
  func flush() -> Utterance? {
    lock.lock(); defer { lock.unlock() }
    return inSpeech ? finish() : nil
  }

  private func step(_ chunk: [Float], at: Double) -> Utterance? {
    let level = Self.dbfs(chunk)
    floor = level < floor ? level : min(floor + 0.05, level)  // falls at once, rises slowly
    let gate = max(floor + 12, -50)
    let isLoud = level > gate
    if !inSpeech {
      preroll.append(chunk)
      if preroll.count > prerollFrames { preroll.removeFirst() }
      loud = isLoud ? loud + 1 : 0
      if loud >= startFrames {
        inSpeech = true
        current = preroll.flatMap { $0 }
        startUnix = at - Double(startFrames - 1) * Double(Self.frame) / Self.rate
        voiced = loud
        quiet = 0
        lastVoicedUnix = at + Double(Self.frame) / Self.rate
        preroll = []
      }
      return nil
    }
    current += chunk
    if isLoud {
      voiced += 1
      quiet = 0
      lastVoicedUnix = at + Double(Self.frame) / Self.rate
    } else {
      quiet += 1
    }
    if quiet >= endFrames || current.count >= maxFrames * Self.frame { return finish() }
    return nil
  }

  private func finish() -> Utterance? {
    defer { reset() }
    guard voiced >= minVoicedFrames else {
      dropped += 1
      return nil
    }
    let trailing = max(0, quiet - 8) * Self.frame  // keep 0.16 s after the last voiced frame
    let samples = Array(current.dropLast(trailing))
    return Utterance(samples: samples, startUnix: startUnix, endUnix: lastVoicedUnix)
  }

  private func reset() {
    inSpeech = false
    current = []
    preroll = []
    loud = 0
    quiet = 0
    voiced = 0
  }

  static func dbfs(_ chunk: [Float]) -> Float {
    var sum: Float = 0
    for x in chunk { sum += x * x }
    let rms = (sum / Float(max(chunk.count, 1))).squareRoot()
    return 20 * log10(max(rms, 1e-7))
  }

  static func wav(_ samples: [Float]) -> Data {
    var data = Data()
    func put<T: FixedWidthInteger>(_ value: T) { withUnsafeBytes(of: value.littleEndian) { data.append(contentsOf: $0) } }
    let bytes = UInt32(samples.count * 2)
    data.append(contentsOf: Array("RIFF".utf8)); put(UInt32(36) + bytes)
    data.append(contentsOf: Array("WAVEfmt ".utf8)); put(UInt32(16)); put(UInt16(1)); put(UInt16(1))
    put(UInt32(rate)); put(UInt32(rate * 2)); put(UInt16(2)); put(UInt16(16))
    data.append(contentsOf: Array("data".utf8)); put(bytes)
    for x in samples { put(Int16(max(-1, min(1, x)) * 32767)) }
    return data
  }
}
