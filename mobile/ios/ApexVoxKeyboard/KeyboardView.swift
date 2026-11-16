import SwiftUI

struct KeyboardView: View {
    @ObservedObject var model: KeyboardModel

    private let orange = Color(red: 0.957, green: 0.243, blue: 0.004)

    var body: some View {
        VStack(spacing: 8) {
            toneRow
            Text(statusText)
                .font(.footnote)
                .foregroundStyle(model.message == nil ? Color.secondary : Color.red)
                .lineLimit(2)
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity, minHeight: 32)
                .padding(.horizontal, 12)
            HStack(alignment: .center, spacing: 12) {
                VStack(spacing: 8) {
                    key(systemImage: "arrow.uturn.backward", label: "Deshacer dictado") { model.undoLastInsert() }
                        .disabled(!model.canUndo)
                    if model.status == .recording {
                        key(systemImage: "xmark", label: "Cancelar") { model.cancelRecording() }
                    } else {
                        key(text: ",", label: "Coma") { model.type(",") }
                    }
                }
                micButton
                VStack(spacing: 8) {
                    deleteKey
                    key(text: ".", label: "Punto") { model.type(".") }
                }
            }
            HStack(spacing: 8) {
                if model.showsGlobe {
                    key(systemImage: "globe", label: "Siguiente teclado") { model.nextKeyboard() }
                        .frame(width: 52)
                }
                key(text: "espacio", label: "Espacio") { model.type(" ") }
                key(systemImage: "return", label: "Intro") { model.type("\n") }
                    .frame(width: 72)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 8)
    }

    // MARK: - Tone

    private var toneRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(model.tones) { tone in
                    let selected = model.tone == tone.id
                    Button(tone.label) {
                        model.selectTone(tone.id)
                    }
                    .font(.footnote.weight(selected ? .semibold : .regular))
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(selected ? orange : Color(.systemBackground), in: Capsule())
                    .foregroundStyle(selected ? Color.white : Color.primary)
                }
            }
            .padding(.horizontal, 4)
        }
        .disabled(model.status == .noFullAccess)
    }

    // MARK: - Microphone

    private var micButton: some View {
        Button {
            model.micTapped()
        } label: {
            ZStack {
                Circle()
                    .fill(model.status == .recording ? Color.red : orange)
                    .frame(width: 84, height: 84)
                    .opacity(micEnabled ? 1 : 0.55)
                if model.status == .processing {
                    ProgressView().tint(.white)
                } else {
                    Image(systemName: micSymbol)
                        .font(.system(size: 30, weight: .semibold))
                        .foregroundStyle(.white)
                }
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
        .disabled(model.status == .processing)
        .accessibilityLabel(model.status == .recording ? "Terminar dictado" : "Dictar")
    }

    private var micEnabled: Bool {
        model.status == .ready || model.status == .recording
    }

    private var micSymbol: String {
        switch model.status {
        case .recording: return "stop.fill"
        case .ready, .processing: return "mic.fill"
        case .noFullAccess, .signedOut, .needsPro, .needsSession: return "arrow.up.forward.app.fill"
        }
    }

    private var statusText: String {
        if let message = model.message, model.status == .ready || model.status == .needsSession {
            return message
        }
        switch model.status {
        case .noFullAccess:
            return "Activa «Permitir acceso total» en Ajustes → Teclados → Apex Vox para dictar."
        case .signedOut:
            return "Toca para abrir Apex Vox e iniciar sesión."
        case .needsPro:
            return "El dictado es parte de Apex Pro. Toca para abrir Apex Vox."
        case .needsSession:
            return "Toca para abrir Apex Vox e iniciar el dictado; luego vuelve aquí."
        case .ready:
            return "Toca el micrófono y habla."
        case .recording:
            return "Escuchando… toca para terminar."
        case .processing:
            return "Transcribiendo…"
        }
    }

    // MARK: - Keys

    private func key(text: String? = nil, systemImage: String? = nil, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Group {
                if let systemImage {
                    Image(systemName: systemImage)
                } else {
                    Text(text ?? "")
                }
            }
            .font(.body)
            .frame(maxWidth: .infinity, minHeight: 42)
            .background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: 8))
            .foregroundStyle(Color.primary)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }

    /// Deletes one character on touch down and keeps deleting while held.
    private var deleteKey: some View {
        Image(systemName: "delete.left")
            .font(.body)
            .frame(maxWidth: .infinity, minHeight: 42)
            .background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: 8))
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in model.deletePressBegan() }
                    .onEnded { _ in model.deletePressEnded() }
            )
            .accessibilityLabel("Borrar")
            .accessibilityAddTraits(.isButton)
    }
}
