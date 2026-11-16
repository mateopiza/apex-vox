import SwiftUI

struct HistoryView: View {
    @State private var items: [HistoryItem] = []
    @State private var loading = true
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            List {
                if let errorMessage {
                    ErrorBanner(message: errorMessage)
                }
                if !loading, items.isEmpty, errorMessage == nil {
                    Text("Aún no tienes transcripciones guardadas.")
                        .foregroundStyle(.secondary)
                }
                ForEach(items) { item in
                    NavigationLink {
                        HistoryDetailView(item: item)
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.title ?? "Transcripción")
                                .lineLimit(1)
                            Text("\(dateString(item.createdAt)) · \(item.totalDurationFormatted ?? "")")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .overlay {
                if loading, items.isEmpty {
                    ProgressView()
                }
            }
            .navigationTitle("Historial")
            .refreshable { await load() }
            .task { await load() }
        }
    }

    private func load() async {
        do {
            items = try await APIClient.shared.history().transcriptions ?? []
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
        loading = false
    }

    private func dateString(_ iso: String?) -> String {
        guard let iso else { return "" }
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let date = parser.date(from: iso) ?? ISO8601DateFormatter().date(from: iso)
        guard let date else { return String(iso.prefix(10)) }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}

struct HistoryDetailView: View {
    let item: HistoryItem
    @State private var result: TranscriptionResult?
    @State private var errorMessage: String?

    var body: some View {
        Group {
            if let result {
                TranscriptView(result: result)
            } else if let errorMessage {
                ErrorBanner(message: errorMessage).padding()
            } else {
                ProgressView()
            }
        }
        .navigationTitle(item.title ?? "Transcripción")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            do {
                result = try await APIClient.shared.result(jobID: item.jobId)
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}
