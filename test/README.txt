Dataset synthetique au format historique DocuAI.

Structure generee:
- test/Data/history/extractions/<kind>/<timestamp>_<nom>.json
- test/Data/history/extractions/<kind>/<timestamp>_<nom>.jpg
- test/Data/history/extractions.db

Les JSON reprennent le meme principe que Data/history/extractions: payload en racine + bloc _meta.
Les donnees sont nouvelles et synthetiques: elles ne sont pas copiees depuis l'historique reel.
