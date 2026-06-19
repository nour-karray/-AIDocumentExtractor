# Fine-tuning Qwen2.5 pour DocuAI

Ce dossier de travail sert a preparer un dataset de fine-tuning local pour Qwen2.5. Il ne remplace pas le pipeline d'extraction de l'application. Il sert a entrainer plus tard un adaptateur LoRA pour que Qwen comprenne mieux tes documents: factures STEG, tickets, factures fournisseur et analyses medicales.

## Deux modes separes

Le fine-tuning ne se fait pas a chaque extraction. Le projet doit etre compris en deux modes.

### 1. Mode entrainement

Ce mode sert a creer ou ameliorer le modele specialise. Il se fait avant l'utilisation normale de l'application, puis il peut etre relance plus tard quand tu as assez de nouvelles corrections.

```text
Documents varies
  -> Docling / PaddleOCR
  -> Markdown ou texte OCR
  -> JSON correct valide humainement
  -> Dataset train / validation / test
  -> Fine-tuning LoRA de Qwen
  -> Qwen2.5 + adaptateur LoRA specialise
```

Cette phase peut prendre du temps. Elle demande des donnees corrigees et, idealement, une machine avec GPU.

### 2. Mode utilisation dans l'application

Quand un utilisateur importe un document, l'application ne fait pas de fine-tuning. Elle utilise seulement le modele deja pret.

```text
Nouveau document importe
  -> Pretraitement
  -> Docling ou PaddleOCR fallback
  -> Markdown ou texte OCR
  -> Qwen deja pret, base ou fine-tune
  -> JSON extrait
  -> Score de qualite
  -> Affichage / correction utilisateur
  -> Sauvegarde SQLite + JSON
```

Les corrections utilisateur peuvent ensuite enrichir le dataset et servir a un futur fine-tuning, par exemple chaque semaine, chaque mois, ou quand tu as assez de nouvelles corrections fiables.

Phrase simple pour le rapport:

> Le fine-tuning est une phase d'entrainement separee de l'utilisation normale de l'application. Il est realise avant le deploiement du systeme, a partir de documents annotes et de JSON corrects valides humainement. Une fois Qwen adapte avec LoRA, il est integre dans l'application et utilise directement lors de l'extraction des nouveaux documents. Pendant l'utilisation quotidienne, le systeme ne reentraine pas le modele a chaque document; il applique simplement le modele deja pret pour produire le JSON. Les corrections effectuees par les utilisateurs peuvent ensuite etre conservees pour enrichir le dataset et relancer un nouveau fine-tuning periodiquement.

## Structure utilisee

Dans ce projet, tous les fichiers sont regroupes ici:

```text
Data/finetuning/
  raw/
    kaggle/
    custom/
    generated/
  processed/
    inputs/
    ground_truth/
  manifests/
  splits/
    train.jsonl
    validation.jsonl
    test.jsonl
```

Les sources actuelles sont:

- `C:\Users\User\Desktop\pfaEXTRACT\SROIE2019` vers `Data/finetuning/raw/kaggle/receipt_sroie`
- `C:\Users\User\Desktop\pfaEXTRACT\lbmaske` vers `Data/finetuning/raw/kaggle/medical_lbmaske`
- `Data/raw_Data` vers `Data/finetuning/raw/custom`
- `C:\Users\User\Downloads\data genrer.zip` vers `Data/finetuning/raw/generated`

Important: seul SROIE2019 contient deja des annotations fiables. Les autres fichiers sont copies dans le dossier fine-tuning, mais ils restent dans le manifest `unlabeled_documents.jsonl` tant qu'un JSON correct n'a pas ete valide.

## Preparation des sources

Depuis la racine du projet:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prepare_finetuning_sources.ps1
```

Ce script copie les datasets dans `Data/finetuning/raw`, sans copier le modele lourd `layoutlm-base-uncased`.

## Creation des inputs et ground truth

```powershell
python .\scripts\prepare_finetuning_inputs.py
```

Sur ce poste Windows, si `python` n'est pas reconnu:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" .\scripts\prepare_finetuning_inputs.py
```

Ce script fait deux choses:

- convertit les annotations SROIE en paires `input .txt` + `ground_truth .json`;
- ajoute les autres documents dans `Data/finetuning/manifests/unlabeled_documents.jsonl` pour les annoter plus tard.

## Creation de train / validation / test

```powershell
python .\scripts\build_finetuning_dataset.py
```

Ou avec le chemin Python complet:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" .\scripts\build_finetuning_dataset.py
```

Sorties:

```text
Data/finetuning/splits/train.jsonl
Data/finetuning/splits/validation.jsonl
Data/finetuning/splits/test.jsonl
Data/finetuning/splits/stats.json
```

Chaque ligne JSONL suit ce format:

```json
{
  "instruction": "Extrais les informations importantes du document et retourne uniquement un JSON valide conforme au type du document.",
  "input": "[METHOD_USED=sroie_box_ocr]\n\n...",
  "output": {
    "document_type": "receipt",
    "store_name": "...",
    "date": "...",
    "total": "..."
  }
}
```

## Ajouter tes propres documents au fine-tuning

Important: ne pas entrainer Qwen directement avec un JSON produit automatiquement par
le systeme si ce JSON n'a pas ete corrige. Un mauvais JSON devient une mauvaise
lecon pour le modele.

### Cas STEG recommande

Les factures STEG locales sont dans:

```text
Data/raw_Data/electricite copy/
Data/finetuning/raw/custom/steg/
Data/finetuning/raw/generated/steg/
```

Pour creer une file de documents STEG a annoter:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" .\scripts\prepare_steg_annotation_pack.py --source "Data\raw_Data\electricite copy" --overwrite
```

