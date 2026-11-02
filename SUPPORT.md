# Getting help

| You want to... | Go to |
| --- | --- |
| Ask a question, share an idea or show what you built | [GitHub Discussions](https://github.com/mateopiza/apex-vox/discussions) |
| Report a reproducible bug | [New issue → Bug report](https://github.com/mateopiza/apex-vox/issues/new/choose) |
| Propose a feature | [New issue → Feature request](https://github.com/mateopiza/apex-vox/issues/new/choose) |
| Report a security vulnerability | **Privately**, as described in [SECURITY.md](SECURITY.md). Never in a public issue |
| Get help with an account, payment or data request on the hosted service (apex-vox.ialabs.app) | Email [hola@ialabs.app](mailto:hola@ialabs.app) |

Before asking:

1. Read the [README](README.md) and the [docs](docs/), especially [configuration](docs/configuration.md) and [deployment](docs/deployment.md).
2. Check `GET /api/health` (with `X-Admin-Key` for details) and the container logs (`docker compose logs web`).
3. Search existing issues and discussions.

When you open an issue, include your version or commit, how you run the app (Docker or local), the relevant configuration with **all secrets removed**, and the steps to reproduce the problem. Issues and discussions in English or Spanish are both welcome.

Support on GitHub is best effort by the maintainers and the community.
