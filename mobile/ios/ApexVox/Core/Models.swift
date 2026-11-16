import Foundation

// Decoded with `.convertFromSnakeCase`: `user_id` arrives as `userId`.

struct EmptyResponse: Decodable {}

struct Quota: Decodable {
    var planDisplayName: String?
    var remainingTodaySeconds: Double?
    var isUnlimited: Bool?
}

struct UserProfile: Decodable {
    var userId: String
    var email: String
    var fullName: String?
    var plan: String
    var accessToken: String?
    var quota: Quota?

    var isPro: Bool {
        plan == "pro" || plan == "trial"
    }
}

struct ToneCatalog: Decodable {
    var tones: [ToneOption]
    var defaultTone: String
    var allowed: Bool

    enum CodingKeys: String, CodingKey {
        case tones
        case defaultTone = "default"
        case allowed
    }
}

struct DictationResult: Decodable {
    var text: String
    var rawText: String
    var tone: String
    var rewritten: Bool
    var durationSec: Double?
}

struct Segment: Decodable, Identifiable {
    var id: Int
    var speaker: String
    var text: String
    var startFormatted: String?
}

struct BoxSession: Decodable {
    var boxSessionId: String
    var title: String
}

struct BoxBlockResponse: Decodable {
    var newSegments: [Segment]?
    var totalDurationFormatted: String?
}

struct BoxNote: Decodable, Identifiable {
    var noteId: String
    var text: String
    var tag: String
    var timestampFormatted: String?

    var id: String { noteId }
}

struct TranscriptionResult: Decodable {
    var jobId: String
    var totalDurationFormatted: String?
    var segments: [Segment]?
    var fullText: String?
}

struct BoxFinalize: Decodable {
    var jobId: String
    var result: TranscriptionResult
}

struct HistoryItem: Decodable, Identifiable {
    var jobId: String
    var title: String?
    var totalDurationFormatted: String?
    var createdAt: String?

    var id: String { jobId }
}

struct PortalSummary: Decodable {
    var transcriptions: [HistoryItem]?
}