Si PaddleOCR est lent sur Windows, limiter les timeouts:

```powershell
$env:LOCAL_PIPELINE_PADDLEOCR_TIMEOUT_SECONDS="3"
$env:LOCAL_PIPELINE_FAST_OCR_TIMEOUT_SECONDS="5"
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" .\scripts\prepare_steg_annotation_pack.py --source "Data\raw_Data\electricite copy" --overwrite
```

Le script cree:

```text
Data/finetuning/processed/inputs/steg/*.txt
Data/finetuning/annotation_drafts/steg/*.json
Data/finetuning/manifests/steg_annotation_review_queue.jsonl
```

Workflow d'annotation:

1. ouvrir une image source, par exemple `Data/raw_Data/electricite copy/STEG4.jpg`;
2. ouvrir son brouillon dans `Data/finetuning/annotation_drafts/steg/`;
3. corriger le bloc `ground_truth`;
4. mettre `"verified": true`;
5. relancer:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" .\scripts\prepare_steg_annotation_pack.py --promote-verified
```

Le JSON verifie est alors cree dans:

```text
Data/finetuning/processed/ground_truth/steg/
```

Ensuite seulement, relancer:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" .\scripts\build_finetuning_dataset.py
```

Champs STEG a verifier en priorite:

```json
{
  "document_type": "steg_invoice",
  "reference": "",
  "numero_compteur": "",
  "date_facture": "",
  "montant_a_payer": "",
  "date_limite_paiement": "",
  "periode_du": "",
  "periode_au": "",
  "coupon_reference_raw": "",
  "coupon_montant": "",
  "confidence_note": "high"
}
```

### Methode manuelle generale

Pour utiliser les images STEG, medicales ou tickets deja copiees:

1. ouvrir `Data/finetuning/manifests/unlabeled_documents.jsonl`;
2. choisir un document;
3. produire son texte avec ton pipeline Docling/PaddleOCR ou le corriger manuellement;
4. mettre le texte dans `Data/finetuning/processed/inputs/<type>/<id>.txt`;
5. mettre le JSON correct dans `Data/finetuning/processed/ground_truth/<type>/<id>.json`;
6. relancer `python .\scripts\build_finetuning_dataset.py`.

Ne pas creer de faux JSON pour gonfler les scores. Pour entrainer proprement, chaque `ground_truth` doit etre une correction reelle.

Par defaut, `prepare_finetuning_inputs.py` n'utilise plus les sorties historiques
comme verite terrain sauf si elles contiennent `finetuning_verified: true`.
Pour forcer l'ancien comportement, utiliser `--include-unverified-history`, mais
ce n'est pas recommande pour STEG.

## Lancer un LoRA Qwen2.5

Deux options existent:

- `scripts/train_qwen_lora.py`: script local minimal base sur Transformers/PEFT, utile pour prototyper;
- `LLaMA-Factory`: option recommandee pour un vrai entrainement LoRA/QLoRA plus simple a configurer et a suivre.

Installer les dependances optionnelles:

```powershell
python -m pip install -r requirements-finetuning.txt
```

Puis lancer:

```powershell
python .\scripts\train_qwen_lora.py --model-name Qwen/Qwen2.5-7B-Instruct
```

Avec le chemin Python complet:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" .\scripts\train_qwen_lora.py --model-name Qwen/Qwen2.5-7B-Instruct
```

Le resultat sera sauvegarde dans:

```text
models/qwen2_5_docuai_lora/
```

Cette etape est lourde. Elle demande beaucoup de RAM/VRAM et peut etre lente sur CPU. Pour le projet actuel, la preparation `train.jsonl / validation.jsonl / test.jsonl` est l'etape a montrer comme base solide du fine-tuning.

## Export compatible LLaMA-Factory

Le dataset interne `instruction/input/output` peut etre converti au format conversationnel attendu par LLaMA-Factory:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" .\scripts\export_llamafactory_dataset.py
```

Sorties:

```text
Data/finetuning/llamafactory/train.jsonl
Data/finetuning/llamafactory/val.jsonl
Data/finetuning/llamafactory/test.jsonl
Data/finetuning/llamafactory/dataset_info.json
```

Exemple de ligne:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Extrais les informations importantes...\n\nDocument:\n..."
    },
    {
      "role": "assistant",
      "content": "{\"document_type\":\"receipt\",\"total\":\"150.00\"}"
    }
  ]
}
```

Dans LLaMA-Factory, l'idee est de configurer un entrainement `sft` avec `finetuning_type: lora`, `template: qwen`, et `model_name_or_path: Qwen/Qwen2.5-7B-Instruct`.

## Integration dans l'application

L'application appelle Ollama avec la variable `OLLAMA_MODEL`. Aujourd'hui, si tu utilises:

```env
OLLAMA_MODEL=qwen2.5:7b-instruct
```

elle utilise le Qwen de base. Apres entrainement LoRA et integration du modele adapte dans Ollama, tu remplaces simplement cette valeur par le nom du modele specialise, par exemple:

```env
OLLAMA_MODEL=docuai-qwen2.5-lora:latest
```

Le pipeline applicatif reste identique. Seul le modele appele change.
