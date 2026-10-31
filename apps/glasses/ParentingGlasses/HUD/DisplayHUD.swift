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
  /// Called on the main actor after the display accepted a card, with the Unix time the send finished.
  @ObservationIgnored var onSent: ((HUDCard, Double) -> Void)?
  /// Called on the main actor when the wearer taps the card's button (a red flag's "Got it").
  @ObservationIgnored var onAction: (() -> Void)?

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
    let tapped: @Sendable () -> Void = { [weak self] in
      Task { @MainActor in self?.onAction?() }
    }
    Task {
      defer {
        sending = false
        flush()
      }
      do {
        try await display.send(Self.view(card, onAction: tapped))
        shown = card
        sent += 1
        onSent?(card, Date().timeIntervalSince1970)
      } catch {
        lastError = (error as? DisplayError)?.description ?? error.localizedDescription
      }
    }
  }

  /// The catalog icons the cards use, by case name. IconName's raw values are not its case names (DAT 1.0.1 defines
  /// its own rawValue), so `IconName(rawValue: "clock")` finds nothing: before Oct 30 every card fell back to iCircle.
  /// Kept in step with ICONS in parenting_agent/hud_cards.py.
  static let icons: [String: IconName] = [
    "bedSide": .bedSide,
    "bell": .bell,
    "calendar": .calendar,
    "carFrontView": .carFrontView,
    "cart": .cart,
    "checkmark": .checkmark,
    "checkmarkCircle": .checkmarkCircle,
    "clock": .clock,
    "cloudCrescentMoon": .cloudCrescentMoon,
    "dropper": .dropper,
    "exclamationTriangle": .exclamationTriangle,
    "eye": .eye,
    "forkKnife": .forkKnife,
    "house": .house,
    "iCircle": .iCircle,
    "lightBulb": .lightBulb,
    "pencil": .pencil,
    "person": .person,
    "phoneHandsetArrowUpRight": .phoneHandsetArrowUpRight,
    "smartGlasses": .smartGlasses,
    "speakerOff": .speakerOff,
    "speakerWithThreeArcs": .speakerWithThreeArcs,
    "speakerWithTwoArcs": .speakerWithTwoArcs,
    "speechBubble": .speechBubble,
    "threePeopleOverlapping": .threePeopleOverlapping,
  ]

  /// The card as Display components: icon and title, the status line, then the supporting lines, and a red flag's one
  /// button. Text styles and the system card background only: the display adds light, so no colors of our own.
  static func view(_ card: HUDCard, onAction: (@Sendable () -> Void)? = nil) -> FlexBox {
    let icon = Self.icons[card.icon] ?? .iCircle
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
      if let action = card.action {
        ButtonGroup {
          Button(label: action, style: .primary, iconName: .checkmark, onClick: onAction)
        }
      }
    }
    .background(.card)
  }
}
