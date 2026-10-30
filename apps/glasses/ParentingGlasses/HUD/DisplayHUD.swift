import Foundation
import MWDATCore
import MWDATDisplay

/// Draws the HUD on the Meta Ray-Ban Display through DAT's Display capability (`MWDATDisplay`).
/// On real glasses this is the in-lens display. In the simulator the session runs on MockDeviceKit's
/// `.metaRayBanDisplay` and Meta's `MockDisplayKit` renders the same content in a preview view on the phone.
/// Kept apart from SwiftUI because both modules define `Text`, `Image` and `Button`.
@Observable
@MainActor
final class DisplayHUD {
  private(set) var state: DisplayState = .stopped
  private(set) var sent = 0
  var lastError: String?

  @ObservationIgnored private var display: Display?
  @ObservationIgnored private var stateToken: AnyListenerToken?
  @ObservationIgnored private var shown: HUDCard?
  @ObservationIgnored private var pending: HUDCard?
  @ObservationIgnored private var sending = false

  /// Attaches the display to a started device session. Glasses without a display throw, and the HUD stays off.
  func attach(to session: DeviceSession) {
    guard display == nil else { return }
    do {
      let display = try session.addDisplay()
      self.display = display
      stateToken = display.statePublisher.listen { [weak self] state in
        Task { @MainActor in self?.changed(state) }
      }
      display.start()
    } catch {
      lastError = "display: \(error.localizedDescription)"
    }
  }

  func detach() {
    display?.stop()
    display = nil
    stateToken = nil
    shown = nil
    state = .stopped
  }

  /// Shows the card. Each send replaces the whole display, so only a changed card is sent, and only the newest one
  /// waits while a send is in flight.
  func show(_ card: HUDCard) {
    guard card != shown || pending != nil else { return }
    pending = card
    flush()
  }

  private func changed(_ state: DisplayState) {
    self.state = state
    if state == .started, let card = pending ?? shown {
      shown = nil
      pending = card
      flush()
    }
  }

  private func flush() {
    guard !sending, state == .started, let display, let card = pending else { return }
    pending = nil
    guard card != shown else { return }
    sending = true
    Task {
      defer {
        sending = false
        flush()
      }
      do {
        try await display.send(Self.view(card))
        shown = card
        sent += 1
      } catch {
        lastError = (error as? DisplayError)?.description ?? error.localizedDescription
      }
    }
  }

  /// The card as Display components: icon and title, the status line, then the supporting lines.
  static func view(_ card: HUDCard) -> FlexBox {
    let icon = IconName(rawValue: card.icon) ?? .iCircle
    return FlexBox(direction: .column, spacing: 12, padding: EdgeInsets(all: 28)) {
      FlexBox(direction: .row, spacing: 12, crossAlignment: .center) {
        Icon(name: icon, style: card.alert ? .filled : .outline)
        Text(card.title, style: .heading)
      }
      Text(card.status, style: .heading)
      if let detail = card.detail {
        Text(detail, style: .body, color: .secondary)
      }
      if let meta = card.meta {
        Text(meta, style: .meta, color: .secondary)
      }
    }
    .background(.card)
  }
}
