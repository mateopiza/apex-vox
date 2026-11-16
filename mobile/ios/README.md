# Apex Vox for iOS

A SwiftUI app and a dictation keyboard that use the Apex Vox backend.

> **Status: compiles, not yet run.** The app and the keyboard build without warnings in the `iOS` workflow (Xcode on macOS, simulator, unsigned). Neither has run on a simulator or a phone, and the TestFlight upload has not been tried.

## What it does

| Where | What |
| --- | --- |
| **Keyboard** (`ApexVoxKeyboard`) | A microphone key in any app. Dictate, and the text is inserted in the tone you chose (as spoken, clean, formal, professional, friendly, concise or your own instructions). Tone chips, undo of the last dictation, space, return, delete, comma and period. It is a dictation keyboard, not a full QWERTY one: switch back with the globe key to type. |
| **Dictar** tab | Opens the dictation session the keyboard needs, and dictates notes inside the app (copy, share, rewrite in another tone). |
| **Reunión** tab | Records a meeting with the screen off or other apps in front. Audio goes to Apex Box in 3-minute blocks, is transcribed while the meeting goes on, and timestamped notes (note, agreement, task, alert, idea, question) are added live. Ending the meeting produces the transcript, the summary and the minutes. |
| **Historial** tab | The account's saved transcriptions. |
| **Ajustes** tab | Default tone, style instructions, language, vocabulary, session length, keyboard setup steps, sign out. |

Dictation needs Apex Pro (`POST /api/dictation` answers 402 otherwise). Meetings use the account's normal quota.

## How the keyboard dictates

iOS does not give keyboard extensions access to the microphone. So:

1. The app opens a **dictation session**: it starts the microphone engine and stays alive in the background (`audio` background mode). iOS shows its microphone indicator for as long as the session is open. Audio is only written between a start and a stop.
2. The keyboard sends `start` / `stop` / `cancel` as Darwin notifications (`Shared/Bridge.swift`).
3. The app records, sends the clip to `POST /api/dictation`, deletes it, writes the text to a file in the shared App Group container and posts `stateChanged`.
4. The keyboard inserts the text and posts `consumed`; the app then erases its copy.

If no session is open, the microphone key opens the app (`apexvox://dictate`), which starts one; the user returns with the system "back to app" arrow. The session closes itself after the idle time set in Ajustes (15 minutes by default).

The keyboard needs **Allow Full Access** to read the shared container. It makes no network requests, never holds the session token (that stays in the app's Keychain) and reads nothing from the host app except the character before the cursor, to decide whether to add a space.

## Build

Requirements: Xcode 16, [XcodeGen](https://github.com/yonaskolb/XcodeGen).

```sh
cd mobile/ios
xcodegen generate      # writes ApexVox.xcodeproj, the Info.plists and the entitlements
open ApexVox.xcodeproj
```

Identifiers live in `project.yml`: `APP_BUNDLE_ID` (`app.ialabs.apexvox`), `APP_GROUP_ID` (`group.app.ialabs.apexvox`, also written in the two entitlements blocks) and `API_HOST` (`apex-vox.ialabs.app`). The keyboard cannot be tested in the Simulator end to end (no microphone session across apps); use a device.

### Without a Mac: GitHub Actions

`.github/workflows/ios.yml` compiles both targets on every change under `mobile/ios`. To sign and upload to TestFlight, run it by hand (**Actions → iOS → Run workflow**) with **upload** checked. It needs these repository secrets:

| Secret | Value |
| --- | --- |
| `APPLE_TEAM_ID` | The 10-character Team ID (developer.apple.com → Membership). |
| `ASC_KEY_ID` | Key ID of an App Store Connect API key (App Store Connect → Users and Access → Integrations → App Store Connect API). The key needs the **Admin** role so Xcode can create identifiers, profiles and the distribution certificate. |
| `ASC_ISSUER_ID` | Issuer ID shown on the same page. |
| `ASC_PRIVATE_KEY` | The full contents of the downloaded `AuthKey_XXXX.p8`. |

Before the first upload, in the Apple Developer portal: register the App IDs `app.ialabs.apexvox` and `app.ialabs.apexvox.keyboard` with the **App Groups** capability, create the group `group.app.ialabs.apexvox` and assign it to both; then create the app record in App Store Connect with the bundle ID `app.ialabs.apexvox`. The build number is the workflow run number.

This signing path (automatic signing with an API key on a fresh runner) has not been run yet. If it turns out to create a new development certificate on every run, switch the archive step to a certificate and profiles stored as secrets.

## Things to check on a real device

- **Opening the app from the keyboard.** Extensions have no public API for it; `KeyboardViewController.openContainingApp()` walks the responder chain to the application object. It is the approach dictation keyboards use, but it depends on iOS behaviour and App Review may question it. If it stops working, the fallback is to tell the user to open the app.
- **Background lifetime.** That the session survives with the app in the background for its full length, and that iOS ends it cleanly on a phone call.
- **Route changes.** Connecting AirPods mid-dictation closes the clip and continues in a new one; for a dictation only the second part is sent.
- **Account network limit.** The backend allows `MAX_IPS_PER_MONTH` (3 by default) networks per account. A phone moving between Wi-Fi and mobile data will pass it within days and get 403. This needs a backend decision before release, for example sessions tied to a device that count devices instead of networks.

## Not included yet

- Sign in with Google or GitHub (accounts created that way can set a password with "forgot password" on the web).
- Buying Apex Pro inside the app. The app links to the website; App Store rules on digital purchases apply before publishing.
- English strings (the texts are in Spanish, written as localizable keys).
- Android.
