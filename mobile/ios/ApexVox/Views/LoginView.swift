import SwiftUI

struct LoginView: View {
    @EnvironmentObject private var auth: AuthStore
    @State private var creatingAccount = false
    @State private var fullName = ""
    @State private var email = ""
    @State private var password = ""
    @State private var working = false
    @State private var errorMessage: String?

    private var canSubmit: Bool {
        email.contains("@") && password.count >= 8 && !working
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    if creatingAccount {
                        TextField("Nombre", text: $fullName)
                            .textContentType(.name)
                    }
                    TextField("Correo", text: $email)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField("Contraseña (mínimo 8 caracteres)", text: $password)
                        .textContentType(creatingAccount ? .newPassword : .password)
                } footer: {
                    if let errorMessage {
                        ErrorBanner(message: errorMessage)
                    }
                }

                Section {
                    Button {
                        Task { await submit() }
                    } label: {
                        HStack {
                            Text(creatingAccount ? "Crear cuenta" : "Iniciar sesión")
                            Spacer()
                            if working {
                                ProgressView()
                            }
                        }
                    }
                    .disabled(!canSubmit)

                    Button(creatingAccount ? "Ya tengo cuenta" : "Crear una cuenta") {
                        creatingAccount.toggle()
                        errorMessage = nil
                    }
                } footer: {
                    Text("Si entraste a Apex Vox con Google o GitHub, crea una contraseña en la web con «Olvidé mi contraseña» y úsala aquí.")
                }
            }
            .navigationTitle("Apex Vox")
        }
    }

    private func submit() async {
        working = true
        errorMessage = nil
        defer { working = false }
        let address = email.trimmingCharacters(in: .whitespaces).lowercased()
        do {
            if creatingAccount {
                try await auth.register(email: address, password: password, fullName: fullName)
            } else {
                try await auth.signIn(email: address, password: password)
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
