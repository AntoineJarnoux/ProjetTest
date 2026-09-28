"""Chargement de la configuration (config.yaml + variables d'environnement)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(Exception):
    pass


@dataclass
class Facecam:
    x: int
    y: int
    largeur: int
    hauteur: int


@dataclass
class Streamer:
    login: str
    accord: bool = False
    compte_tiktok: str = "principal"
    remuneration_par_1000_vues: float = 0.0
    facecam: Facecam | None = None


@dataclass
class Config:
    streamers: list[Streamer]
    jours: int = 7
    max_par_streamer: int = 5
    vues_minimum: int = 0
    disposition: str = "flou"
    duree_max: int = 60
    sous_titres: bool = False
    modele_whisper: str = "small"
    langue: str = "fr"
    confidentialite: str = "SELF_ONLY"
    contenu_sponsorise: bool = True
    credit: str = "🎥 Clip de @{streamer} sur Twitch"
    hashtags: list[str] = field(default_factory=list)
    dossier_donnees: Path = Path("data")

    def streamers_autorises(self) -> list[Streamer]:
        return [s for s in self.streamers if s.accord]

    def streamer(self, login: str) -> Streamer | None:
        login = login.lower()
        return next((s for s in self.streamers if s.login.lower() == login), None)


def charger_env(chemin: Path = Path(".env")) -> None:
    """Charge un fichier .env simple (CLE=valeur) sans écraser l'environnement existant."""
    if not chemin.exists():
        return
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, valeur = ligne.split("=", 1)
        os.environ.setdefault(cle.strip(), valeur.strip().strip('"').strip("'"))


def secret(nom: str) -> str:
    valeur = os.environ.get(nom)
    if not valeur:
        raise ConfigError(f"Variable d'environnement manquante : {nom} (voir .env.example)")
    return valeur


def charger_config(chemin: Path) -> Config:
    if not chemin.exists():
        raise ConfigError(f"{chemin} introuvable. Copie config.example.yaml en {chemin}.")
    brut = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}

    streamers = []
    for s in brut.get("streamers") or []:
        if "login" not in s:
            raise ConfigError("Chaque streamer doit avoir un `login`.")
        fc = s.get("facecam")
        streamers.append(
            Streamer(
                login=str(s["login"]).lower(),
                accord=bool(s.get("accord", False)),
                compte_tiktok=str(s.get("compte_tiktok", "principal")),
                remuneration_par_1000_vues=float(s.get("remuneration_par_1000_vues", 0)),
                facecam=Facecam(**fc) if fc else None,
            )
        )

    recherche = brut.get("recherche") or {}
    montage = brut.get("montage") or {}
    publication = brut.get("publication") or {}

    disposition = montage.get("disposition", "flou")
    if disposition not in ("flou", "facecam"):
        raise ConfigError("montage.disposition doit valoir `flou` ou `facecam`.")

    return Config(
        streamers=streamers,
        jours=int(recherche.get("jours", 7)),
        max_par_streamer=int(recherche.get("max_par_streamer", 5)),
        vues_minimum=int(recherche.get("vues_minimum", 0)),
        disposition=disposition,
        duree_max=int(montage.get("duree_max", 60)),
        sous_titres=bool(montage.get("sous_titres", False)),
        modele_whisper=str(montage.get("modele_whisper", "small")),
        langue=str(montage.get("langue", "fr")),
        confidentialite=str(publication.get("confidentialite", "SELF_ONLY")),
        contenu_sponsorise=bool(publication.get("contenu_sponsorise", True)),
        credit=str(publication.get("credit", "🎥 Clip de @{streamer} sur Twitch")),
        hashtags=list(publication.get("hashtags") or []),
        dossier_donnees=Path(brut.get("dossier_donnees", "data")),
    )
