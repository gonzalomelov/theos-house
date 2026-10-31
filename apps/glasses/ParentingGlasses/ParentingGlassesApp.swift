import MWDATCore
import SwiftUI

@main
struct ParentingGlassesApp: App {
  @State private var companion: Companion

  init() {
    do {
      try Wearables.configure()
    } catch {
      NSLog("[ParentingGlasses] Wearables.configure failed: \(error)")
    }
    _companion = State(wrappedValue: Companion())
  }

  var body: some Scene {
    WindowGroup {
      ContentView(companion: companion)
        .onOpenURL { url in
          guard
            let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
            components.queryItems?.contains(where: { $0.name == "metaWearablesAction" }) == true
          else { return }
          companion.glasses.handle(url: url)
        }
        .task {
          #if DEBUG
          if UserDefaults.standard.bool(forKey: "hudReplay") {
            await companion.runHUDReplay()
          } else if UserDefaults.standard.bool(forKey: "hudLive") {
            await companion.runHUDLive()
          } else if UserDefaults.standard.bool(forKey: "hudDay") || UserDefaults.standard.bool(forKey: "hudSpeech") {
            await companion.runHUDDay()
          } else if UserDefaults.standard.bool(forKey: "autoDemo") {
            await companion.runDemo()
          }
          #endif
        }
    }
  }
}
