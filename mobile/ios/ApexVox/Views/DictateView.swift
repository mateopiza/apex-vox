import SwiftUI

struct DictateView: View {
    @EnvironmentObject private var auth: AuthStore
    @EnvironmentObject private var dictation: DictationService

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    if auth.isPro {
                        sessionCard
                        tonePicker
                        recorder
                        notesCard
                    } else {
                        proNotice
                    }
                }
                .padding()
            }
            .background(Brand.paper.ignoresSafeArea())
            .navigationTitle("Dictar")
            .task { await auth.refresh() }
        }
    }

    // MARK: - Keyboard session

    private var sessionCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: dictation.sessionActive ? "keyboard.badge.ellipsis" : "keyboard")
                    .foregroundStyle(dictation.sessionActive ? Brand.orange : .secondary)
                Text(dictation.sessionActive ? "Teclado listo para dictar" : "Dictar desde el teclado")
                    .font(.headline)
            }
            if dictation.sessionActive {
                Text("Vuelve a la app donde quieres escribir y toca el micrófono del teclado Apex Vox. El indicador naranja de iOS seguirá encendido mientras la sesión esté abierta; solo se guarda audio mientras dictas.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                if let end = dictation.sessionEndsAt {
                    Text("Se cierra sola \(end, style: .relative) después del último dictado.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                Button("Cerrar sesión de dictado", role: .destructive) {
                    dictation.endSession()
                }
            } else {
                Text("iOS no deja que un teclado use el micrófono, así que la app escucha por él. Abre una sesión y cambia a la app donde quieres escribir.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Button("Abrir sesión de dictado") {
                    Task { await dictation.startSession() }
                }
                .buttonStyle(.borderedProminent)
                .tint(Brand.orange)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(.background, in: RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - Tone

    private var tonePicker: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Tono")
                .font(.subheadline.weight(.semibold))
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(dictation.tones) { tone in
                        let selected = dictation.settings.tone == tone.id
                        Button(tone.label) {
                            dictation.settings.tone = tone.id
                        }
                        .font(.subheadline)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 8)
                        .background(selected ? Brand.orange : Color(.secondarySystemBackground), in: Capsule())
                        .foregroundStyle(selected ? .white : Brand.ink)
                    }
                }
            }
            if let current = dictation.tones.first(where: { $0.id == dictation.settings.tone }), !current.description.isEmpty {
                Text(current.description)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            if dictation.settings.tone == "custom" {
                TextField("Ej.: como un mensaje corto para un cliente", text: $dictation.settings.instructions, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...3)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - In-app dictation

    private var recorder: some View {
        VStack(spacing: 8) {
            RecordButton(
                isRecording: dictation.phase == .recording,
                isBusy: dictation.phase == .processing,
                level: dictation.level
            ) {
                Task { await dictation.toggleFromApp() }
            }
            Text(statusText)
                .font(.footnote)
                .foregroundStyle(.secondary)
            if let message = dictation.errorMessage {
                ErrorBanner(message: message)
            }
        }
    }

    private var statusText: String {
        switch dictation.phase {
        case .idle: return "Toca para dictar una nota aquí"
        case .recording: return "Escuchando… toca para terminar"
        case .processing: return "Transcribiendo…"
        }
    }

    private var notesCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextEditor(text: $dictation.notes)
                .frame(minHeight: 160)
                .scrollContentBackground(.hidden)
                .padding(8)
                .background(.background, in: RoundedRectangle(cornerRadius: 12))
            HStack {
                Button {
                    UIPasteboard.general.string = dictation.notes
                } label: {
                    Label("Copiar", systemImage: "doc.on.doc")
                }
                Spacer()
                Button {
                    Task { await dictation.rewriteNotes() }
                } label: {
                    Label("Reformular", systemImage: "wand.and.stars")
                }
                Spacer()
                ShareLink(item: dictation.notes) {
                    Label("Compartir", systemImage: "square.and.arrow.up")
                }
                Spacer()
                Button(role: .destructive) {
                    dictation.notes = ""
                } label: {
                    Label("Borrar", systemImage: "trash")
                }
            }
            .font(.footnote)
            .labelStyle(.titleAndIcon)
            .disabled(dictation.notes.isEmpty || dictation.phase != .idle)
        }
    }

    // MARK: - Free plan

    private var proNotice: some View {
        VStack(spacing: 12) {
            Image(systemName: "sparkles")
                .font(.largeTitle)
                .foregroundStyle(Brand.orange)
            Text("El dictado es parte de Apex Pro")
                .font(.headline)
            Text("Con Apex Pro dictas desde cualquier app con el teclado Apex Vox y eliges el tono del texto. Con tu plan actual puedes grabar y transcribir reuniones en la pestaña Reunión.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Link("Ver Apex Pro en la web", destination: APIClient.shared.baseURL)
                .buttonStyle(.borderedProminent)
                .tint(Brand.orange)
            Button("Ya soy Pro: actualizar") {
                Task { await auth.refresh() }
            }
            .font(.footnote)
        }
        .padding()
        .frame(maxWidth: .infinity)
        .background(.background, in: RoundedRectangle(cornerRadius: 16))
    }
}
