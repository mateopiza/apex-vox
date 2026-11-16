import Foundation

/// How the keyboard and the app talk.
///
/// iOS does not let a keyboard extension use the microphone, so the app records. The keyboard
/// sends commands as Darwin notifications (they carry no data) and the app answers by writing
/// `BridgeState` to a file in the shared App Group container and posting `stateChanged`.
enum BridgeSignal: String {
    // Keyboard → app
    case start = "app.ialabs.apexvox.bridge.start"
    case stop = "app.ialabs.apexvox.bridge.stop"
    case cancel = "app.ialabs.apexvox.bridge.cancel"
    case consumed = "app.ialabs.apexvox.bridge.consumed"
    // App → keyboard
    case stateChanged = "app.ialabs.apexvox.bridge.state"

    func post() {
        CFNotificationCenterPostNotification(
            CFNotificationCenterGetDarwinNotifyCenter(),
            CFNotificationName(rawValue as CFString),
            nil,
            nil,
            true
        )
    }
}

/// Calls `handler` on the main queue each time the signal is posted by either process.
final class BridgeObserver {
    private let signal: BridgeSignal
    private let handler: () -> Void

    init(_ signal: BridgeSignal, handler: @escaping () -> Void) {
        self.signal = signal
        self.handler = handler
        CFNotificationCenterAddObserver(
            CFNotificationCenterGetDarwinNotifyCenter(),
            Unmanaged.passUnretained(self).toOpaque(),
            { _, observer, _, _, _ in
                guard let observer else { return }
                let me = Unmanaged<BridgeObserver>.fromOpaque(observer).takeUnretainedValue()
                DispatchQueue.main.async { me.handler() }
            },
            signal.rawValue as CFString,
            nil,
            .deliverImmediately
        )
    }

    deinit {
        CFNotificationCenterRemoveObserver(
            CFNotificationCenterGetDarwinNotifyCenter(),
            Unmanaged.passUnretained(self).toOpaque(),
            CFNotificationName(signal.rawValue as CFString),
            nil
        )
    }
}

enum BridgePhase: String, Codable {
    case idle
    case recording
    case processing
}

/// Written by the app only.
struct BridgeState: Codable, Equatable {
    /// `Date().timeIntervalSince1970` of the app's last tick while a dictation session is open.
    var heartbeat: Double = 0
    var phase: BridgePhase = .idle
    /// Changes with every finished dictation, so the keyboard inserts each one once.
    var resultID: String = ""
    var resultText: String = ""
    var resultError: String = ""
    var signedIn: Bool = false
    var canDictate: Bool = false

    /// The app is alive in the background with the microphone ready.
    var sessionAlive: Bool {
        Date().timeIntervalSince1970 - heartbeat < 4
    }
}

/// Chosen in the app or from the keyboard.
struct DictationSettings: Codable, Equatable {
    var tone: String = "clean"
    var instructions: String = ""
    var language: String = "auto"
    var vocabulary: String = ""
    var sessionMinutes: Int = 15
}

struct ToneOption: Codable, Identifiable, Equatable {
    var id: String
    var label: String
    var description: String = ""

    /// Used until the app has fetched `/api/dictation/tones`.
    static let builtIn: [ToneOption] = [
        ToneOption(id: "literal", label: "Tal cual"),
        ToneOption(id: "clean", label: "Limpio"),
        ToneOption(id: "formal", label: "Formal"),
        ToneOption(id: "professional", label: "Profesional"),
        ToneOption(id: "friendly", label: "Cercano"),
        ToneOption(id: "concise", label: "Conciso"),
        ToneOption(id: "custom", label: "Personalizado"),
    ]
}

/// JSON files in the App Group container, written atomically.
enum SharedStore {
    static let appGroupID: String =
        (Bundle.main.object(forInfoDictionaryKey: "AppGroupID") as? String) ?? "group.app.ialabs.apexvox"

    private static var directory: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroupID)
    }

    /// False in the keyboard until the user allows Full Access.
    static var isAvailable: Bool {
        directory != nil
    }

    private static func load<T: Codable>(_ name: String, default fallback: T) -> T {
        guard let url = directory?.appendingPathComponent(name),
              let data = try? Data(contentsOf: url),
              let value = try? JSONDecoder().decode(T.self, from: data)
        else { return fallback }
        return value
    }

    @discardableResult
    private static func save<T: Codable>(_ value: T, as name: String) -> Bool {
        guard let url = directory?.appendingPathComponent(name),
              let data = try? JSONEncoder().encode(value)
        else { return false }
        return (try? data.write(to: url, options: .atomic)) != nil
    }

    static func loadState() -> BridgeState {
        load("bridge-state.json", default: BridgeState())
    }

    static func saveState(_ state: BridgeState) {
        save(state, as: "bridge-state.json")
    }

    static func loadSettings() -> DictationSettings {
        load("dictation-settings.json", default: DictationSettings())
    }

    @discardableResult
    static func saveSettings(_ settings: DictationSettings) -> Bool {
        save(settings, as: "dictation-settings.json")
    }

    static func loadTones() -> [ToneOption] {
        let tones: [ToneOption] = load("tones.json", default: [])
        return tones.isEmpty ? ToneOption.builtIn : tones
    }

    static func saveTones(_ tones: [ToneOption]) {
        save(tones, as: "tones.json")
    }
}
