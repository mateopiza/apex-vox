import SwiftUI
import UIKit

/// The Apex Vox dictation keyboard. It has no microphone access (iOS forbids it for keyboards) and
/// makes no network requests: it signals the app, which records and transcribes, and inserts the
/// text the app hands back. It never reads what is typed in the host app beyond the last character,
/// which it needs to decide whether to add a space.
final class KeyboardViewController: UIInputViewController {
    private let model = KeyboardModel()

    override func viewDidLoad() {
        super.viewDidLoad()
        model.controller = self

        let host = UIHostingController(rootView: KeyboardView(model: model))
        host.view.backgroundColor = .clear
        host.view.translatesAutoresizingMaskIntoConstraints = false
        addChild(host)
        view.addSubview(host.view)
        host.didMove(toParent: self)

        let height = view.heightAnchor.constraint(equalToConstant: 252)
        height.priority = UILayoutPriority(999)
        NSLayoutConstraint.activate([
            host.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            host.view.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            host.view.topAnchor.constraint(equalTo: view.topAnchor),
            host.view.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            height,
        ])
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        model.showsGlobe = needsInputModeSwitchKey
        model.appear()
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        model.disappear()
    }

    override func textDidChange(_ textInput: UITextInput?) {
        super.textDidChange(textInput)
        model.showsGlobe = needsInputModeSwitchKey
    }

    /// Opens the containing app. Extensions have no public API for this, so the call goes through
    /// the responder chain to the host application object.
    func openContainingApp() {
        guard let url = URL(string: "apexvox://dictate"),
              let applicationClass = NSClassFromString("UIApplication")
        else { return }
        let selector = NSSelectorFromString("openURL:options:completionHandler:")
        typealias OpenURL = @convention(c) (AnyObject, Selector, NSURL, NSDictionary, AnyObject?) -> Void

        var responder: UIResponder? = self
        while let current = responder {
            if current.isKind(of: applicationClass), current.responds(to: selector), let implementation = current.method(for: selector) {
                let open = unsafeBitCast(implementation, to: OpenURL.self)
                open(current, selector, url as NSURL, NSDictionary(), nil)
                return
            }
            responder = current.next
        }
    }
}
