"""Interface en ligne de commande : python -m clipper <commande>."""

from __future__ import annotations

import argparse
import shutil
import sys
import time
import webbrowser
from pathlib import Path

from clipper import montage, sous_titres, telechargement
from clipper.config import Config, ConfigError, charger_config, charger_env, secret
from clipper.db import Base
from clipper.rapport import calculer_rapport, formater_rapport
from clipper.tiktok import TikTok, TikTokError, attendre_code, nouveau_state, url_autorisation
from clipper.twitch import Twitch, TwitchError, normaliser_clip

RACINE = Path(__file__).resolve().parent.parent


def _ctx(args) -> tuple[Config, Base]:
    cfg = charger_config(Path(args.config))
    return cfg, Base(cfg.dossier_donnees / "clipper.db")


def _tiktok() -> TikTok:
    return TikTok(secret("TIKTOK_CLIENT_KEY"), secret("TIKTOK_CLIENT_SECRET"))


def _jeton_valide(db: Base, tt: TikTok, nom: str) -> str:
    compte = db.compte(nom)
    if compte is None:
        raise ConfigError(f"Compte TikTok `{nom}` non connecté. Lance : python -m clipper connecter {nom}")
    if compte["expire_le"] > time.time() + 300:
        return compte["access_token"]
    if compte["refresh_expire_le"] < time.time():
        raise ConfigError(f"La connexion du compte `{nom}` a expiré. Relance : python -m clipper connecter {nom}")
    jeton = tt.rafraichir(compte["refresh_token"])
    db.enregistrer_compte(nom, jeton)
    return jeton["access_token"]


def legende(cfg: Config, clip) -> str:
    credit = cfg.credit.format(streamer=clip["streamer"])
    return " ".join(p for p in (clip["titre"], "—", credit, " ".join(cfg.hashtags)) if p).strip()


# --- Commandes ---------------------------------------------------------------


def cmd_init(args) -> int:
    for src, dst in (("config.example.yaml", "config.yaml"), (".env.example", ".env")):
        if Path(dst).exists():
            print(f"✔ {dst} existe déjà")
        else:
            shutil.copy(RACINE / src, dst)
            print(f"✔ {dst} créé — pense à le remplir")
    return 0


def cmd_streamers(args) -> int:
    cfg, _ = _ctx(args)
    for s in cfg.streamers:
        etat = "✔ accord" if s.accord else "✘ pas d'accord (ignoré)"
        print(f"{s.login:<24} {etat:<24} compte TikTok : {s.compte_tiktok:<12} {s.remuneration_par_1000_vues} €/1000 vues")
    return 0


def cmd_chercher(args) -> int:
    cfg, db = _ctx(args)
    autorises = cfg.streamers_autorises()
    for s in cfg.streamers:
        if not s.accord:
            print(f"⏭  {s.login} ignoré : pas d'accord renseigné (accord: false)")
    if not autorises:
        print("Aucun streamer avec `accord: true` dans la config.")
        return 1

    tw = Twitch(secret("TWITCH_CLIENT_ID"), secret("TWITCH_CLIENT_SECRET"))
    ids = tw.ids_utilisateurs([s.login for s in autorises])
    nouveaux = 0
    for s in autorises:
        if s.login not in ids:
            print(f"⚠  {s.login} introuvable sur Twitch")
            continue
        # On en demande plus que nécessaire pour pouvoir filtrer par vues
        bruts = tw.clips(ids[s.login], jours=cfg.jours, max_clips=cfg.max_par_streamer * 4)
        retenus = [c for c in bruts if c.get("view_count", 0) >= cfg.vues_minimum]
        retenus.sort(key=lambda c: c.get("view_count", 0), reverse=True)
        for brut in retenus[: cfg.max_par_streamer]:
            clip = normaliser_clip(brut, s.login)
            if db.ajouter_clip(clip):
                nouveaux += 1
                print(f"＋ [{s.login}] {clip['titre'][:60]} ({clip['vues_twitch']} vues)")
    print(f"{nouveaux} nouveau(x) clip(s).")
    return 0


def cmd_liste(args) -> int:
    _, db = _ctx(args)
    clips = db.clips(statut=args.statut, streamer=args.streamer)
    for c in clips:
        print(f"{c['id'][:28]:<28} {c['statut']:<11} {c['streamer']:<16} {c['vues_twitch']:>8} vues  {c['titre'][:50]}")
    if not clips:
        print("Aucun clip.")
    return 0


def cmd_ignorer(args) -> int:
    _, db = _ctx(args)
    db.maj_clip(args.id, statut="ignore")
    print(f"Clip {args.id} ignoré.")
    return 0


def cmd_telecharger(args) -> int:
    cfg, db = _ctx(args)
    clips = [db.clip(args.id)] if args.id else db.clips(statut="trouve")
    for c in filter(None, clips):
        try:
            chemin = telechargement.telecharger(c["url"], cfg.dossier_donnees / "bruts", c["id"])
            db.maj_clip(c["id"], statut="telecharge", fichier_brut=str(chemin), erreur=None)
            print(f"⬇  {c['id']} → {chemin}")
        except telechargement.TelechargementError as e:
            db.maj_clip(c["id"], statut="echec", erreur=str(e))
            print(f"✘ {c['id']} : {e}")
    return 0


