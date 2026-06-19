# Rapport de choix des modeles et evaluation des pipelines

Date: 2026-06-08

## 1. Objectif du rapport

Ce rapport explique comment choisir le meilleur pipeline d'extraction pour le projet DocuAI.

L'idee n'est pas de choisir un modele seulement parce qu'il est connu ou plus puissant. Le choix doit etre base sur des mesures:

- accuracy;
- precision;
- recall;
- F1-score;
- taux de JSON valide;
- taux de champs manquants;
- temps de traitement;
- cout;
- confidentialite;
- stabilite locale.

La demarche correcte est:

```text
1. Construire une baseline OCR local.
2. Mesurer ses performances.
3. Tester les autres pipelines sur les memes documents.
4. Comparer les metriques.
5. Choisir le meilleur pipeline par type de document.
```

## 2. Pipelines compares

Le projet compare trois grandes familles de methodes.

| Pipeline | Composants | Role |
| --- | --- | --- |
| OCR local classique | Tesseract + regles metier | Baseline rapide, locale, sans API. |
| Pipeline IA local | Docling + PaddleOCR + Tesseract fallback + Qwen2.5 via Ollama | Extraction locale plus intelligente vers JSON. |
| Gemini API | Gemini 2.5 Flash | Modele externe puissant pour documents complexes. |

Le modele local actuellement configure est:

```text
qwen2.5:7b-instruct
```

Le modele Gemini configure est:

```text
gemini-2.5-flash
```

## 3. Pourquoi commencer par OCR local

OCR local est utilise comme baseline parce qu'il est:

- gratuit;
- rapide;
- executable sans internet;
- plus facile a expliquer;
- suffisant pour certains documents bien structures comme STEG et analyses medicales.

La baseline sert de point de comparaison.

Exemple:

```text
Si OCR local obtient F1 = 0.92 sur STEG
et Gemini obtient F1 = 0.94 mais coute plus cher,
alors OCR local peut rester le meilleur choix pour STEG.
```

Donc le meilleur modele n'est pas toujours le plus grand modele. C'est le modele qui donne le meilleur compromis entre qualite, cout, temps et stabilite.

## 4. Donnees de test utilisees

Les documents de test sont dans:

```text
Data/raw_Data
```

Details:

```text
Data/raw_Data/electricite        factures STEG
Data/raw_Data/medical            analyses medicales
Data/raw_Data/analyse_medical    analyses medicales supplementaires
Data/raw_Data/ticketsCasse       tickets de caisse
```

Factures fournisseurs:

```text
Data/history/extractions/supplier_invoice
```

Datasets et annotations pour entrainement/evaluation:

```text
Data/finetuning
Data/finetuning/processed/ground_truth
Data/finetuning/llamafactory/train.jsonl
Data/finetuning/llamafactory/val.jsonl
Data/finetuning/llamafactory/test.jsonl
```

Important: pour calculer Accuracy/F1 correctement, il faut un fichier de verite terrain pour chaque document teste. La verite terrain est le JSON corrige manuellement.

Exemple:

```json
{
  "document_type": "steg_invoice",
  "reference": "747268800",
  "montant_a_payer": "645,000",
  "date_limite_paiement": "2024-08-28"
}
```

## 5. Niveaux d'evaluation

L'evaluation se fait a plusieurs niveaux.

### 5.1 Detection du type de document

On verifie si le systeme reconnait correctement le type du document.

Exemples:

```text
STEG4.jpg doit etre detecte comme steg_invoice
analyse4.jpg doit etre detecte comme medical_lab_report
ticket ZARA doit etre detecte comme receipt
facture fournisseur doit etre detectee comme supplier_invoice
```

Formule:

```text
Detection Accuracy = nombre de documents bien classes / nombre total de documents
```

Exemple:

```text
4 documents bien classes sur 4
Detection Accuracy = 4 / 4 = 1.00 = 100%
```

### 5.2 Validite JSON

Un modele peut extraire du texte mais retourner un JSON invalide. Cela doit etre penalise.

Formule:

```text
Valid JSON Rate = nombre de JSON valides / nombre total de sorties
```

Exemple:

```text
18 sorties JSON valides sur 20
Valid JSON Rate = 18 / 20 = 0.90 = 90%
```

### 5.3 Extraction des champs

On compare chaque champ predit avec la verite terrain.

Exemple STEG:

