# Sécurité

- Les secrets restent dans `.env`; aucune clé n'est acceptée ni stockée par le frontend.
- L'authentification activée exige un mot de passe/hash et un secret JWT explicite.
- Les origines CORS, tailles de fichier, tailles de lot, nombre de fichiers, MIME et extensions sont bornés côté serveur.
- Les paramètres de retry sont bornés et l'adresse Ollama n'est jamais fournie par le client.
- Les traitements longs utilisent un processus terminable afin d'empêcher toute persistance tardive après timeout.
- `/api/meta` ne publie ni chemins locaux, ni hôte Ollama, ni emplacement du `.env`.

Avant publication, exécutez Ruff, pytest, la compilation Python, le lint TypeScript, le build Next.js et un scan de secrets. Si un secret a été exposé, révoquez-le même après purge de l'historique.

Signalez une vulnérabilité de manière privée au propriétaire du dépôt; n'incluez jamais de document réel dans le rapport.