def cmd_monter(args) -> int:
    cfg, db = _ctx(args)
    clips = [db.clip(args.id)] if args.id else db.clips(statut="telecharge")
    avec_st = cfg.sous_titres and not args.sans_sous_titres
    if avec_st and not sous_titres.disponible():
        print("ℹ  faster-whisper non installé : montage sans sous-titres (pip install faster-whisper)")
        avec_st = False

    for c in filter(None, clips):
        streamer = cfg.streamer(c["streamer"])
        brut = Path(c["fichier_brut"] or "")
        if not brut.exists():
            print(f"✘ {c['id']} : fichier brut absent, lance d'abord `telecharger`")
            continue
        disposition = args.disposition or cfg.disposition
        if disposition == "facecam" and (streamer is None or streamer.facecam is None):
            print(f"ℹ  {c['streamer']} n'a pas de zone facecam : disposition `flou` utilisée")
            disposition = "flou"
        try:
            srt = None
            if avec_st:
                dossier_st = cfg.dossier_donnees / "sous_titres"
                dossier_st.mkdir(parents=True, exist_ok=True)
                srt = sous_titres.generer_srt(brut, dossier_st / f"{c['id']}.srt", cfg.modele_whisper, cfg.langue)
            sortie = montage.monter(
                brut,
                cfg.dossier_donnees / "montes" / f"{c['id']}.mp4",
                disposition=disposition,
                duree_max=cfg.duree_max,
                facecam=streamer.facecam if streamer else None,
                srt=srt,
            )
            db.maj_clip(c["id"], statut="monte", fichier_monte=str(sortie), erreur=None)
            print(f"🎬 {c['id']} → {sortie}")
        except montage.MontageError as e:
            db.maj_clip(c["id"], statut="echec", erreur=str(e))
            print(f"✘ {c['id']} : {e}")
    return 0