| Champ | Verite terrain | Prediction | Resultat |
| --- | --- | --- | --- |
| reference | 747268800 | 747268800 | correct |
| montant_a_payer | 645,000 | 645,000 | correct |
| date_limite_paiement | 2024-08-28 | 2024-10-03 | incorrect |

Ici:

```text
TP = 2
FP = 1
FN = 1
```

Pourquoi FP et FN pour le champ incorrect?

- FP: le systeme a propose une mauvaise valeur;
- FN: la bonne valeur attendue n'a pas ete trouvee.

Formules:

```text
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1-score  = 2 * Precision * Recall / (Precision + Recall)
```

Exemple:

```text
Precision = 2 / (2 + 1) = 0.667
Recall    = 2 / (2 + 1) = 0.667
F1-score  = 0.667
```

### 5.4 Accuracy par champ

Pour un champ donne, on peut calculer:

```text
Field Accuracy = nombre de predictions correctes pour ce champ / nombre de documents ou ce champ est attendu
```

Exemple pour `montant_a_payer` sur 10 factures STEG:

```text
9 montants corrects / 10 factures
Accuracy montant = 9 / 10 = 0.90 = 90%
```

### 5.5 Champs critiques

Tous les champs n'ont pas la meme importance.

Pour STEG, les champs critiques sont:

```text
reference
montant_a_payer
date_limite_paiement
```

Pour analyse medicale:

```text
patient_name
dossier_number
tests.raw_test_name
tests.value
tests.unit
```

Pour ticket de caisse:

```text
store_name
ticket_number
date
items
total
```

Pour facture fournisseur:

```text
invoice_number
seller.name
seller.tax_id
items
summary.total_amount
```

On calcule donc une accuracy specifique sur les champs critiques:

```text
Critical Field Accuracy = champs critiques corrects / champs critiques attendus
```

## 6. Evaluation OCR brut

Si on possede le texte correct du document, on peut evaluer l'OCR avant l'extraction JSON.

### 6.1 CER

CER signifie Character Error Rate.

```text
CER = distance d'edition caracteres / nombre de caracteres dans le texte correct
```

Exemple:

```text
Texte correct : 747268800
OCR predit    : 147268800
Erreur        : 1 caractere
CER           = 1 / 9 = 0.111 = 11.1%
```

### 6.2 WER

WER signifie Word Error Rate.

```text
WER = distance d'edition mots / nombre de mots dans le texte correct
```

Ces mesures servent a savoir si le probleme vient de l'OCR ou de l'extracteur JSON.

## 7. Score global de selection

Pour choisir le meilleur pipeline, on peut utiliser un score pondere.

Proposition de score:

```text
Score final =
  0.40 * Field F1
+ 0.20 * Critical Field Accuracy
+ 0.15 * Valid JSON Rate
+ 0.10 * Detection Accuracy
+ 0.10 * Latency Score
+ 0.05 * Cost/Privacy Score
```

Les poids peuvent etre adaptes selon le besoin. Dans ce projet, la qualite des champs est prioritaire.

### 7.1 Latency Score

Le temps est transforme en score entre 0 et 1.

Exemple simple:

```text
Latency Score = min(1, temps_reference / temps_mesure)
```

Si le temps de reference est 30 secondes:

```text
Pipeline A = 15 secondes
Latency Score = min(1, 30 / 15) = 1.00

Pipeline B = 90 secondes
Latency Score = min(1, 30 / 90) = 0.33
```

### 7.2 Cost/Privacy Score

Proposition:

| Methode | Cost/Privacy Score | Justification |
| --- | --- | --- |
| OCR local | 1.00 | Gratuit, local, pas de fuite de donnees. |
| Pipeline IA local | 0.90 | Local, mais plus lourd en ressources. |
| Gemini API | 0.60 | Tres performant mais externe et payant selon usage. |

## 8. Exemple de calcul complet

Supposons 20 documents STEG.

| Pipeline | Field F1 | Critical Accuracy | Valid JSON | Detection | Latency | Cost/Privacy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| OCR local | 0.92 | 0.95 | 1.00 | 1.00 | 1.00 | 1.00 |
| Docling+Qwen | 0.88 | 0.90 | 0.95 | 1.00 | 0.45 | 0.90 |
| Gemini | 0.96 | 0.97 | 1.00 | 1.00 | 0.70 | 0.60 |

Calcul OCR local:

