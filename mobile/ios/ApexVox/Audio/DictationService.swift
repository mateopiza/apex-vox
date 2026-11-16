import Foundation
import UIKit

/// Dictation, for the keyboard and for the app's own screen.
///
/// A keyboard extension cannot record, so the user opens a "dictation session" here: the app keeps
/// the microphone engine running in the background and obeys the keyboard's start/stop signals.
/// While the session is open iOS shows the microphone indicator; audio is only kept between a
/// start and a stop, and it is deleted as soon as it has been sent.
@MainActor
final class DictationService: ObservableObject {
    static let shared = DictationService()

    /// Longest single dictation. Keeps the clip well under the server's size limit.
    static let maxClipSeconds: Double = 600

    @Published private(set) var sessionActive = false
    @Published private(set) var sessionEndsAt: Date?
    @Published private(set) var phase: BridgePhase = .idle
    @Published private(set) var level: Float = 0
    @Published private(set) var errorMessage: String?
    /// Text dictated on the app's own screen (dictations from the keyboard go to the keyboard).
    @Published var notes: String = ""
    @Published var settings: DictationSettings = SharedStore.loadSettings() {
        didSet {
            if settings != oldValue {
                SharedStore.saveSettings(settings)
            }
        }
    }
    @Published private(set) var tones: [ToneOption] = SharedStore.loadTones()

    private enum Requester {
        case keyboard
        case app
    }

    private let capture = AudioCapture.shared
    private let api = APIClient.shared
    private var requester: Requester = .app
    private var heartbeat: Timer?
    private var observers: [BridgeObserver] = []
    private var result = (id: "", text: "", error: "")

    private init() {
        observers = [
            BridgeObserver(.start) { [weak self] in Task { @MainActor in self?.begin(for: .keyboard) } },
            BridgeObserver(.stop) { [weak self] in Task { @MainActor in self?.finish() } },
            BridgeObserver(.cancel) { [weak self] in Task { @MainActor in self?.cancel() } },
            BridgeObserver(.consumed) { [weak self] in Task { @MainActor in self?.clearResult() } },
        ]
    }

    // MARK: - Session (keeps the app ready for the keyboard)

    func startSession() async {
        errorMessage = nil
        guard !MeetingRecorder.shared.isActive else {
            errorMessage = "Termina la reunión que estás grabando antes de dictar."
            return
        }
        guard await AudioCapture.requestPermission() else {
            errorMessage = CaptureError.microphoneDenied.localizedDescription
            return
        }
        do {
            try capture.start()
        } catch {
            errorMessage = error.localizedDescription
            return
        }
        capture.onLevel = { [weak self] level in self?.level = level }
        capture.onInterruptedClip = { clip in
            _ = try? FileManager.default.removeItem(at: clip.url)
        }
        settings = SharedStore.loadSettings()
        sessionActive = true
        extendSession()
        heartbeat?.invalidate()
        heartbeat = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
        publish()
    }

    func endSession() {
        heartbeat?.invalidate()
        heartbeat = nil
        if let clip = capture.endFile() {
            try? FileManager.default.removeItem(at: clip.url)
        }
        capture.stop()
        capture.onLevel = nil
        sessionActive = false
        sessionEndsAt = nil
        if phase == .recording {
            phase = .idle
        }
        level = 0
        publish()
    }

    private func extendSession() {
        sessionEndsAt = Date().addingTimeInterval(Double(max(1, settings.sessionMinutes)) * 60)
    }

    private func tick() {
        guard sessionActive else { return }
        if phase == .recording, capture.currentFileSeconds >= Self.maxClipSeconds {
            finish()
        }
        if phase == .idle, let end = sessionEndsAt, Date() >= end {
            endSession()
            return
        }
        publish()
    }

    // MARK: - One dictation

    /// The app's own microphone button.
    func toggleFromApp() async {
        switch phase {
        case .idle:
            if !sessionActive {
                await startSession()
            }
            if sessionActive {
                begin(for: .app)
            }
        case .recording:
            finish()
        case .processing:
            break
        }
    }

