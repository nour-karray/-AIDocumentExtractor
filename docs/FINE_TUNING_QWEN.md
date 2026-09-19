# Fine-tuning Qwen2.5 pour DocIA

Le fine-tuning est un workflow expérimental séparé de l'API de production. Aucun document utilisateur et aucune annotation de dataset ne sont utilisés comme raccourci pendant une extraction runtime.

## Préparer les données

Placez les datasets autorisés sous `data/finetuning/raw/`. Ce répertoire est ignoré par Git. Utilisez uniquement des documents synthétiques, publics ou traités avec une base légale appropriée.

```powershell
python scripts/prepare_finetuning_inputs.py
python scripts/build_finetuning_dataset.py
```

Les sorties sont créées sous `data/finetuning/processed/`, `data/finetuning/manifests/` et `data/finetuning/splits/`. Une paire ne doit entrer dans l'entraînement que si son JSON de référence a été vérifié humainement. Les sorties automatiques non vérifiées ne constituent pas une vérité terrain.

SROIE peut être utilisé uniquement par les scripts dataset/évaluation. Il n'intervient jamais dans `process_single_document()` ni dans l'API.

## Entraîner un adaptateur LoRA

Installez les dépendances optionnelles, idéalement dans un environnement GPU isolé :

```powershell
python -m pip install -r requirements-finetuning.txt
python scripts/train_qwen_lora.py --model-name Qwen/Qwen2.5-7B-Instruct
```

La sortie par défaut est `models/qwen2_5_docia_lora/`, également ignorée par Git.

## Export LLaMA-Factory

```powershell
python scripts/export_llamafactory_dataset.py
```

L'export conversationnel est généré sous `data/finetuning/llamafactory/`. Configurez ensuite un entraînement SFT LoRA avec le template Qwen.

## Intégration

Après conversion et installation du modèle dans Ollama, définissez son nom uniquement côté backend :

```env
OLLAMA_MODEL=docia-qwen2.5-lora:latest
```

Le pipeline applicatif reste inchangé. Ne publiez jamais les datasets, poids, adaptateurs ou sorties contenant des données personnelles.
