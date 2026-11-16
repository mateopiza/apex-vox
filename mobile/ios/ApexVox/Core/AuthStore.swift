import Foundation
import Security

/// The session token lives in the Keychain of the app only. The keyboard never sees it: it asks
/// the app to dictate.
enum Keychain {
    private static let service = "app.ialabs.apexvox.session"
    private static let account = "token"

    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
    }

    static func readToken() -> String? {
        var request = query
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(request as CFDictionary, &item) == errSecSuccess, let data = item as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    static func saveToken(_ token: String) {
        SecItemDelete(query as CFDictionary)
        var item = query
        item[kSecValueData as String] = Data(token.utf8)
        // Dictation uploads run while the phone is locked or the app is in the background.
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(item as CFDictionary, nil)
    }

    static func deleteToken() {
        SecItemDelete(query as CFDictionary)
    }
}

@MainActor
final class AuthStore: ObservableObject {
    static let shared = AuthStore()

    @Published private(set) var profile: UserProfile?
    @Published private(set) var isRestoring = true

    var isSignedIn: Bool { profile != nil }
    var isPro: Bool { profile?.isPro ?? false }

    private let api = APIClient.shared

    private init() {
        api.token = Keychain.readToken()
    }

    /// Called once at launch: turns a saved token back into a profile.
    func restore() async {
        defer { isRestoring = false }
        guard api.token != nil else {
            publish()
            return
        }
        await refresh()
    }

    func refresh() async {
        do {
            profile = try await api.me()
        } catch let error as APIError where error.needsSignIn {
            clear()
        } catch {
            // Offline or a server error: keep the session and what we knew about the plan.
        }
        publish()
    }

    func signIn(email: String, password: String) async throws {
        accept(try await api.login(email: email, password: password))
    }

    func register(email: String, password: String, fullName: String) async throws {
        accept(try await api.register(email: email, password: password, fullName: fullName))
    }

    func signOut() async {
        await api.logout()
        clear()
        publish()
    }

    private func accept(_ profile: UserProfile) {
        if let token = profile.accessToken, !token.isEmpty {
            api.token = token
            Keychain.saveToken(token)
        }
        self.profile = profile
        publish()
    }

    private func clear() {
        api.token = nil
        Keychain.deleteToken()
        profile = nil
    }

    /// Tells the keyboard whether dictation can work at all.
    private func publish() {
        var state = SharedStore.loadState()
        state.signedIn = api.token != nil
        state.canDictate = isPro
        SharedStore.saveState(state)
        BridgeSignal.stateChanged.post()
    }
}
