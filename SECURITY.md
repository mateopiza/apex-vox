# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| `main` (latest commit) | Yes |
| 2.0.x | Yes |
| Older snapshots | No |

The hosted service at <https://apex-vox.ialabs.app> always runs a recent `main`. Self-hosted instances should keep up with `main` to receive fixes.

## Reporting a vulnerability

**Do not open a public issue for security problems.** Use one of these channels instead:

- Email **[seguridad@ialabs.app](mailto:seguridad@ialabs.app)**, or
- [Open a private security advisory](https://github.com/mateopiza/apex-vox/security/advisories/new) on GitHub.

Please include:

- a description of the issue and its impact;
- steps to reproduce (requests, payloads, affected URLs or files and lines);
- the version or commit you tested, and whether it was the hosted service or a self-hosted instance;
- how to reach you for follow-up.

## What to expect

- **First response within 3 business days.**
- We confirm the issue, agree a fix timeline with you based on severity, and keep you updated until it is resolved.
- After the fix ships we credit you in the release notes, unless you prefer to stay anonymous.

## Scope

In scope:

- the code in this repository: the FastAPI app, the web UI, the Chrome extension, the Supabase schema and the Docker setup;
- the hosted service at `apex-vox.ialabs.app`.

Out of scope:

- denial-of-service attacks, and volumetric or load testing;
- social engineering, phishing and physical attacks;
- spam, or reports about missing email best practices without a demonstrable impact;
- issues in third-party providers (Groq, Deepgram, Recall.ai, Resend, Supabase, Bold, Cloudflare, the object-storage provider). Report those to the vendor;
- findings that require a compromised device or browser.

## Safe harbor

While you investigate:

- do not access, modify or delete other people's data. Use your own accounts, or test accounts you create;
- do not degrade the service or affect its availability for others;
- do not publish or share the finding until it is fixed and we have agreed on disclosure.

We will not pursue legal action against good-faith research that follows these rules. This policy matches the security policy published by the app at `/legal/seguridad` and in `/.well-known/security.txt`.

## Self-hosted instances

If you operate your own deployment, set `SECURITY_EMAIL` so that your `security.txt` and security policy page point to your own contact. See [docs/security.md](docs/security.md) for the controls in the code and how to rotate credentials.
