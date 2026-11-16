import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var auth: AuthStore
    @EnvironmentObject private var dictation: DictationService

    private let languages: [(id: String, label: String)] = [
        ("auto", "Detectar"), ("es", "Español"), ("en", "English"), ("pt", "Português"), ("fr", "Français"),
    ]

    var body: some View {
        NavigationStack {
            Form {
                Section("Cuenta") {
                    LabeledContent("Correo", value: auth.profile?.email ?? "")
                    LabeledContent("Plan", value: auth.isPro ? "Apex Pro" : "Gratis")
                    Button("Cerrar sesión", role: .destructive) {
                        dictation.endSession()
                        Task { await auth.signOut() }
                    }
                }

                Section {
                    Picker("Tono", selection: $dictation.settings.tone) {
                        ForEach(dictation.tones) { tone in
                            Text(tone.label).tag(tone.id)
                        }
                    }
                    TextField("Instrucciones de estilo (opcional)", text: $dictation.settings.instructions, axis: .vertical)
                        .lineLimit(1...3)
                    Picker("Idioma", selection: $dictation.settings.language) {
                        ForEach(languages, id: \.id) { language in
                            Text(language.label).tag(language.id)
                        }
                    }
                    TextField("Nombres y términos que usas", text: $dictation.settings.vocabulary, axis: .vertical)
                        .lineLimit(1...3)
                    Stepper(
                        "La sesión del teclado dura \(dictation.settings.sessionMinutes) min",
                        value: $dictation.settings.sessionMinutes,
                        in: 5...60,
                        step: 5
                    )
                } header: {
                    Text("Dictado")
                } footer: {
                    Text("Las instrucciones se suman al tono elegido; con el tono Personalizado son la única guía. Los nombres y términos ayudan a escribirlos bien.")
                }

                Section {
                    NavigationLink("Activar el teclado Apex Vox") {
                        KeyboardSetupView()
                    }
                }

                Section {
                    Link("Privacidad", destination: APIClient.shared.baseURL.appendingPathComponent("legal/privacidad"))
                    Link("Términos", destination: APIClient.shared.baseURL.appendingPathComponent("legal/terminos"))
                    LabeledContent("Versión", value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "")
                }
            }
            .navigationTitle("Ajustes")
        }
    }
}

struct KeyboardSetupView: View {
    var body: some View {
        List {
            Section {
                step(1, "Abre Ajustes de iOS → General → Teclado → Teclados → Añadir nuevo teclado y elige Apex Vox.")
                step(2, "Toca Apex Vox en la lista y activa «Permitir acceso total». Hace falta para que el teclado reciba el texto que la app transcribe. El teclado no guarda lo que escribes ni lo envía a ningún lado.")
                step(3, "En cualquier app, mantén pulsado el globo 🌐 y elige Apex Vox.")
                step(4, "Toca el micrófono. La primera vez se abre esta app para iniciar la sesión de dictado; vuelve a tu app con la flecha de la esquina superior izquierda y dicta.")
            } footer: {
                Text("iOS no permite que los teclados usen el micrófono. Por eso la app escucha en segundo plano mientras la sesión de dictado está abierta.")
            }
            Section {
                Button("Abrir Ajustes") {
                    if let url = URL(string: UIApplication.openSettingsURLString) {
                        UIApplication.shared.open(url)
                    }
                }
            }
        }
        .navigationTitle("Teclado")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func step(_ number: Int, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text("\(number)")
                .font(.headline)
                .foregroundStyle(.white)
                .frame(width: 28, height: 28)
                .background(Brand.orange, in: Circle())
            Text(text)
        }
        .padding(.vertical, 4)
    }
}
