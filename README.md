# DocIA

DocIA is a privacy-conscious document extraction platform for medical reports, invoices, and receipts. A Next.js interface talks to a FastAPI backend that can use local OCR/Ollama or a server-side Gemini integration.

> Portfolio project — not a certified medical device. Do not use generated output as medical advice or a diagnosis.

## Highlights

- Automatic document routing and structured JSON extraction
- Local pipeline with Docling, PaddleOCR/Tesseract, and Ollama
- Optional Gemini processing with the API key kept on the backend
- Real dashboard and history data; no fabricated metrics
- Upload limits, explicit CORS policy, optional JWT authentication
- Privacy-first persistence: source files and raw OCR text are disabled by default

## Architecture

```text
Browser (Next.js) -> FastAPI -> router -> local OCR/Ollama or Gemini
                                -> validated JSON -> SQLite/history
```

Uploaded files are processed in temporary storage. Set `DOCIA_STORE_SOURCE_FILES=true` only when retention is required and legally appropriate.

## Quick start

Requirements: Python 3.11+, Node.js 20+, and optionally Tesseract/Ollama.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn backend.app.main:app --reload
```

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`; API documentation is at `http://127.0.0.1:8000/docs`.

## Configuration

All secrets and model endpoints belong in the backend `.env`; the frontend never accepts or stores API keys. Important variables are documented in `.env.example`.

To enable authentication, set `DOCIA_AUTH_ENABLED=true`, configure either `DOCIA_AUTH_PASSWORD_HASH` or `DOCIA_AUTH_PASSWORD`, and provide a strong `DOCIA_AUTH_TOKEN_SECRET`. Generate a password hash with:

```powershell
python -c "from backend.app.auth import hash_password; print(hash_password('replace-me'))"
```

## Quality checks

```powershell
python -m pytest -q
python -m ruff check backend src pipelines scripts tests
cd frontend
npm run lint
npm run build
```

## Repository layout

- `backend/` — FastAPI endpoints, authentication, orchestration
- `frontend/` — Next.js interface
- `src/` — configuration, OCR, routing, validation, persistence
- `pipelines/` — document-specific extraction pipelines
- `scripts/` — dataset preparation and evaluation utilities
- `tests/` — automated tests using synthetic data only
- `examples/synthetic/` — safe example payloads
- `docs/` — architecture, security, privacy, and development notes

Runtime documents, databases, model weights, and generated reports are excluded from Git. See [privacy](docs/PRIVACY.md), [security](docs/SECURITY.md), and [architecture](docs/ARCHITECTURE.md).

## License

No license has been declared yet. Add one before accepting external contributions or redistribution.
