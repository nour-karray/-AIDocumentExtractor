# DocIA

DocIA is an intelligent document processing platform that converts heterogeneous PDFs and scanned documents into validated structured data. A Next.js interface talks to a FastAPI backend that can use local OCR/Ollama or a server-side Gemini integration.

> For document extraction only. Extracted medical information must be verified before professional use. DocIA is not a certified medical device and does not provide diagnoses or medical advice.

## Features

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

## Supported document types

- Medical laboratory reports
- STEG electricity invoices
- Supplier invoices
- Receipts
- Unknown documents, reported without inventing a schema

## Tech stack

Next.js 15 and TypeScript power the frontend. FastAPI, Pydantic, SQLite, OpenCV and OCR providers power the backend. The optional local AI path uses Docling, PaddleOCR/Tesseract and Qwen2.5 through Ollama; Gemini is the only hosted AI provider implemented.

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
corepack pnpm install --frozen-lockfile
corepack pnpm run dev
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
python -m compileall -q backend src pipelines scripts
cd frontend
corepack pnpm run lint
corepack pnpm run build
```

## Fine-tuning preparation

The repository includes dataset validation, split, LLaMA-Factory export and LoRA training utilities. Generated datasets and weights are not committed. Runtime uses base Qwen2.5 unless a trained model is explicitly configured; model output never becomes ground truth automatically. See [the fine-tuning guide](docs/FINE_TUNING_QWEN.md).

## Security and privacy

Secrets are server-side only. Source documents and raw OCR text are not persisted by default, and runtime data is ignored by Git. See [privacy](docs/PRIVACY.md) and [security](docs/SECURITY.md).

## Limitations

Extraction accuracy depends on document quality, OCR availability and the configured model. Outputs require human verification. DocIA is a single-user/private application, not a multi-tenant SaaS, certified medical device, diagnostic tool or clinical decision-support system.

## Repository layout

- `backend/` — FastAPI endpoints, authentication, orchestration
- `frontend/` — Next.js interface
- `src/` — configuration, OCR, routing, validation, persistence
- `pipelines/` — document-specific extraction pipelines
- `scripts/` — dataset preparation and evaluation utilities
- `tests/` — automated tests using synthetic data only
- `examples/synthetic/` — safe example payloads
- `docs/` — architecture, security, privacy, and development notes

Runtime documents, databases, model weights, and generated reports are excluded from Git. See [development](docs/DEVELOPMENT.md) and [architecture](docs/ARCHITECTURE.md) for more detail.

## License

No license has been declared yet. Add one before accepting external contributions or redistribution.
