import AVFoundation

struct RecordedClip {
    let url: URL
    let seconds: Double
}

enum CaptureError: LocalizedError {
    case microphoneDenied
    case noInput

    var errorDescription: String? {
        switch self {
        case .microphoneDenied:
            return "Apex Vox no tiene permiso para usar el micrófono. Actívalo en Ajustes."
        case .noInput:
            return "No encontramos un micrófono disponible."
        }
    }
}

/// One microphone engine for the whole app. It keeps running between dictations (that is what
/// keeps the app alive in the background) and only writes audio while a file is open.
final class AudioCapture {
    static let shared = AudioCapture()

    /// 0...1, called on the main queue a few times per second while running.
    var onLevel: ((Float) -> Void)?
    /// The input changed (AirPods, a call ended...) while a file was open: the part recorded so
    /// far is handed over and recording continues in a new file.
    var onInterruptedClip: ((RecordedClip) -> Void)?

    private let engine = AVAudioEngine()
    private let lock = NSLock()
    private var file: AVAudioFile?
    private var fileURL: URL?
    private var framesWritten: AVAudioFramePosition = 0
    private var fileSampleRate: Double = 44_100
    private var lastLevelAt = Date.distantPast
    private var observers: [NSObjectProtocol] = []
    private(set) var isRunning = false

    private init() {}

    static func requestPermission() async -> Bool {
        await withCheckedContinuation { continuation in
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                continuation.resume(returning: granted)
            }
        }
    }

    // MARK: - Engine

    func start() throws {
        guard !isRunning else { return }
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .default, options: [.mixWithOthers, .allowBluetooth, .defaultToSpeaker])
        try session.setActive(true)
        try installTapAndRun()
        isRunning = true
        observe()
    }

    func stop() {
        guard isRunning else { return }
        isRunning = false
        observers.forEach { NotificationCenter.default.removeObserver($0) }
        observers = []
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        _ = endFile()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func installTapAndRun() throws {
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else { throw CaptureError.noInput }
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 4096, format: format) { [weak self] buffer, _ in
            self?.handle(buffer)
        }
        engine.prepare()
        try engine.start()
    }

    private func observe() {
        let center = NotificationCenter.default
        observers.append(center.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main) { [weak self] _ in
            self?.recover()
        })
        observers.append(center.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: .main) { [weak self] note in
            let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            if raw == AVAudioSession.InterruptionType.ended.rawValue {
                self?.recover()
            }
        })
    }

    /// Restart after a route change or an interruption. An open file cannot change format, so it
    /// is closed and a new one continues.
    private func recover() {
        guard isRunning else { return }
        let wasRecording = isRecordingToFile
        let finished = endFile()
        engine.stop()
        do {
            try AVAudioSession.sharedInstance().setActive(true)
            try installTapAndRun()
            if wasRecording {
                _ = try beginFile()
            }
        } catch {
            // The next start() or beginFile() will report the problem to the user.
        }
        if let finished {
            onInterruptedClip?(finished)
        }
    }

    // MARK: - Files

    var isRecordingToFile: Bool {
        lock.lock()
        defer { lock.unlock() }
        return file != nil
    }

    /// Seconds written to the open file.
    var currentFileSeconds: Double {
        lock.lock()
        defer { lock.unlock() }
        return Double(framesWritten) / fileSampleRate
    }

    @discardableResult
    func beginFile() throws -> URL {
        let (newFile, url, sampleRate) = try makeFile()
        lock.lock()
        file = newFile
        fileURL = url
        framesWritten = 0
        fileSampleRate = sampleRate
        lock.unlock()
        return url
    }

    /// Closes the open file. Nil if none was open.
    func endFile() -> RecordedClip? {
        lock.lock()
        defer { lock.unlock() }
        return takeFile()
    }

    /// Closes the open file and opens the next one without losing a sample between them.
    func rotateFile() throws -> RecordedClip? {
        let (newFile, url, sampleRate) = try makeFile()
        lock.lock()
        defer { lock.unlock() }
        let finished = takeFile()
        file = newFile
        fileURL = url
        framesWritten = 0
        fileSampleRate = sampleRate
        return finished
    }

    private func makeFile() throws -> (AVAudioFile, URL, Double) {
        let format = engine.inputNode.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else { throw CaptureError.noInput }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("clip-\(UUID().uuidString).m4a")
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: format.sampleRate,
            AVNumberOfChannelsKey: format.channelCount,
            AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue,
        ]
        let newFile = try AVAudioFile(
            forWriting: url,
            settings: settings,
            commonFormat: format.commonFormat,
            interleaved: format.isInterleaved
        )
        return (newFile, url, format.sampleRate)
    }

    /// Call with the lock held.
    private func takeFile() -> RecordedClip? {
        guard let url = fileURL, file != nil else { return nil }
        let seconds = Double(framesWritten) / fileSampleRate
        file = nil  // releasing the file finishes writing it
        fileURL = nil
        framesWritten = 0
        return RecordedClip(url: url, seconds: seconds)
    }

    // MARK: - Audio thread

    private func handle(_ buffer: AVAudioPCMBuffer) {
        lock.lock()
        if let file {
            do {
                try file.write(from: buffer)
                framesWritten += AVAudioFramePosition(buffer.frameLength)
            } catch {
                // A buffer in the wrong format after a route change: recover() replaces the file.
            }
        }
        lock.unlock()

        guard let onLevel, Date().timeIntervalSince(lastLevelAt) > 0.08 else { return }
        lastLevelAt = Date()
        let level = Self.level(of: buffer)
        DispatchQueue.main.async { onLevel(level) }
    }

    private static func level(of buffer: AVAudioPCMBuffer) -> Float {
        guard let samples = buffer.floatChannelData?[0], buffer.frameLength > 0 else { return 0 }
        var sum: Float = 0
        let count = Int(buffer.frameLength)
        for index in 0..<count {
            sum += samples[index] * samples[index]
        }
        let rms = (sum / Float(count)).squareRoot()
        return min(1, rms * 12)
    }
}
