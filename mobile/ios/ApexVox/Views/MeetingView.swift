import SwiftUI

struct MeetingView: View {
    @EnvironmentObject private var meeting: MeetingRecorder
    @EnvironmentObject private var dictation: DictationService
    @State private var title = ""
    @State private var noteText = ""
    @State private var noteTag = "nota"
    @State private var starting = false

    private let tags: [(id: String, label: String)] = [
        ("nota", "Nota"), ("acuerdo", "Acuerdo"), ("tarea", "Tarea"),
        ("alerta", "Alerta"), ("idea", "Idea"), ("pregunta", "Pregunta"),
    ]

    var body: some View {
        NavigationStack {
            Group {
                switch meeting.stage {
                case .idle:
                    setup
                case .recording:
                    recording
                case .finishing:
                    finishing
                case .done:
                    TranscriptView(result: meeting.transcript) {
                        meeting.reset()
                    }
                }
            }
            .navigationTitle("Reunión")
        }
    }

    // MARK: - Before

    private var setup: some View {
        Form {
            Section {
                TextField("Título (opcional)", text: $title)
            } footer: {
                Text("La grabación sigue con la pantalla apagada o usando otras apps. Se envía en bloques de 3 minutos y se transcribe mientras avanza la reunión. Avisa a los asistentes de que estás grabando.")
            }
            Section {
                Button {
                    starting = true
                    Task {
                        await meeting.start(title: title, language: meetingLanguage)
                        starting = false
                    }
                } label: {
                    HStack {
                        Label("Empezar a grabar", systemImage: "record.circle")
                        Spacer()
                        if starting {
                            ProgressView()
                        }
                    }
                }
                .disabled(starting)
            } footer: {
                if let message = meeting.errorMessage {
                    ErrorBanner(message: message)
                }
            }
        }
    }

    /// Apex Box needs a language; "auto" in the dictation settings means the phone's.
    private var meetingLanguage: String {
        let chosen = dictation.settings.language
        return chosen == "auto" ? APIClient.preferredLanguage : chosen
    }

    // MARK: - During

    private var recording: some View {
        VStack(spacing: 0) {
            VStack(spacing: 6) {
                Text(clockString(meeting.elapsed))
                    .font(.system(size: 44, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                ProgressView(value: Double(min(1, meeting.level)))
                    .tint(Brand.orange)
                    .padding(.horizontal, 60)
                if meeting.pendingBlocks > 0 {
                    Text("\(meeting.pendingBlocks) bloque(s) por enviar")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let message = meeting.errorMessage {
                    ErrorBanner(message: message).padding(.horizontal)
                }
            }
            .padding(.vertical, 16)

            List {
                if !meeting.notes.isEmpty {
                    Section("Notas") {
                        ForEach(meeting.notes) { note in
                            VStack(alignment: .leading, spacing: 2) {
                                Text("\(note.timestampFormatted ?? "") · \(note.tag.capitalized)")
                                    .font(.caption)
                                    .foregroundStyle(Brand.orange)
                                Text(note.text)
                            }
                        }
                    }
                }
                Section("Transcripción en vivo") {
                    if meeting.segments.isEmpty {
                        Text("El texto aparece al cerrar cada bloque de 3 minutos.")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(meeting.segments) { segment in
                        SegmentRow(segment: segment)
                    }
                }
            }
            .listStyle(.insetGrouped)

            VStack(spacing: 10) {
                HStack {
                    Picker("Tipo", selection: $noteTag) {
                        ForEach(tags, id: \.id) { tag in
                            Text(tag.label).tag(tag.id)
                        }
                    }
                    .pickerStyle(.menu)
                    TextField("Nota en este momento…", text: $noteText)
                        .textFieldStyle(.roundedBorder)
                    Button {
                        let text = noteText
                        noteText = ""
                        Task { await meeting.addNote(text, tag: noteTag) }
                    } label: {
                        Image(systemName: "plus.circle.fill").font(.title2)
                    }
                    .disabled(noteText.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                Button(role: .destructive) {
                    Task { await meeting.stop() }
                } label: {
                    Label("Terminar reunión", systemImage: "stop.circle.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
            }
            .padding()
            .background(.bar)
        }
    }

    // MARK: - After

    private var finishing: some View {
        VStack(spacing: 16) {
            if let message = meeting.errorMessage {
                ErrorBanner(message: message)
                Button("Reintentar") {
                    Task { await meeting.retry() }
                }
                .buttonStyle(.borderedProminent)
                .tint(Brand.orange)
            } else {
                ProgressView()
                Text("Preparando la transcripción, el resumen y el acta…")
                    .foregroundStyle(.secondary)
                Text("Puede tardar unos minutos en reuniones largas. No cierres la app.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .multilineTextAlignment(.center)
        .padding()
    }
}

struct SegmentRow: View {
    let segment: Segment

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("\(segment.startFormatted ?? "") · \(segment.speaker)")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(segment.text)
        }
    }
}

/// A finished transcript: used after a meeting and from the history.
struct TranscriptView: View {
    let result: TranscriptionResult?
    var onClose: (() -> Void)?

    var body: some View {
        List {
            if let result {
                Section {
                    LabeledContent("Duración", value: result.totalDurationFormatted ?? "—")
                    ShareLink(item: plainText(result)) {
                        Label("Compartir transcripción", systemImage: "square.and.arrow.up")
                    }
                    Link(destination: webURL(result)) {
                        Label("Resumen, acta y audio en la web", systemImage: "safari")
                    }
                }
                Section("Transcripción") {
                    ForEach(result.segments ?? []) { segment in
                        SegmentRow(segment: segment)
                    }
                }
            }
            if let onClose {
                Section {
                    Button("Nueva reunión", action: onClose)
                }
            }
        }
    }

    private func plainText(_ result: TranscriptionResult) -> String {
        let lines = (result.segments ?? []).map { "[\($0.startFormatted ?? "")] \($0.speaker): \($0.text)" }
        return lines.isEmpty ? (result.fullText ?? "") : lines.joined(separator: "\n")
    }

    private func webURL(_ result: TranscriptionResult) -> URL {
        var components = URLComponents(url: APIClient.shared.baseURL, resolvingAgainstBaseURL: false)
        components?.queryItems = [URLQueryItem(name: "job", value: result.jobId)]
        return components?.url ?? APIClient.shared.baseURL
    }
}
