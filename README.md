# Clipper — clips Twitch → TikTok

Outil en ligne de commande qui :

1. **cherche** les clips les plus vus des streamers avec qui tu as un accord (API officielle Twitch) ;
2. les **télécharge** et les **monte** en vertical 9:16 (fond flouté ou facecam + jeu), avec sous-titres automatiques en option ;
3. les **publie** sur TikTok via l'API officielle (Content Posting API), sur un ou plusieurs comptes reliés ;
4. **suit les vues** et calcule ce que chaque streamer te doit (rémunération aux 1000 vues).

> ⚠️ Règles intégrées volontairement :
> - seuls les streamers marqués `accord: true` sont traités (clipper sans autorisation = violation de droits d'auteur) ;
> - les comptes TikTok ne sont **pas créés** par l'outil : tu relies des comptes existants via la connexion officielle TikTok ;
> - chaque publication est confirmée à la main (sauf `--oui`), et la mention « contenu sponsorisé » est activée par défaut puisque tu es payé par le streamer.

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install faster-whisper      # optionnel : sous-titres automatiques
# ffmpeg est requis : apt install ffmpeg  /  brew install ffmpeg
python -m clipper init          # crée config.yaml et .env
```

### Clés API

- **Twitch** : crée une application sur <https://dev.twitch.tv/console/apps> → `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` dans `.env`.
- **TikTok** : crée une application sur <https://developers.tiktok.com/>, ajoute les produits *Login Kit* et *Content Posting API*,
  les scopes `user.info.basic`, `video.publish`, `video.list`, et la redirect URI `http://localhost:8765/callback`.
  Renseigne `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET` dans `.env`.
  Tant que l'app n'est pas **auditée** par TikTok, les vidéos ne peuvent être publiées qu'en privé (`SELF_ONLY`).
  Demande l'audit depuis le portail développeur pour publier en public.

## Utilisation

```bash
python -m clipper streamers          # vérifier la config
python -m clipper connecter principal   # relier ton compte TikTok (ouvre le navigateur)
python -m clipper auto               # chercher + télécharger + monter
python -m clipper liste              # voir les clips et leur statut
python -m clipper ignorer <id>       # écarter un clip nul
python -m clipper publier --max 3    # publier (avec confirmation)
python -m clipper suivre             # état des publications + vues TikTok
python -m clipper rapport            # vues et montant à facturer par streamer
```

Autres commandes : `chercher`, `telecharger`, `monter [--disposition facecam] [--sans-sous-titres]`, `comptes`, `deconnecter <nom>`.

### Plusieurs comptes

Chaque streamer a un `compte_tiktok` dans `config.yaml`. Relie chaque compte avec
`python -m clipper connecter <nom>` (ton compte, ou celui d'un streamer qui te donne l'accès en se connectant lui-même).

### Disposition « facecam »

Indique la zone de la webcam du streamer dans une image 1920x1080 :

```yaml
facecam: {x: 1440, y: 0, largeur: 480, hauteur: 270}
```

La facecam est placée en haut (1080x640) et le jeu en bas (1080x1280).

## Données

Tout est stocké dans `data/` : `clipper.db` (SQLite : clips, comptes, jetons), `bruts/`, `montes/`, `sous_titres/`.
Les jetons TikTok sont dans la base : ne partage pas ce dossier.

## Tests

```bash
pip install pytest && python -m pytest
```
