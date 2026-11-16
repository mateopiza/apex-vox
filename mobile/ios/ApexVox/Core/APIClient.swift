import Foundation

struct APIError: LocalizedError {
    let status: Int
    let message: String

    var errorDescription: String? { message }
    var needsSignIn: Bool { status == 401 }
    var needsPro: Bool { status == 402 }
}

/// HTTP client for the Apex Vox backend (see docs/api.md).
final class APIClient {
    static let shared = APIClient()

    /// Session token (`apx_...`). Set by `AuthStore`.
    var token: String?

    let baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder

    private init() {
        let host = (Bundle.main.object(forInfoDictionaryKey: "APIHost") as? String) ?? "apex-vox.ialabs.app"
        baseURL = URL(string: "https://\(host)") ?? URL(string: "https://apex-vox.ialabs.app")!
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 60
        configuration.timeoutIntervalForResource = 600
        session = URLSession(configuration: configuration)
        decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
    }

    // MARK: - Requests

    func get<T: Decodable>(_ path: String, query: [String: String] = [:]) async throws -> T {
        try await send(makeRequest("GET", path, query: query))
    }

    func send<T: Decodable>(
        _ method: String,
        _ path: String,
        json: [String: Any] = [:],
        query: [String: String] = [:],
        timeout: TimeInterval? = nil
    ) async throws -> T {
        var request = makeRequest(method, path, query: query)
        if let timeout {
            request.timeoutInterval = timeout
        }
        if method != "GET" && method != "DELETE" {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: json)
        }
        return try await send(request)
    }

    /// Multipart upload of one file plus text fields.
    func upload<T: Decodable>(_ path: String, file: URL, fields: [String: String], timeout: TimeInterval = 120) async throws -> T {
        let boundary = "apexvox-\(UUID().uuidString)"
        var request = makeRequest("POST", path)
        request.timeoutInterval = timeout
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        for (name, value) in fields {
            body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n")
        }
        let audio = try Data(contentsOf: file)
        body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(file.lastPathComponent)\"\r\n")
        body.append("Content-Type: audio/mp4\r\n\r\n")
        body.append(audio)
        body.append("\r\n--\(boundary)--\r\n")
        request.httpBody = body
        return try await send(request)
    }

    private func makeRequest(_ method: String, _ path: String, query: [String: String] = [:]) -> URLRequest {
        var components = URLComponents(url: baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: false)
        if !query.isEmpty {
            components?.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        }
        var request = URLRequest(url: components?.url ?? baseURL.appendingPathComponent(path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(Self.preferredLanguage, forHTTPHeaderField: "Accept-Language")
        if let token, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private func send<T: Decodable>(_ request: URLRequest) async throws -> T {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw APIError(status: 0, message: "Sin conexión con Apex Vox. Revisa tu internet e intenta de nuevo.")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw APIError(status: status, message: Self.errorMessage(from: data, status: status))
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError(status: status, message: "Apex Vox respondió algo inesperado. Actualiza la app.")
        }
    }

    // MARK: - Errors and language

    static var preferredLanguage: String {
        (Locale.preferredLanguages.first ?? "es").hasPrefix("en") ? "en" : "es"
    }

    /// The backend answers `{"detail": "Español / English"}`. Shows the half in the user's language.
    private static func errorMessage(from data: Data, status: Int) -> String {
        let fallback = "No pudimos completar la operación (\(status)). Intenta de nuevo."
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let detail = object["detail"] as? String, !detail.isEmpty
        else { return fallback }
        let parts = detail.components(separatedBy: " / ")
        guard parts.count == 2 else { return detail }
        return preferredLanguage == "en" ? parts[1] : parts[0]
    }
}

private extension Data {
    mutating func append(_ string: String) {
        append(Data(string.utf8))
    }
}

// MARK: - Endpoints

extension APIClient {
    func login(email: String, password: String) async throws -> UserProfile {
        try await send("POST", "api/auth/login", json: ["email": email, "password": password])
    }

    func register(email: String, password: String, fullName: String) async throws -> UserProfile {
        try await send("POST", "api/auth/register", json: ["email": email, "password": password, "full_name": fullName])
    }

    func me() async throws -> UserProfile {
        try await get("api/auth/me")
    }

    func logout() async {
        let _: EmptyResponse? = try? await send("POST", "api/auth/logout")
    }

    func tones() async throws -> ToneCatalog {
        try await get("api/dictation/tones", query: ["lang": Self.preferredLanguage])
    }

    func dictate(file: URL, settings: DictationSettings) async throws -> DictationResult {
        try await upload(
            "api/dictation",
            file: file,
            fields: [
                "tone": settings.tone,
                "instructions": settings.instructions,
                "language": settings.language,
                "vocabulary": settings.vocabulary,
            ],
            timeout: 90
        )
    }

    func rewrite(text: String, settings: DictationSettings) async throws -> DictationResult {
        try await send(
            "POST",
            "api/dictation/rewrite",
            json: ["text": text, "tone": settings.tone, "instructions": settings.instructions]
        )
    }

    func createMeeting(title: String, language: String) async throws -> BoxSession {
        try await send(
            "POST",
            "api/box/sessions",
            json: [
                "title": title,
                "mode": "presencial",
                "platform": "in_person",
                "block_duration_sec": MeetingRecorder.blockSeconds,
                "language": language,
                "device_type": "ios_app",
            ]
        )
    }

    func uploadBlock(sessionID: String, index: Int, file: URL, seconds: Double) async throws -> BoxBlockResponse {
        try await upload(
            "api/box/sessions/\(sessionID)/blocks",
            file: file,
            fields: [
                "block_index": String(index),
                "duration_hint_sec": String(format: "%.1f", seconds),
                "transcribe_immediately": "true",
            ],
            timeout: 300
        )
    }

    func addNote(sessionID: String, text: String, tag: String, at seconds: Double) async throws -> BoxNote {
        try await send(
            "POST",
            "api/box/sessions/\(sessionID)/notes",
            json: ["text": text, "tag": tag, "timestamp_sec": seconds]
        )
    }

    /// Merging the blocks and writing the summary and minutes can take minutes on a long meeting.
    func finalizeMeeting(sessionID: String) async throws -> BoxFinalize {
        try await send(
            "POST",
            "api/box/sessions/\(sessionID)/finalize",
            json: ["generate_minutes": true, "generate_minutes_template": "ejecutiva"],
            timeout: 600
        )
    }

    func history() async throws -> PortalSummary {
        try await get("api/portal/summary")
    }

    func result(jobID: String) async throws -> TranscriptionResult {
        try await get("api/jobs/\(jobID)/result")
    }
}
