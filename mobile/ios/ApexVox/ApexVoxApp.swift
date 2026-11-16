import SwiftUI

@main
struct ApexVoxApp: App {
    @StateObject private var auth = AuthStore.shared
    @StateObject private var dictation = DictationService.shared
    @StateObject private var meeting = MeetingRecorder.shared
    @State private var tab = AppTab.dictate

    var body: some Scene {
        WindowGroup {
            RootView(tab: $tab)
                .environmentObject(auth)
                .environmentObject(dictation)
                .environmentObject(meeting)
                .task {
                    await auth.restore()
                    await dictation.loadTones()
                }
                .onOpenURL { url in
                    // apexvox://dictate — the keyboard asks the app to open a dictation session.
                    guard url.scheme == "apexvox", url.host == "dictate" else { return }
                    tab = .dictate
                    Task {
                        if auth.isSignedIn, auth.isPro, !dictation.sessionActive {
                            await dictation.startSession()
                        }
                    }
                }
        }
    }
}

enum AppTab: Hashable {
    case dictate
    case meeting
    case history
    case settings
}

enum Brand {
    static let orange = Color(red: 0.957, green: 0.243, blue: 0.004)
    static let ink = Color(red: 0.188, green: 0.169, blue: 0.157)
    static let paper = Color(red: 0.953, green: 0.953, blue: 0.933)
}

struct RootView: View {
    @EnvironmentObject private var auth: AuthStore
    @Binding var tab: AppTab

    var body: some View {
        if auth.isRestoring {
            ProgressView()
        } else if !auth.isSignedIn {
            LoginView()
        } else {
            TabView(selection: $tab) {
                DictateView()
                    .tabItem { Label("Dictar", systemImage: "mic.fill") }
                    .tag(AppTab.dictate)
                MeetingView()
                    .tabItem { Label("Reunión", systemImage: "person.2.wave.2.fill") }
                    .tag(AppTab.meeting)
                HistoryView()
                    .tabItem { Label("Historial", systemImage: "clock.arrow.circlepath") }
                    .tag(AppTab.history)
                SettingsView()
                    .tabItem { Label("Ajustes", systemImage: "gearshape.fill") }
                    .tag(AppTab.settings)
            }
            .tint(Brand.orange)
        }
    }
}

/// Round record button used for dictation and meetings.
struct RecordButton: View {
    let isRecording: Bool
    let isBusy: Bool
    let level: Float
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle()
                    .fill(Brand.orange.opacity(0.18))
                    .frame(width: 132, height: 132)
                    .scaleEffect(isRecording ? 1 + CGFloat(level) * 0.35 : 1)
                    .animation(.easeOut(duration: 0.12), value: level)
                Circle()
                    .fill(isRecording ? Color.red : Brand.orange)
                    .frame(width: 96, height: 96)
                if isBusy {
                    ProgressView().tint(.white)
                } else {
                    Image(systemName: isRecording ? "stop.fill" : "mic.fill")
                        .font(.system(size: 34, weight: .semibold))
                        .foregroundStyle(.white)
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(isBusy)
        .accessibilityLabel(isRecording ? "Detener" : "Grabar")
    }
}

struct ErrorBanner: View {
    let message: String

    var body: some View {
        Label(message, systemImage: "exclamationmark.triangle.fill")
            .font(.footnote)
            .foregroundStyle(.red)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

func clockString(_ seconds: Double) -> String {
    let total = Int(max(0, seconds))
    return String(format: "%02d:%02d:%02d", total / 3600, (total / 60) % 60, total % 60)
}
