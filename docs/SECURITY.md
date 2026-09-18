# Security

Never commit `.env`, credentials, uploaded documents, SQLite databases, model weights, or generated reports. Gemini keys and Ollama endpoints are backend-only. When authentication is enabled, DocIA refuses to start without a configured password and JWT signing secret.

The API restricts CORS origins and enforces file count, per-file size, total batch size, extension, and MIME checks. Ollama destinations cannot be supplied by a browser request, which prevents user-controlled server-side requests.

If a secret has ever been committed, rotate it first. Removing it from the latest commit is insufficient: rewrite Git history with a reviewed tool such as `git filter-repo`, then coordinate a force-push with all collaborators.
