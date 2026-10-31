import Foundation

/// One event from the agent's glasses endpoint (server-sent events on /events).
struct AgentEvent: Decodable, Sendable {
  let kind: String
  let text: String?
  let state: String?
  let hands: Int?
}

/// Talks to the parenting agent on the parent's own computer: frames up, spoken replies down.
/// Plain HTTP on localhost or the home network only, with the pairing token on every request.
@Observable
@MainActor
final class AgentLink {
  var connected = false
  var framesSent = 0
  var framesDropped = 0
  var lastUploadMs: Int?
  var lastError: String?

  /// Each event with its raw JSON, which the HUD decodes again for the fields it shows.
  @ObservationIgnored var onEvent: ((AgentEvent, Data) -> Void)?
  @ObservationIgnored private var listenTask: Task<Void, Never>?
  @ObservationIgnored private var uploading = false

  var baseURL: URL {
    URL(string: UserDefaults.standard.string(forKey: "agentURL") ?? "") ?? URL(string: "http://127.0.0.1:8766")!
  }

  private var token: String { UserDefaults.standard.string(forKey: "agentToken") ?? "" }

  private func request(_ path: String, method: String = "GET") -> URLRequest {
    var request = URLRequest(url: baseURL.appendingPathComponent(path))
    request.httpMethod = method
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    request.timeoutInterval = 10
    return request
  }

  /// Sends one JPEG frame. A frame that arrives while the previous one is still uploading is dropped,
  /// so the agent always gets the newest view and the phone never queues stale frames.
  func send(frame jpeg: Data) {
    guard !uploading else {
      framesDropped += 1
      return
    }
    uploading = true
    var request = request("frame", method: "POST")
    request.setValue("image/jpeg", forHTTPHeaderField: "Content-Type")
    let started = Date()
    Task {
      defer { uploading = false }
      do {
        let (_, response) = try await URLSession.shared.upload(for: request, from: jpeg)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        if code == 204 {
          framesSent += 1
          lastUploadMs = Int(Date().timeIntervalSince(started) * 1000)
          lastError = nil
        } else {
          lastError = "agent answered \(code) to a frame"
        }
      } catch {
        lastError = "frame not sent: \(error.localizedDescription)"
      }
    }
  }

  /// Sends what the parent said (typed for now) to the agent, as a message on the glasses channel.
  func say(_ text: String) {
    var request = request("say", method: "POST")
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.httpBody = try? JSONSerialization.data(withJSONObject: ["text": text])
    Task {
      do {
        let (_, response) = try await URLSession.shared.data(for: request)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        if code != 204 { lastError = "agent answered \(code) to a message" }
      } catch {
        lastError = "message not sent: \(error.localizedDescription)"
      }
    }
  }

  /// Sends one utterance from the microphone (a WAV) or from glasses that transcribe (text) to the agent's ear. The agent
  /// writes it down, decides whether it was meant for it, and answers on the event stream.
  func hear(wav: Data? = nil, text: String? = nil, endUnix: Double, seconds: Double, source: String) {
    var request = request("hear", method: "POST")
    request.setValue(wav == nil ? "application/json" : "audio/wav", forHTTPHeaderField: "Content-Type")
    request.setValue(String(format: "%.3f", endUnix), forHTTPHeaderField: "X-Speech-End-Unix")
    request.setValue(String(format: "%.3f", seconds), forHTTPHeaderField: "X-Speech-Seconds")
    request.setValue(source, forHTTPHeaderField: "X-Speech-Source")
    let body = wav ?? (try? JSONSerialization.data(withJSONObject: ["text": text ?? ""])) ?? Data()
    Task {
      do {
        let (_, response) = try await URLSession.shared.upload(for: request, from: body)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        if code != 202 { lastError = "agent answered \(code) to speech" }
      } catch {
        lastError = "speech not sent: \(error.localizedDescription)"
      }
    }
  }

  /// Listens to the agent's events and reconnects after a drop.
  func listen() {
    listenTask?.cancel()
    listenTask = Task {
      while !Task.isCancelled {
        do {
          var request = request("events")
          request.timeoutInterval = 60
          let (bytes, response) = try await URLSession.shared.bytes(for: request)
          guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            lastError = "agent refused the event stream (check the token)"
            connected = false
            try await Task.sleep(for: .seconds(3))
            continue
          }
          connected = true
          lastError = nil
          for try await line in bytes.lines {
            guard line.hasPrefix("data: "), let data = line.dropFirst(6).data(using: .utf8) else { continue }
            if let event = try? JSONDecoder().decode(AgentEvent.self, from: data) {
              onEvent?(event, data)
            }
          }
        } catch {
          if !Task.isCancelled { lastError = "agent not reachable at \(baseURL.absoluteString)" }
        }
        connected = false
        try? await Task.sleep(for: .seconds(1))
      }
    }
  }
}
