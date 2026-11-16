import Foundation
import UIKit

/// Records a meeting through Apex Box: the audio is cut into blocks without gaps, each block is
/// uploaded and transcribed while the meeting goes on, and the phone only ever holds the blocks
/// that are still waiting to be sent.
@MainActor
final class MeetingRecorder: ObservableObject {
    static let shared = MeetingRecorder()
    static let blockSeconds = 180

    enum Stage: Equatable {
        case idle
        case recording
        case finishing
        case done(jobID: String)
    }

    private struct PendingBlock {
        let index: Int
        let clip: RecordedClip
    }

    @Published private(set) var stage: Stage = .idle
    @Published private(set) var elapsed: Double = 0
    @Published private(set) var level: Float = 0
    @Published private(set) var segments: [Segment] = []
    @Published private(set) var notes: [BoxNote] = []
    @Published private(set) var pendingBlocks = 0
    @Published private(set) var transcript: TranscriptionResult?
    @Published var errorMessage: String?

    var isActive: Bool {
        stage == .recording || stage == .finishing
    }

    private let capture = AudioCapture.shared
    private let api = APIClient.shared
    private var sessionID: String?
    private var timer: Timer?
    private var startedAt = Date()
    private var closedSeconds: Double = 0
    private var nextBlockIndex = 0
    private var queue: [PendingBlock] = []
    private var uploading = false

    private init() {}

    // MARK: - Start and stop

    func start(title: String, language: String) async {
        guard stage == .idle || isDone else { return }
        errorMessage = nil
        if DictationService.shared.sessionActive {
            DictationService.shared.endSession()
        }
        guard await AudioCapture.requestPermission() else {
            errorMessage = CaptureError.microphoneDenied.localizedDescription
            return
        }
        do {
            let name = title.trimmingCharacters(in: .whitespaces)
            let session = try await api.createMeeting(title: name.isEmpty ? "Reunión" : name, language: language)
            try capture.start()
            try capture.beginFile()
            sessionID = session.boxSessionId
        } catch {
            capture.stop()
            errorMessage = error.localizedDescription
            return
        }
        capture.onLevel = { [weak self] level in self?.level = level }
        capture.onInterruptedClip = { [weak self] clip in
            Task { @MainActor in self?.enqueue(clip) }
        }
        segments = []
        notes = []
        transcript = nil
        queue = []
        nextBlockIndex = 0
        closedSeconds = 0
        elapsed = 0
        startedAt = Date()
        stage = .recording
        UIApplication.shared.isIdleTimerDisabled = true
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
    }

    func stop() async {
        guard stage == .recording else { return }
        stage = .finishing
        timer?.invalidate()
        timer = nil
        UIApplication.shared.isIdleTimerDisabled = false
        if let clip = capture.endFile() {
            enqueue(clip)
        }
        capture.stop()
        capture.onLevel = nil
        capture.onInterruptedClip = nil
        level = 0

        await complete()
    }

    /// After a failed upload or finalize.
    func retry() async {
        guard stage == .finishing else { return }
        errorMessage = nil
        await complete()
    }

    /// Sends what is left and asks the server for the final transcript, summary and minutes.
    private func complete() async {
        guard let sessionID else { return }
        while uploading {
            try? await Task.sleep(nanoseconds: 200_000_000)
        }
        await drainQueue()
        guard queue.isEmpty else {
            errorMessage = "No pudimos enviar \(queue.count) bloque(s). Revisa tu conexión y toca Reintentar."
            return
        }
        let background = BackgroundTask()
        defer { background.end() }
        do {
            let finished = try await api.finalizeMeeting(sessionID: sessionID)
            transcript = finished.result
            stage = .done(jobID: finished.jobId)
            self.sessionID = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func reset() {
        guard isDone || stage == .idle else { return }
        stage = .idle
        transcript = nil
        segments = []
        notes = []
        elapsed = 0
        errorMessage = nil
    }

    private var isDone: Bool {
        if case .done = stage { return true }
        return false
    }

    // MARK: - Blocks

    private func tick() {
        guard stage == .recording else { return }
        elapsed = closedSeconds + capture.currentFileSeconds
        if capture.currentFileSeconds >= Double(Self.blockSeconds) {
            do {
                if let clip = try capture.rotateFile() {
                    enqueue(clip)
                }
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func enqueue(_ clip: RecordedClip) {
        guard clip.seconds > 0.2 else {
            try? FileManager.default.removeItem(at: clip.url)
            return
        }
        closedSeconds += clip.seconds
        queue.append(PendingBlock(index: nextBlockIndex, clip: clip))
        nextBlockIndex += 1
        pendingBlocks = queue.count
        Task { await drainQueue() }
    }

    /// Sends the waiting blocks in order. A block that fails stays first in the queue.
    private func drainQueue() async {
        guard !uploading, let sessionID else { return }
        uploading = true
        defer { uploading = false }
        while let block = queue.first {
            do {
                let response = try await api.uploadBlock(
                    sessionID: sessionID,
                    index: block.index,
                    file: block.clip.url,
                    seconds: block.clip.seconds
                )
                segments.append(contentsOf: response.newSegments ?? [])
                try? FileManager.default.removeItem(at: block.clip.url)
                queue.removeFirst()
                pendingBlocks = queue.count
            } catch {
                errorMessage = error.localizedDescription
                return
            }
        }
    }

    // MARK: - Notes

    func addNote(_ text: String, tag: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard stage == .recording, let sessionID, !trimmed.isEmpty else { return }
        do {
            notes.append(try await api.addNote(sessionID: sessionID, text: trimmed, tag: tag, at: elapsed))
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
