# Brancher le backend sans toucher au frontend

Le principe : `Kloyya-prototype.html` et `index.html` restent **intouchés**.
Tout le câblage réseau vit dans des fichiers additionnels, chargés en plus.

## 1. Ajouter deux scripts, sans éditer les fichiers existants

Dans une copie de déploiement (pas le fichier source du repo design), juste
avant `</body>` :

```html
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script>
  window.supabase = window.supabase.createClient(
    "https://xxxxx.supabase.co",
    "VOTRE_SUPABASE_ANON_KEY"
  );
  window.KLOYYA_API_BASE = "https://api.kloyya.com"; // ou http://localhost:8000 en dev
</script>
<script src="/frontend-bridge/api-client.js"></script>
<script src="/frontend-bridge/kloyya-wire.js"></script>
```

Si votre outillage de build interdit même ça, servez ces trois lignes comme
un petit fichier séparé injecté par votre CDN/edge (Cloudflare Worker,
Vercel Edge Middleware) plutôt que de modifier le HTML source du repo.

## 2. `kloyya-wire.js` — le seul fichier qui touche le DOM du prototype

Ce fichier (à écrire lors de l'intégration réelle, pas fourni ici car il
dépend des `id`/`class` exacts du prototype que je n'ai pas modifiés) doit :

- lire le texte de la hero ask box / composer → `KloyyaAPI.createOutcome(title)`
- sur "Choose plan" → `KloyyaAPI.subscribe(tierId, cadence)`
- sur l'écran "New outcome" → gérer le cycle
  `createOutcome` → `clarifyOutcome` (si une question revient) → `getPlan`
- sur "Plan review" → `updatePlan` quand l'utilisateur supprime/édite une étape
- sur "Live run" → `streamOutcome(outcomeId, { onStep, onLog, onProgress, onFinding, onState, onDone })`
  et mapper chaque event sur les éléments d'UI déjà présents (barre de
  progression, log pane colorée par `tag`, carte de finding)
- sur "Outcome delivered" → `getOutcomeDetail(outcomeId)` pour peupler
  answer/rows/citations/artifacts
- sur "Connections" → `listConnections`, `authorizeConnection`,
  `updateConnectionScopes`, `revokeConnection`
- sur "Onboarding" → `getPersonaConfig(persona)` pour remplacer les listes
  `ROLES`/`GOALS`/`RECO` codées en dur dans le prototype par la version
  serveur (voir `app/routers/onboarding.py::PERSONA_CONFIG` — à remplir
  avec le contenu verbatim du prototype, cf. `scripts/seed_persona_config.py`)

## 3. Ce que le backend NE remplace PAS

- Toute la logique de rendu, l'arithmétique tier/prix (`monthly × 12 × 0.9`)
  reste dans le prototype pour l'affichage instantané, mais le calcul qui
  compte (celui qui facture) est recalculé serveur dans
  `app/routers/billing.py::yearly_price_cents` — ne jamais faire confiance
  à un prix envoyé par le client.
- L'animation de waveform vocale reste simulée côté client ; seul le texte
  transcrit vient du serveur (`KloyyaAPI.transcribe`).

## 4. Auth

Le login/signup du prototype (boutons, formulaires) doit appeler
`supabase.auth.signUp(...)` / `supabase.auth.signInWithPassword(...)` /
`supabase.auth.signInWithOAuth({ provider: 'google' })` directement — ce
sont des appels au SDK Supabase, pas à notre API. Une fois la session
Supabase active, `api-client.js` s'en sert automatiquement pour authentifier
tous les appels vers `app.kloyya.com`.

Après signup, appelez immédiatement `POST /api/onboarding/provision-workspace`
(inclus dans `app/routers/onboarding.py`) — il crée le workspace + la ligne
`users` liée au `supabase_auth_id`. Sans cet appel, tout endpoint protégé
répond 403 (aucun workspace résolu pour ce compte). Il est idempotent :
l'appeler plusieurs fois ne crée pas de doublon.