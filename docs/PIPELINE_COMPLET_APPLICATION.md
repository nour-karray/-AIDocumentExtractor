# Pipeline complet de l'application DocuAI

## 1. Definition

Un pipeline est une suite d'etapes organisees qui transforme une entree en sortie.

Dans ce projet:

```text
Document image/PDF
  -> traitement
  -> OCR ou IA
  -> extraction des champs
  -> JSON final
```

## 2. Pipeline global de l'application

```text
1. Utilisateur
   ↓
2. Interface Web Next.js
   ↓
3. Upload du document image/PDF
   ↓
4. Backend FastAPI recoit le fichier
   ↓
5. Detection du type de document
   ↓
6. Pretraitement du document
   ↓
7. Choix de la methode d'extraction
   ↓
8. Extraction des donnees
   ↓
9. Normalisation JSON
   ↓
10. Validation qualite
   ↓
11. Sauvegarde historique
   ↓
12. Affichage du resultat dans l'interface
```

## 3. Schema detaille

```text
Document image/PDF
   ↓
Frontend Next.js
   ↓
Backend FastAPI
   ↓
Document Router
   ↓
Detection :
   - facture STEG
   - analyse medicale
   - ticket de caisse
   - facture fournisseur
   - document inconnu
   ↓
Pretraitement :
   - correction orientation
   - redimensionnement
   - amelioration contraste
   - deskew
   - nettoyage image
   ↓
Methode choisie :
   ├── OCR local classique
   │      ↓
   │   Tesseract OCR
   │      ↓
   │   Regles specialisees
   │      ↓
   │   JSON
   │
   ├── Pipeline IA local
   │      ↓
   │   Docling
   │      ↓
   │   PaddleOCR / Tesseract fallback
   │      ↓
   │   Qwen local via Ollama
   │      ↓
   │   JSON
   │
   └── Gemini API
          ↓
       Gemini 2.5 Flash
          ↓
       JSON
   ↓
Validation :
   - champs obligatoires
   - champs manquants
   - format des montants
   - format des dates
   - score qualite
   - warnings
   ↓
Sauvegarde :
   - JSON dans Data/history/extractions
   - historique SQLite dans Data/history/extractions.db
   ↓
Affichage :
   - resultat
   - score
   - champs extraits
   - erreurs
   - export rapport
```

## 4. Les trois pipelines d'extraction

### 4.1 Pipeline OCR local

```text
Document
  -> Pretraitement
  -> Tesseract OCR
  -> Regles specialisees
  -> JSON
```

Ce pipeline fonctionne sans internet et sans API externe.

Il est recommande pour:

```text
Factures STEG
Analyses medicales
```

### 4.2 Pipeline IA local

```text
Document
  -> Pretraitement
  -> Docling
  -> PaddleOCR ou Tesseract fallback
  -> Qwen local via Ollama
  -> JSON
```

Ce pipeline utilise les composants locaux:

```text
Docling
PaddleOCR
Qwen2.5 via Ollama
```

Il est recommande pour:

```text
PDF propres
Factures fournisseurs
Tickets de caisse si Gemini n'est pas disponible
Documents generiques
```

### 4.3 Pipeline Gemini API

```text
Document
  -> Gemini API
  -> JSON
  -> Validation
```

Ce pipeline utilise:

```text
Gemini 2.5 Flash
```

Il necessite une cle API:

```env
GEMINI_API_KEY=ta_cle_api
```

Il est recommande pour:

```text
Tickets de caisse
Factures fournisseurs complexes
Images difficiles
```

## 5. Exemple facture STEG

```text
STEG4.jpg
   ↓
Detection : steg_invoice
   ↓
Pretraitement image
   ↓
OCR local Tesseract
   ↓
Lecture des zones :
   - reference
   - montant
   - date limite paiement
   ↓
JSON final
```

Exemple de resultat:

```json
{
  "document_type": "steg_invoice",
  "reference": "747268800",
  "montant_a_payer": "645,000",
  "date_limite_paiement": "2024-08-28"
}
```

## 6. Exemple analyse medicale

```text
analyse4.jpg
   ↓
Detection : medical_lab_report
   ↓
Pretraitement image
   ↓
OCR local
   ↓
Extraction :
   - nom patient
   - numero dossier
   - dates
   - analyses
   - valeurs
   - unites
   ↓
JSON final
```

## 7. Sauvegarde des resultats

Les resultats generes sont sauvegardes ici:

```text
Data/history/extractions
```

La base SQLite est ici:

```text
Data/history/extractions.db
```

Les rapports de test sont ici:

```text
outputs/qa_validation
```

## 8. Resume tres simple

```text
Upload document
   ↓
Detecter le type
   ↓
Ameliorer l'image
   ↓
Lire le texte ou utiliser IA
   ↓
Extraire les champs
   ↓
Creer JSON
   ↓
Verifier qualite
   ↓
Sauvegarder
   ↓
Afficher resultat
```

