import Foundation

// Tests for the utterance cutter in ParentingGlasses/Speech/Utterances.swift, compiled with it by scripts/test-hud.sh.
// Foundation only: they run on the Mac without the simulator or the DAT SDK.

var failures = 0
var checks = 0

func expect(_ condition: Bool, _ message: String, line: Int = #line) {
  checks += 1
  if !condition {
    failures += 1
    print("FAIL line \(line): \(message)")
  }
}

let rate = UtteranceCutter.rate

/// Silence, then a 300 Hz tone for each (start, length) in seconds, at -16 dBFS, fed 20 ms at a time from t0.
func run(_ parts: [(Double, Double)], total: Double, muted: Bool = false, noise: Float = 0) -> [Utterance] {
  let cutter = UtteranceCutter()
  cutter.setMuted(muted)
  var out: [Utterance] = []
  cutter.onUtterance = { out.append($0) }
  let t0 = 1_000_000.0
  var samples = (0..<Int(total * rate)).map { _ in Float.random(in: -noise...noise) }
  for (start, length) in parts {
    for i in Int(start * rate)..<Int((start + length) * rate) where i < samples.count {
      samples[i] += 0.16 * sin(2 * .pi * 300 * Float(i) / Float(rate))
    }
  }
  var i = 0
  while i < samples.count {
    let end = min(i + 320, samples.count)
    cutter.feed(Array(samples[i..<end]), at: t0 + Double(i) / rate)
    i = end
  }
  return out
}

let one = run([(1.0, 1.2)], total: 4)
expect(one.count == 1, "one word, one utterance (got \(one.count))")
if let u = one.first {
  expect(abs(u.endUnix - 1_000_002.2) < 0.03, "the end of speech is the last voiced moment (\(u.endUnix - 1_000_000))")
  expect(abs(u.startUnix - 1_000_001.0) < 0.03, "the start of speech (\(u.startUnix - 1_000_000))")
  expect(u.seconds > 1.2 && u.seconds < 1.65, "the clip keeps a little before and after (\(u.seconds) s)")
  let wav = u.wav
  expect(String(decoding: wav.prefix(4), as: UTF8.self) == "RIFF" && wav.count == 44 + u.samples.count * 2, "a 16-bit WAV")
}
expect(run([(1.0, 0.1)], total: 3).isEmpty, "a click is not speech")
expect(run([(1.0, 1.0)], total: 3, muted: true).isEmpty, "nothing is heard while the app speaks")
expect(run([(1.0, 0.5), (1.8, 0.5)], total: 4).count == 1, "a short pause stays inside one utterance")
expect(run([(1.0, 0.5), (2.5, 0.5)], total: 4.5).count == 2, "a long pause makes two")
expect(run([(1.0, 0.8)], total: 3, noise: 0.003).count == 1, "speech over a quiet room")
expect(run([], total: 3, noise: 0.003).isEmpty, "a quiet room is not speech")
expect(run([(0.5, 20)], total: 22).count == 2, "a long monologue is cut at 15 s")

print("\(checks - failures) of \(checks) cutter checks passed")
exit(failures == 0 ? 0 : 1)
