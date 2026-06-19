# Plateforme intelligente d'extraction d'informations

Projet doctoral pour l'extraction automatique d'informations a partir de documents heterogenes (PDF, images scannees, factures, rapports, comptes rendus, etc.).

## Objectif

Construire une plateforme de bout en bout qui:
- collecte des documents non structures,
- applique un pretraitement adapte,
- execute l'OCR,
- extrait des entites/champs metier,
- stocke les resultats dans une base exploitable,
- fournit une visualisation analytique.

## Documentation et structure du code

- **Vue d’ensemble du dépôt (arborescence réelle, flux, SQLite, Streamlit)** : [`docs/DOCUMENTATION_PROJET.md`](docs/DOCUMENTATION_PROJET.md)
- **Architecture cible** (doctorat, non entièrement implémentée) : [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **Guide pédagogique** : [`docs/GUIDE_COMPLET.md`](docs/GUIDE_COMPLET.md)

En bref : `src/` (application), `pipelines/` (Gemini vision JSON), `data/history/` (JSON + `extractions.db` par défaut), `docs/`.

Voir aussi l'architecture locale hybride active : [`docs/ARCHITECTURE_LOCALE_HYBRIDE.md`](docs/ARCHITECTURE_LOCALE_HYBRIDE.md)

## Pipeline cible (v1)

1. Collecte des documents (dossier, upload, scanner, email).
2. Pretraitement (deskew, denoise, binarisation, detection de zones).
3. OCR (texte + position + confiance).
4. Extraction d'informations (champs facture, dates, montants, client, etc.).
5. Validation/qualite (scores, regles de coherence).
6. Stockage (base relationnelle + index recherche).
7. Visualisation (tableaux de bord, suivi qualite OCR/extraction).

## Prochaine etape recommandee

Commencer par un premier cas d'usage: **factures STEG** avec un schema simple:
- reference_facture
- date_facture
- nom_client
- adresse
- montant_ht
- montant_tva
- montant_ttc
- periode_consommation
- identifiant_compteur

Le fichier `docs/ARCHITECTURE.md` détaille l'architecture cible ; `docs/DOCUMENTATION_PROJET.md` décrit ce qui est réellement implémenté.

## Nouvelle interface web (Next.js + FastAPI)

Le projet contient maintenant une nouvelle interface admin moderne :
- `backend/` : API `FastAPI` qui reutilise les pipelines Python existants
- `frontend/` : interface `Next.js` multi-pages (dashboard, extractions, resultats, historiques, analyses, modeles, parametres)

### 1. Lancer le backend FastAPI

Depuis la racine du projet :

```bash
python -m pip install -r requirements.txt
uvicorn backend.app.main:app --reload
```

API disponible sur :
- `http://127.0.0.1:8000/api/health`
- ou via `.\run_api.ps1`

### Authentification API

Par defaut, l'authentification est desactivee pour garder le mode demo simple. Pour la rendre obligatoire sur les endpoints metier (`dashboard`, `history`, `extractions`, rapports, exports), ajoutez dans `.env` :

```env
DOCUAI_AUTH_ENABLED=true
DOCUAI_AUTH_USERNAME=admin
DOCUAI_AUTH_PASSWORD=change-me
DOCUAI_AUTH_TOKEN_SECRET=une-valeur-longue-et-secrete
DOCUAI_AUTH_TOKEN_TTL_MINUTES=480
```

Connexion :

```bash
curl -X POST http://127.0.0.1:8000/api/auth/login ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"admin\",\"password\":\"change-me\"}"
```

Puis appelez les endpoints proteges avec :

```bash
curl http://127.0.0.1:8000/api/dashboard -H "Authorization: Bearer <token>"
```

Pour eviter le mot de passe en clair, genere un hash :

```bash
python -c "from backend.app.auth import hash_password; print(hash_password('change-me'))"
```

et remplace `DOCUAI_AUTH_PASSWORD` par `DOCUAI_AUTH_PASSWORD_HASH`.

### 2. Lancer le frontend Next.js

Depuis `frontend/` :

```bash
npm install
npm run dev
```

Alternative si `npm` est endommage sur Windows :

```bash
corepack pnpm install
corepack pnpm dev
```

Interface disponible sur :
- `http://localhost:3000`
- ou via `.\run_frontend.ps1`

### 3. Pipeline IA local par defaut

```bash
PDF/image -> pretraitement -> Docling -> Markdown -> controle qualite -> PaddleOCR si besoin -> Qwen2.5 via Ollama -> JSON -> validation metier -> SQLite
```

Installer le modele local :

```bash
ollama pull qwen2.5:7b-instruct
```

PaddleOCR est utilise uniquement comme secours quand le Markdown Docling est trop faible.

### 4. Preparation fine-tuning Qwen2.5

Le dossier fine-tuning est separe du pipeline de production. Il sert a construire un dataset propre pour un futur LoRA Qwen:

```bash
powershell -ExecutionPolicy Bypass -File .\scripts\prepare_finetuning_sources.ps1
python .\scripts\prepare_finetuning_inputs.py
python .\scripts\build_finetuning_dataset.py
```

Sur ton Windows, si `python` n'est pas reconnu, utilise:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" .\scripts\prepare_finetuning_inputs.py
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" .\scripts\build_finetuning_dataset.py
```

Les fichiers finaux sont generes dans `Data/finetuning/splits/`. Le guide complet est ici: [`docs/FINE_TUNING_QWEN.md`](docs/FINE_TUNING_QWEN.md).

Le fine-tuning ne se lance pas pendant chaque extraction. Il sert a produire un modele specialise en amont. Ensuite l'application continue le meme flux `pretraitement -> Docling/PaddleOCR -> Qwen -> JSON`, mais avec le modele pret indique dans `OLLAMA_MODEL`.

Export optionnel pour LLaMA-Factory:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" .\scripts\export_llamafactory_dataset.py
```

### 5. Cle Gemini

Le meilleur emplacement reste le fichier `.env` a la racine du projet backend :

```env
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
```

La cle peut aussi etre saisie dans l'interface pour une session navigateur.

## Ancienne interface Streamlit (legacy)

Depuis la racine du projet:

```bash
python -m pip install -r requirements.txt
streamlit run src/web/app.py
```

Interface web:
- upload image/PDF d'analyse medicale,
- affichage des metadonnees,
- tableau des tests extraits,
- export JSON telechargeable.

### Gemini (comprehension du document)

1. Creer une cle API : [Google AI Studio](https://aistudio.google.com/apikey)
2. Copier `.env.example` vers `.env` et renseigner `GEMINI_API_KEY=...`
3. Dans l'app web, cocher **Utiliser Gemini** (ou laisser la cle dans `.env` uniquement)

Sans cle : l'application utilise uniquement l'OCR local (Tesseract).

## Lancer en CLI (sans interface)

```bash
python -m src.main --input "Data/raw_Data/medical/analyse1.jpg"
python -m src.main --input "Data/raw_Data/medical/analyse1.jpg" --output "data/output/analyse1.json"
python -m src.main --input "Data/raw_Data/medical/analyse1.jpg" --gemini --output "data/output/analyse1.json"
```
