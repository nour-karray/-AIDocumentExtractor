# Evaluation professionnelle des pipelines IA de DocuAI

Date: 2026-06-09

Ce document sert de base propre pour presenter le projet devant un jury ou des professionnels IA. Il se limite aux elements mesurables dans le projet et evite les chiffres inventes.

## 1. Positionnement honnete

Dans DocuAI, on ne compare pas seulement des modeles. On compare des pipelines complets:

| Pipeline | Composants | Role dans l'application |
| --- | --- | --- |
| OCR local classique | OpenCV + Tesseract + regles specialisees | Baseline locale, rapide et explicable. |
| IA locale hybride | Docling + controle qualite + PaddleOCR fallback + Qwen2.5 via Ollama | Extraction locale structuree sans API cloud. |
| Gemini API | Gemini Vision / Gemini 2.5 Flash | Extraction cloud robuste sur documents complexes. |

Phrase a utiliser:

> L'evaluation porte sur la sortie finale JSON de chaque pipeline, car c'est cette sortie qui est consommee par l'application. Le texte OCR brut est une etape intermediaire, pas l'objectif final.

## 2. Donnees disponibles dans le projet

Le projet contient actuellement un dataset prepare pour l'evaluation et le fine-tuning:

```text
Data/finetuning/splits/train.jsonl
Data/finetuning/splits/validation.jsonl
Data/finetuning/splits/test.jsonl
Data/finetuning/processed/ground_truth
```

Etat actuel des splits:

| Split | Nombre |
| --- | ---: |
| Train | 839 |
| Validation | 178 |
| Test | 182 |
| Total | 1199 |

Repartition du dataset annote:

| Famille | Nombre total | Test |
| --- | ---: | ---: |
| Medical | 226 | 35 |
| Receipt / ticket | 973 | 147 |

Important:

- Les metriques statistiques solides peuvent etre calculees sur les familles qui ont une verite terrain exploitable.
- Actuellement, le dataset annote solide couvre surtout `medical` et `receipt`.
- STEG et factures fournisseurs existent dans l'application, mais il faut encore un lot de ground truth verifie manuellement pour produire un F1 statistique defensable.

## 3. Metriques utilisees

### 3.1 Detection du type de document

Objectif: verifier que le routeur classe correctement le document.

```text
Detection Accuracy = documents bien classes / documents testes
```

Test fonctionnel reel execute le 2026-06-09:

```text
python scripts/qa_validate_extractions.py --cases detect_steg4 detect_medical_analyse4 detect_receipt_zara detect_supplier_ar
```

Resultat:

```text
4/4 cas OK
Accuracy de detection sur ce smoke test = 100%
```

Interpretation correcte:

> Ce resultat confirme que le routeur fonctionne sur un echantillon controle couvrant STEG, medical, ticket et facture fournisseur. Ce n'est pas une performance globale statistique; pour cela, il faut un benchmark plus large annote manuellement.

### 3.2 Extraction des champs

Pour chaque document, on compare le JSON predit avec le JSON de verite terrain.

Definitions:

```text
TP = champ attendu extrait correctement
FP = champ extrait mais faux ou hallucine
FN = champ attendu absent ou incorrect
```

Formules:

```text
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1-score  = 2 * Precision * Recall / (Precision + Recall)
```

Regle importante:

- Si un champ est faux, on compte generalement `FP + FN`.
- Pourquoi? Le modele a produit une mauvaise valeur, et la bonne valeur attendue n'a pas ete retrouvee.

### 3.3 Field Accuracy

```text
Field Accuracy = champs attendus corrects / champs attendus totaux
```

Cette metrique est intuitive pour un jury, car elle repond a la question:

> Sur les champs importants attendus, combien sont corrects?

### 3.4 Valid JSON Rate

```text
Valid JSON Rate = sorties JSON valides / sorties produites
```

Cette metrique est importante pour les LLM:

- un modele peut comprendre le document;
- mais s'il retourne un JSON invalide, l'application ne peut pas exploiter la sortie proprement.

### 3.5 Temps moyen

Pour comparer professionnellement, il faut aussi mesurer:

```text
Temps moyen par document
Taux de timeout
Cout API
Execution locale ou cloud
Confidentialite
```

## 4. Outil d'evaluation ajoute au projet

Un script d'evaluation quantitative a ete ajoute:

```text
scripts/evaluate_extraction_metrics.py
```

Il produit:

```text
outputs/evaluation_metrics/<run_id>/summary.json
outputs/evaluation_metrics/<run_id>/per_document.csv
outputs/evaluation_metrics/<run_id>/report.md
```

Commande de base:

```powershell
python scripts\evaluate_extraction_metrics.py
```

Cette commande verifie le split de test et cree un rapport de methode. Sur l'etat actuel du projet, elle detecte:

```text
Test split: 182 documents
Medical: 35
Receipt: 147
```

Pour evaluer un pipeline, il faut placer ses predictions JSON dans:

```text
outputs/evaluation_metrics/predictions/<nom_pipeline>/
```

Exemples:

```text
outputs/evaluation_metrics/predictions/ocr_local/
outputs/evaluation_metrics/predictions/docling_qwen/
outputs/evaluation_metrics/predictions/gemini/
```

