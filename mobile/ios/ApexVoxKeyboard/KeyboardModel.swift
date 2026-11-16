import SwiftUI
import UIKit

enum KeyboardStatus: Equatable {
    case noFullAccess
    case signedOut
    case needsPro
    case needsSession
    case ready
    case recording
    case processing
}

@MainActor
final class KeyboardModel: ObservableObject {
    @Published private(set) var status: KeyboardStatus = .needsSession
    @Published private(set) var message: String?
    @Published private(set) var tones: [ToneOption] = ToneOption.builtIn
    @Published private(set) var tone = "clean"
    @Published private(set) var canUndo = false
    @Published var showsGlobe = true

    weak var controller: KeyboardViewController?

    private var observer: BridgeObserver?
    private var poll: Timer?
    private var deleteTimer: Timer?
    private var deleteHeld = false
    /// A stop was sent from this keyboard and its text has not arrived yet.
    private var awaitingResult = false
    private var startRequestedAt: Date?
    private var lastInsertedCount = 0

    // MARK: - Lifecycle

    func appear() {
        tones = SharedStore.loadTones()
        tone = SharedStore.loadSettings().tone
        observer = BridgeObserver(.stateChanged) { [weak self] in
            Task { @MainActor in self?.refresh() }
        }
        poll?.invalidate()
        poll = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
        refresh()
    }

    func disappear() {
        if status == .recording {
            BridgeSignal.cancel.post()
        }
        observer = nil
        poll?.invalidate()
        poll = nil
        deletePressEnded()
        awaitingResult = false
        startRequestedAt = nil
    }

    // MARK: - State from the app

    private func refresh() {
        guard controller?.hasFullAccess == true, SharedStore.isAvailable else {
            status = .noFullAccess
            return
        }
        let state = SharedStore.loadState()
        guard state.signedIn else { return set(.signedOut) }
        guard state.canDictate else { return set(.needsPro) }
        guard state.sessionAlive else {
            awaitingResult = false
            startRequestedAt = nil
            return set(.needsSession)
        }

        if awaitingResult, !state.resultID.isEmpty {
            awaitingResult = false
            if state.resultError.isEmpty {
                insert(state.resultText)
                message = nil
            } else {
                message = state.resultError
            }
            BridgeSignal.consumed.post()
        }

        switch state.phase {
        case .recording:
            startRequestedAt = nil
            set(.recording)
        case .processing:
            set(.processing)
        case .idle:
            if let requested = startRequestedAt {
                // The start signal was sent but the app has not confirmed yet.
                if Date().timeIntervalSince(requested) < 2 {
                    return
                }
                startRequestedAt = nil
                message = "La app no respondió. Ábrela de nuevo."
            }
            set(awaitingResult ? .processing : .ready)
        }
    }

    private func set(_ newStatus: KeyboardStatus) {
        if status != newStatus {
            status = newStatus
        }
    }

    // MARK: - Actions

    func micTapped() {
        feedback()
        switch status {
        case .ready:
            message = nil
            startRequestedAt = Date()
            status = .recording
            BridgeSignal.start.post()
        case .recording:
            awaitingResult = true
            status = .processing
            BridgeSignal.stop.post()
        case .processing:
            break
        case .noFullAccess, .signedOut, .needsPro, .needsSession:
            controller?.openContainingApp()
        }
    }

    func cancelRecording() {
        guard status == .recording else { return }
        startRequestedAt = nil
        BridgeSignal.cancel.post()
        status = .ready
    }

    func selectTone(_ id: String) {
        var settings = SharedStore.loadSettings()
        settings.tone = id
        if SharedStore.saveSettings(settings) {
            tone = id
        }
    }

    private func insert(_ text: String) {
        guard let proxy = controller?.textDocumentProxy, !text.isEmpty else { return }
        var output = text
        if let last = proxy.documentContextBeforeInput?.last, !last.isWhitespace, !last.isNewline {
            output = " " + output
        }
        proxy.insertText(output)
        lastInsertedCount = output.count
        canUndo = true
    }

    /// Removes the last dictation that was inserted.
    func undoLastInsert() {
        guard canUndo, let proxy = controller?.textDocumentProxy else { return }
        for _ in 0..<lastInsertedCount {
            proxy.deleteBackward()
        }
        lastInsertedCount = 0
        canUndo = false
    }

    // MARK: - Plain keys

    func type(_ text: String) {
        controller?.textDocumentProxy.insertText(text)
        canUndo = false
    }

    func deleteBackward() {
        controller?.textDocumentProxy.deleteBackward()
        canUndo = false
    }

    /// Deletes one character now and keeps deleting while the key stays pressed.
    func deletePressBegan() {
        guard !deleteHeld else { return }
        deleteHeld = true
        deleteBackward()
        deleteTimer = Timer.scheduledTimer(withTimeInterval: 0.4, repeats: false) { [weak self] _ in
            Task { @MainActor in self?.repeatDeleting() }
        }
    }

    private func repeatDeleting() {
        guard deleteHeld else { return }
        deleteTimer = Timer.scheduledTimer(withTimeInterval: 0.09, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.deleteBackward() }
        }
    }

    func deletePressEnded() {
        deleteHeld = false
        deleteTimer?.invalidate()
        deleteTimer = nil
    }

    func nextKeyboard() {
        controller?.advanceToNextInputMode()
    }

    private func feedback() {
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
    }
}