```text
Score =
0.40*0.92 + 0.20*0.95 + 0.15*1.00 + 0.10*1.00 + 0.10*1.00 + 0.05*1.00

Score =
0.368 + 0.190 + 0.150 + 0.100 + 0.100 + 0.050

Score = 0.958
```

Calcul Gemini:

```text
Score =
0.40*0.96 + 0.20*0.97 + 0.15*1.00 + 0.10*1.00 + 0.10*0.70 + 0.05*0.60

Score =
0.384 + 0.194 + 0.150 + 0.100 + 0.070 + 0.030

Score = 0.928
```

Conclusion de cet exemple:

```text
Meme si Gemini est plus precis, OCR local peut etre choisi pour STEG,
car il est plus rapide, local et gratuit.
```

## 9. Matrice de choix finale par type de document

La decision doit se faire par famille de document.

| Type document | Choix recommande | Raison |
| --- | --- | --- |
| STEG | OCR local specialise | Tres bon sur champs fixes, rapide, local, gratuit. |
| Analyse medicale | OCR local specialise | Extraction structuree des lignes d'analyse. |
| Ticket de caisse | Gemini si cle disponible, sinon pipeline IA local | Structure variable, articles difficiles a extraire avec regles fixes. |
| Facture fournisseur | Gemini si cle disponible, sinon pipeline IA local | Champs variables, fournisseur/client/taxes/articles. |
| PDF texte propre | Docling + Qwen local | Docling conserve la structure et Qwen genere JSON. |
| Image tres degradee | Comparer Gemini et OCR local | Depend de la qualite visuelle. |

## 10. Etat actuel des tests du projet

Les tests QA sont dans:

```text
scripts/qa_validate_extractions.py
```

Les rapports sont generes ici:

```text
outputs/qa_validation
```

Etat verifie:

| Element | Etat actuel |
| --- | --- |
| Backend | OK |
| Frontend | OK |
| Detection automatique | OK sur les cas testes |
| OCR STEG | OK sur le cas teste |
| OCR medical | OK sur le cas teste |
| Gemini | Non teste live car cle API absente |
| Qwen local via Ollama | Installe, mais lent sur certains tests |
| Fine-tuning Qwen | Dataset present, modele fine-tune non applique |

## 11. Comment remplir le tableau experimental

Pour un rapport PFE, il faut creer un tableau comme ceci.

| Document | Type | Pipeline | JSON valide | Champs attendus | Champs corrects | TP | FP | FN | Precision | Recall | F1 | Temps sec |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| STEG4.jpg | STEG | OCR local | 1 | 3 | 3 | 3 | 0 | 0 | 1.00 | 1.00 | 1.00 | 25 |
| analyse4.jpg | Medical | OCR local | 1 | 8 | 7 | 7 | 1 | 1 | 0.875 | 0.875 | 0.875 | 40 |
| ticket_zara.jpg | Receipt | Qwen local | 0 | 4 | 0 | 0 | 0 | 4 | 0.00 | 0.00 | 0.00 | timeout |

Puis on regroupe par pipeline:

| Pipeline | Documents testes | Detection Accuracy | Valid JSON Rate | Field F1 moyen | Critical Accuracy | Temps moyen | Score final |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| OCR local | a remplir | a remplir | a remplir | a remplir | a remplir | a remplir | a remplir |
| Docling+PaddleOCR+Qwen | a remplir | a remplir | a remplir | a remplir | a remplir | a remplir | a remplir |
| Gemini API | a remplir | a remplir | a remplir | a remplir | a remplir | a remplir | a remplir |

## 12. Conclusion methodologique

Le choix du modele dans ce projet doit etre justifie comme suit:

1. OCR local est la baseline.
2. On calcule accuracy, precision, recall et F1 sur les champs extraits.
3. On ajoute des metriques pratiques: JSON valide, temps, cout, confidentialite.
4. On compare Docling+PaddleOCR+Qwen et Gemini sur les memes documents.
5. On choisit le meilleur pipeline par type de document, pas forcement un seul modele pour tout.

Conclusion actuelle:

```text
Pour STEG et analyses medicales, OCR local specialise est le meilleur choix actuel.
Pour tickets de caisse et factures fournisseurs, il faut comparer Gemini et Qwen local,
mais Gemini necessite une cle API et Qwen local doit etre optimise car il peut etre lent.
```