Puis lancer:

```powershell
python scripts\evaluate_extraction_metrics.py --predictions-root outputs\evaluation_metrics\predictions
```

## 5. Comment produire des predictions comparables

Pour que la comparaison soit non conflictuelle:

1. Utiliser exactement les memes documents pour chaque pipeline.
2. Ne jamais evaluer sur les documents utilises pour regler les prompts ou les regles.
3. Garder un split `test` gele.
4. Sauvegarder les predictions sans correction humaine.
5. Comparer automatiquement avec `ground_truth`.

Organisation conseillee:

```text
outputs/evaluation_metrics/predictions/
  ocr_local/
    medical_synth_0054.json
    sroie_train_X51006335314.json
  docling_qwen/
    medical_synth_0054.json
    sroie_train_X51006335314.json
  gemini/
    medical_synth_0054.json
    sroie_train_X51006335314.json
```

Chaque fichier doit contenir le JSON predit par le pipeline.

## 6. Tableau a presenter aux professionnels IA

Tant que toutes les predictions ne sont pas generees, il faut presenter le tableau comme protocole de benchmark, pas comme resultat final.

| Pipeline | Detection Accuracy | Field Accuracy | Precision | Recall | F1 | Temps moyen | Confidentialite | Statut |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| OCR local | A mesurer | A mesurer | A mesurer | A mesurer | A mesurer | A mesurer | Locale | Baseline |
| Docling + PaddleOCR + Qwen2.5 | A mesurer | A mesurer | A mesurer | A mesurer | A mesurer | A mesurer | Locale | Pipeline principal local |
| Gemini Vision | A mesurer | A mesurer | A mesurer | A mesurer | A mesurer | A mesurer | Cloud/API | Reference externe |

Resultat deja mesure:

| Test | Documents | Resultat |
| --- | ---: | ---: |
| Detection multi-familles controlee | 4 | 4/4 OK |

## 7. Decision technique defendable

La decision ne doit pas etre "Gemini est meilleur" ou "Qwen est meilleur" sans contexte. La decision correcte est par type de document:

| Type de document | Pipeline recommande | Justification |
| --- | --- | --- |
| STEG | OCR local specialise ou Gemini si image difficile | Structure relativement fixe; OCR local est explicable et rapide. |
| Medical | OCR local structure + IA si besoin | Les champs sont critiques; validation metier obligatoire. |
| Tickets | Gemini ou pipeline local IA | Mise en page tres variable; OCR seul est souvent insuffisant. |
| Factures fournisseurs | Gemini ou Docling + Qwen | Documents heterogenes; besoin de comprehension structurelle. |

Phrase professionnelle:

> Le systeme adopte une strategie hybride: OCR local pour les cas stables et explicables, pipeline IA local pour reduire la dependance cloud, et Gemini comme reference externe pour les documents les plus variables.

## 8. Limites a reconnaitre

Il faut reconnaitre ces limites clairement:

- Le F1 global n'est pas encore defensable sur STEG et factures fournisseurs sans plus de ground truth valide.
- Les donnees medicales synthetiques permettent de tester la structure, mais elles ne remplacent pas un benchmark clinique reel anonymise.
- Gemini depend de la cle API, du quota, du reseau et de la politique de confidentialite.
- Qwen2.5 local n'est pas encore fine-tune dans la version actuelle.
- Le temps de traitement local depend fortement du CPU/GPU et de l'etat d'Ollama.

## 9. Ce qu'il faut dire pendant la presentation

Version courte:

> Nous avons compare les pipelines au niveau applicatif, pas seulement au niveau modele. Chaque pipeline produit un JSON normalise. L'evaluation compare ce JSON avec une verite terrain champ par champ. Les metriques retenues sont detection accuracy, valid JSON rate, field accuracy, precision, recall et F1-score. Le projet contient deja un split de test de 182 documents annote pour medical et tickets, et un script automatise calcule les metriques lorsque les predictions des pipelines sont fournies.

Version plus technique:

> Pour eviter une comparaison biaisee, les memes documents sont envoyes a chaque pipeline. Les valeurs extraites sont normalisees avant comparaison: dates, montants, texte et lignes medicales. Une valeur incorrecte est comptee comme FP + FN, car elle remplace une valeur attendue correcte par une valeur erronee. Cette evaluation separe aussi la classification du type documentaire, la validite JSON et la qualite des champs extraits.

## 10. Ce qu'il ne faut pas dire

Eviter:

```text
Gemini a 95% d'accuracy.
Qwen est meilleur que Gemini.
Docling est un modele OCR.
Le fine-tuning est deja termine.
Le F1 est globalement valide sur toutes les familles.
```

Dire plutot:

```text
Gemini sert de reference cloud sur les documents complexes.
Qwen2.5 est utilise localement via Ollama dans un pipeline Docling/PaddleOCR.
Docling est un convertisseur documentaire vers une representation structuree.
Le fine-tuning Qwen est prepare via un dataset train/validation/test.
Les metriques sont calculees sur les familles qui disposent d'une verite terrain exploitable.
```

