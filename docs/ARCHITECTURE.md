# Architecture de DocIA

Ce document décrit l'implémentation réellement présente dans le dépôt.

## Composants

- `frontend/` : application Next.js 15. Elle affiche le tableau de bord, les documents, l'historique, les résultats, le profil et l'état du runtime. Elle ne stocke aucune clé API.
- `backend/app/` : API FastAPI, authentification JWT optionnelle, validation des uploads et orchestration des extractions.
- `src/` : configuration centralisée, OCR, classification, normalisation, stockage et génération de rapports.
- `pipelines/` : extracteurs Gemini spécialisés. Le SDK utilisé est `google-genai`.
- `scripts/` : préparation de datasets, évaluation et fine-tuning hors runtime.

## Flux d'extraction

```text
Navigateur
  -> POST /api/extractions
  -> validation type/taille/lot
  -> processus isolé avec timeout
  -> détection du type de document
  -> pipeline local, OCR classique ou Gemini
  -> normalisation et validation métier
  -> résultat JSON et historique SQLite
  -> tableau de bord calculé à partir de l'historique réel
```

Chaque extraction longue s'exécute dans un processus terminable. Après expiration du délai, le processus est arrêté et son répertoire temporaire supprimé avant que l'API ne retourne une erreur.

## Stockage et confidentialité

Les données runtime vivent sous `data/`, qui est ignoré par Git. L'historique structuré utilise SQLite et des JSON. Les fichiers sources et le texte OCR brut ne sont pas conservés par défaut (`DOCIA_STORE_SOURCE_FILES=false`, `DOCIA_STORE_RAW_TEXT=false`).

## Authentification

Quand `DOCIA_AUTH_ENABLED=false`, l'application est directement accessible. Quand elle est activée, le backend exige un mot de passe configuré et un secret JWT explicite. Les routes métier utilisent le bearer token; `/api/meta` reste public mais ne révèle que les informations nécessaires au démarrage du frontend.

## Moteurs disponibles

- Local : prétraitement, Docling, fallback PaddleOCR, puis Qwen via Ollama.
- OCR : Tesseract/EasyOCR sans LLM.
- Gemini : traitement serveur avec `GEMINI_API_KEY` dans `.env`.

La disponibilité affichée est détectée au runtime. Aucune précision ou performance fictive n'est présentée.
