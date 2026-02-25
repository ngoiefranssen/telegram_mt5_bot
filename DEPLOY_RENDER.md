#  Déploiement du Bot sur Render

Ce guide explique comment déployer le bot de trading Telegram sur Render.

##  Prérequis

- Compte Render (gratuit)
- Compte Deriv avec API token
- Compte Telegram

## frxXAGUSD Étape 1: Générer la session Telegram

**Sur votre machine locale**, exécutez:

```bash
python generate_session_string.py
```

Suivez les instructions:
1. Entrez votre numéro de téléphone
2. Entrez le code de vérification reçu
3. **Copiez la session string générée** (longue chaîne de caractères)

## Étape 2: Créer le service sur Render

1. Allez sur https://render.com
2. Cliquez sur **"New +"** → **"Web Service"**
3. Connectez votre dépôt GitHub
4. Configurez:
   - **Name**: `telegram-mt5-bot` (ou votre choix)
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot_vps_gram_mt.py`
   - **Instance Type**: `Free` (suffisant pour ce bot)

## Étape 3: Configurer les variables d'environnement

Dans l'onglet **"Environment"** de votre service Render, ajoutez:

| Key | Value | Description |
|-----|-------|-------------|
| `TELEGRAM_API_ID` | `33159970` | Votre API ID Telegram |
| `TELEGRAM_API_HASH` | `33f09424ad95a65f1961d1e6ca2a0de2` | Votre API Hash Telegram |
| `TELEGRAM_SESSION` | `[session string copiée]` | Session générée à l'étape 1 |
| `CHANNEL_USERNAME` | `hunto4x_fullaccourcy92` | Canal Telegram à écouter |
| `DERIV_API_TOKEN` | `[votre token]` | Votre token API Deriv |
| `DERIV_APP_ID` | `128123` | Votre App ID Deriv |
| `FIXED_LOT` | `0.02` | Taille du lot (stake) |
| `PORT` | `10000` | Port HTTP (requis par Render) |

 **Important**: 
- Ne partagez JAMAIS ces valeurs publiquement!
- **ARRÊTEZ le bot localement** avant de déployer sur Render (sinon erreur AuthKeyDuplicated)

##  Étape 4: Déployer

1. Cliquez sur **"Create Web Service"**
2. Render va automatiquement:
   - Cloner votre dépôt
   - Installer les dépendances
   - Lancer le bot

## Étape 5: Vérifier les logs

1. Allez dans l'onglet **"Logs"** de votre service
2. Vous devriez voir:
   ```
    [Deriv API] Connecté
    Balance: 9981.6 USD
    [Telegram] Connecté en tant que [Votre nom]
    Canal cible: 𝗛𝘂𝗻𝘁𝗼 𝗧𝗿𝗮𝗱𝗲𝗿
    BOT EN ÉCOUTE...
   ```

## Le bot est maintenant actif!

Le bot va:
- Écouter le canal Telegram 24/7
- Détecter automatiquement les signaux
- Exécuter les trades sur Deriv
- Logger toutes les activités

## Mise à jour du bot

Pour mettre à jour le bot:
1. Poussez vos changements sur GitHub
2. Render redéploiera automatiquement

## Dépannage

### Le bot demande un code de vérification
→ Vous n'avez pas configuré `TELEGRAM_SESSION` correctement. Relancez l'étape 1.

### Erreur "AuthKeyDuplicatedError"
→ **Le bot tourne localement ET sur Render en même temps**. Arrêtez le bot local avec Ctrl+C avant de déployer sur Render.

### Erreur "Invalid API token"
→ Vérifiez que `DERIV_API_TOKEN` est correct sur https://app.deriv.com/account/api-token

### Le bot ne détecte pas les signaux
→ Vérifiez que `CHANNEL_USERNAME` est correct et que vous êtes membre du canal

### Erreur "Port scan timeout"
→ Assurez-vous d'avoir ajouté la variable `PORT=10000` dans les variables d'environnement

## Notes

- Le plan gratuit de Render peut avoir des limitations (sleep après inactivité)
- Pour un bot 24/7 sans interruption, considérez le plan payant
- Les logs sont conservés pendant 7 jours sur le plan gratuit