def cmd_connecter(args) -> int:
    """Connecte un compte TikTok EXISTANT via la connexion officielle TikTok."""
    cfg, db = _ctx(args)
    tt = _tiktok()
    redirect = secret("TIKTOK_REDIRECT_URI")
    state = nouveau_state()
    url = url_autorisation(tt.client_key, redirect, state)
    print("Ouvre ce lien et connecte-toi avec le compte TikTok à relier :\n")
    print(url + "\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    code = attendre_code(redirect, state)
    jeton = tt.echanger_code(code, redirect)
    user = tt.infos_utilisateur(jeton["access_token"])
    db.enregistrer_compte(args.nom, jeton, open_id=user.get("open_id", ""), pseudo=user.get("display_name", ""))
    print(f"✔ Compte `{args.nom}` connecté ({user.get('display_name', '?')}).")
    return 0


def cmd_comptes(args) -> int:
    _, db = _ctx(args)
    comptes = db.comptes()
    for c in comptes:
        expire = "expirée" if c["refresh_expire_le"] < time.time() else "active"
        print(f"{c['nom']:<16} {c['pseudo'] or '?':<24} connexion {expire}")
    if not comptes:
        print("Aucun compte connecté. Lance : python -m clipper connecter <nom>")
    return 0


def cmd_deconnecter(args) -> int:
    _, db = _ctx(args)
    print("✔ Compte supprimé." if db.supprimer_compte(args.nom) else "Compte inconnu.")
    return 0


def cmd_publier(args) -> int:
    cfg, db = _ctx(args)
    tt = _tiktok()
    clips = [db.clip(args.id)] if args.id else db.clips(statut="monte")[: args.max]
    publies = 0
    for c in filter(None, clips):
        streamer = cfg.streamer(c["streamer"])
        if streamer is None or not streamer.accord:
            print(f"⏭  {c['id']} : pas d'accord avec {c['streamer']}, publication refusée")
            continue
        if not c["fichier_monte"] or not Path(c["fichier_monte"]).exists():
            print(f"✘ {c['id']} : pas encore monté")
            continue

        nom = streamer.compte_tiktok
        token = _jeton_valide(db, tt, nom)
        infos = tt.infos_createur(token)
        options = infos.get("privacy_level_options", [])
        confidentialite = args.confidentialite or cfg.confidentialite
        if options and confidentialite not in options:
            print(f"✘ Confidentialité `{confidentialite}` non autorisée pour ce compte. Choix possibles : {options}")
            return 1

        texte = legende(cfg, c)
        print(f"\nCompte : {infos.get('creator_nickname', nom)} (@{infos.get('creator_username', '?')})")
        print(f"Vidéo  : {c['fichier_monte']}")
        print(f"Légende : {texte}")
        print(f"Visibilité : {confidentialite} | Contenu sponsorisé : {'oui' if cfg.contenu_sponsorise else 'non'}")
        if not args.oui and input("Publier ? [o/N] ").strip().lower() not in ("o", "oui", "y"):
            print("Annulé.")
            continue
        try:
            publish_id = tt.publier_video(
                token, Path(c["fichier_monte"]), texte, confidentialite, cfg.contenu_sponsorise
            )
            db.maj_clip(c["id"], statut="en_attente", publish_id=publish_id, compte_tiktok=nom, erreur=None)
            publies += 1
            print(f"⬆  Envoyé (publish_id {publish_id}). Suis l'état avec : python -m clipper suivre")
        except TikTokError as e:
            db.maj_clip(c["id"], erreur=str(e))
            print(f"✘ {e}")
    print(f"{publies} vidéo(s) envoyée(s).")
    return 0


def cmd_suivre(args) -> int:
    """Met à jour l'état des publications et les vues TikTok."""
    cfg, db = _ctx(args)
    tt = _tiktok()
    for c in db.clips(statut="en_attente"):
        token = _jeton_valide(db, tt, c["compte_tiktok"])
        st = tt.statut_publication(token, c["publish_id"])
        statut = st.get("status")
        if statut == "PUBLISH_COMPLETE":
            ids = st.get("publicaly_available_post_id") or []
            db.maj_clip(c["id"], statut="publie", video_id=str(ids[0]) if ids else None)
            print(f"✔ {c['id']} publié")
        elif statut == "FAILED":
            db.maj_clip(c["id"], statut="echec", erreur=st.get("fail_reason", "inconnu"))
            print(f"✘ {c['id']} : {st.get('fail_reason')}")
        else:
            print(f"… {c['id']} : {statut}")

    par_compte: dict[str, list] = {}
    for c in db.clips(statut="publie"):
        if c["video_id"]:
            par_compte.setdefault(c["compte_tiktok"], []).append(c)
    for nom, clips in par_compte.items():
        token = _jeton_valide(db, tt, nom)
        vues = tt.stats_videos(token, [c["video_id"] for c in clips])
        for c in clips:
            if c["video_id"] in vues:
                db.maj_clip(c["id"], vues_tiktok=vues[c["video_id"]])
    print("Stats mises à jour.")
    return 0


def cmd_rapport(args) -> int:
    cfg, db = _ctx(args)
    print(formater_rapport(calculer_rapport(cfg, db.clips(statut="publie"))))
    return 0


def cmd_auto(args) -> int:
    """Chercher → télécharger → monter (la publication reste une étape validée à la main)."""
    for etape in (cmd_chercher, cmd_telecharger, cmd_monter):
        etape(argparse.Namespace(**{**vars(args), "id": None, "disposition": None, "sans_sous_titres": False}))
    print("\nClips prêts. Vérifie-les dans data/montes/ puis lance : python -m clipper publier")
    return 0


def construire_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clipper", description="Clips Twitch autorisés → montage vertical → TikTok")
    p.add_argument("--config", default="config.yaml")
    sub = p.add_subparsers(dest="commande", required=True)

    sub.add_parser("init", help="crée config.yaml et .env").set_defaults(fn=cmd_init)
    sub.add_parser("streamers", help="liste les streamers configurés").set_defaults(fn=cmd_streamers)
    sub.add_parser("chercher", help="récupère les meilleurs clips Twitch").set_defaults(fn=cmd_chercher)

    s = sub.add_parser("liste", help="liste les clips connus")
    s.add_argument("--statut")
    s.add_argument("--streamer")
    s.set_defaults(fn=cmd_liste)

    s = sub.add_parser("ignorer", help="écarte un clip")
    s.add_argument("id")
    s.set_defaults(fn=cmd_ignorer)

    s = sub.add_parser("telecharger", help="télécharge les clips trouvés")
    s.add_argument("--id")
    s.set_defaults(fn=cmd_telecharger)

    s = sub.add_parser("monter", help="monte les clips en 9:16")
    s.add_argument("--id")
    s.add_argument("--disposition", choices=["flou", "facecam"])
    s.add_argument("--sans-sous-titres", action="store_true")
    s.set_defaults(fn=cmd_monter)

    s = sub.add_parser("connecter", help="relie un compte TikTok existant (connexion officielle)")
    s.add_argument("nom", nargs="?", default="principal")
    s.set_defaults(fn=cmd_connecter)
    sub.add_parser("comptes", help="liste les comptes TikTok reliés").set_defaults(fn=cmd_comptes)
    s = sub.add_parser("deconnecter", help="oublie un compte TikTok")
    s.add_argument("nom")
    s.set_defaults(fn=cmd_deconnecter)

    s = sub.add_parser("publier", help="publie les clips montés sur TikTok")
    s.add_argument("--id")
    s.add_argument("--max", type=int, default=3)
    s.add_argument("--confidentialite")
    s.add_argument("--oui", action="store_true", help="ne pas demander de confirmation")
    s.set_defaults(fn=cmd_publier)

    sub.add_parser("suivre", help="met à jour l'état des publications et les vues").set_defaults(fn=cmd_suivre)
    sub.add_parser("rapport", help="vues et montant dû par streamer").set_defaults(fn=cmd_rapport)
    sub.add_parser("auto", help="chercher + télécharger + monter").set_defaults(fn=cmd_auto)
    return p


def main(argv: list[str] | None = None) -> int:
    charger_env()
    args = construire_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (ConfigError, TwitchError, TikTokError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