    private func begin(for requester: Requester) {
        guard sessionActive, phase == .idle else { return }
        // The keyboard may have changed the tone since the last dictation.
        settings = SharedStore.loadSettings()
        do {
            try capture.beginFile()
        } catch {
            fail(error.localizedDescription, for: requester)
            return
        }
        self.requester = requester
        errorMessage = nil
        clearResult()
        phase = .recording
        extendSession()
        publish()
    }

    private func cancel() {
        guard phase == .recording else { return }
        if let clip = capture.endFile() {
            try? FileManager.default.removeItem(at: clip.url)
        }
        phase = .idle
        publish()
    }

    private func finish() {
        guard phase == .recording else { return }
        let requester = self.requester
        guard let clip = capture.endFile() else {
            phase = .idle
            publish()
            return
        }
        guard clip.seconds >= 0.4 else {
            try? FileManager.default.removeItem(at: clip.url)
            phase = .idle
            fail("No alcancé a escucharte. Mantén la grabación un poco más.", for: requester)
            return
        }
        phase = .processing
        publish()

        // Finish the upload even if iOS suspends the app right after the session ends.
        let background = BackgroundTask()
        let settings = self.settings
        Task {
            defer {
                try? FileManager.default.removeItem(at: clip.url)
                background.end()
            }
            do {
                let dictation = try await api.dictate(file: clip.url, settings: settings)
                phase = .idle
                if dictation.text.isEmpty {
                    fail("No se escuchó nada. Intenta de nuevo.", for: requester)
                } else {
                    deliver(dictation.text, to: requester)
                }
            } catch {
                phase = .idle
                fail(error.localizedDescription, for: requester)
            }
        }
    }

    private func deliver(_ text: String, to requester: Requester) {
        switch requester {
        case .keyboard:
            result = (UUID().uuidString, text, "")
        case .app:
            notes = notes.isEmpty ? text : notes + (notes.hasSuffix("\n") ? "" : " ") + text
        }
        extendSession()
        publish()
    }

    private func fail(_ message: String, for requester: Requester) {
        switch requester {
        case .keyboard:
            result = (UUID().uuidString, "", message)
        case .app:
            errorMessage = message
        }
        publish()
    }

    /// The keyboard inserted the text: stop keeping a copy of it in the shared container.
    private func clearResult() {
        guard !result.id.isEmpty else { return }
        result = ("", "", "")
        publish()
    }

    // MARK: - Rewrite and tones

    /// Rewrites the notes on screen in the current tone.
    func rewriteNotes() async {
        let text = notes.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, phase == .idle else { return }
        errorMessage = nil
        phase = .processing
        defer { phase = .idle }
        do {
            notes = try await api.rewrite(text: text, settings: settings).text
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func loadTones() async {
        guard let catalog = try? await api.tones(), !catalog.tones.isEmpty else { return }
        tones = catalog.tones
        SharedStore.saveTones(catalog.tones)
    }

    // MARK: - Shared state for the keyboard

    private func publish() {
        var state = SharedStore.loadState()
        state.heartbeat = sessionActive ? Date().timeIntervalSince1970 : 0
        state.phase = requester == .keyboard || phase == .idle ? phase : .idle
        state.resultID = result.id
        state.resultText = result.text
        state.resultError = result.error
        let changed = state.phase != lastPublished.phase || state.resultID != lastPublished.resultID
            || (state.heartbeat == 0) != (lastPublished.heartbeat == 0)
        SharedStore.saveState(state)
        lastPublished = state
        if changed {
            BridgeSignal.stateChanged.post()
        }
    }

    private var lastPublished = BridgeState()
}

/// Asks iOS for time to finish work after the app leaves the foreground.
@MainActor
final class BackgroundTask {
    private var identifier = UIBackgroundTaskIdentifier.invalid

    init() {
        identifier = UIApplication.shared.beginBackgroundTask { [weak self] in
            Task { @MainActor in self?.end() }
        }
    }

    func end() {
        guard identifier != .invalid else { return }
        UIApplication.shared.endBackgroundTask(identifier)
        identifier = .invalid
    }
}
