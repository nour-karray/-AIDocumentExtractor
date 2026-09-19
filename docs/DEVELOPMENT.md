# Développement

## Installation

```powershell
python -m pip install -r requirements-dev.txt
cd frontend
corepack pnpm install --frozen-lockfile
```

La configuration locale part de `.env.example`. N'ajoutez jamais de secret, document réel, base SQLite, poids de modèle ou sortie générée au dépôt.

## Validation

```powershell
python -m ruff check backend src pipelines scripts tests
python -m pytest -q
python -m compileall -q backend src pipelines scripts
cd frontend
corepack pnpm run lint
corepack pnpm run build
```

Les fixtures doivent être synthétiques. Toute route métier doit réutiliser la configuration centralisée, l'authentification, les limites d'upload et les contrôles de confidentialité existants.

Utilisez des commits ciblés (`fix:`, `refactor:`, `test:`, `docs:`). Le lockfile pnpm est la source de vérité du frontend.
