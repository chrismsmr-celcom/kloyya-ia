"""
Rappel d'intégration : les listes ROLES / GOALS / RECO par persona vivent
dans le prototype (`Kloyya-prototype.html`, classe logique JS) et doivent
être copiées verbatim dans app/routers/onboarding.py::PERSONA_CONFIG —
spec landing §5 : "lift them verbatim as the seed data".

Ce script n'écrit rien en base : PERSONA_CONFIG est servi directement par
l'API (source de vérité versionnée en code, comme demandé). Il documente
juste la procédure pour ne pas l'oublier au moment de brancher le vrai
contenu du prototype.
"""

print(
    "1. Ouvrir Kloyya-prototype.html, chercher les constantes ROLES / GOALS / RECO.\n"
    "2. Copier leur contenu tel quel dans app/routers/onboarding.py::PERSONA_CONFIG.\n"
    "3. Ne pas reformuler le texte — c'est celui déjà validé par le design/prototype."
)