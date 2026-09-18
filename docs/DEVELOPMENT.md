# Development

Install runtime dependencies from `requirements.txt` and developer tooling from `requirements-dev.txt`. Keep configuration in `.env`, based on `.env.example`.

Before opening a pull request, run Python tests and Ruff, then `npm run lint` and `npm run build` from `frontend/`. Add only synthetic fixtures. New API routes must reuse centralized configuration, authentication dependencies, upload validation, and persistence controls.

Use focused commits such as `fix: reject oversized uploads`, `refactor: centralize runtime configuration`, or `test: cover history privacy defaults`.
