"""Téléchargement des clips Twitch avec yt-dlp."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


class TelechargementError(Exception):
    pass


def telecharger(url: str, dossier: Path, clip_id: str) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    cible = dossier / f"{clip_id}.mp4"
    if cible.exists() and cible.stat().st_size > 0:
        return cible

    commande = (
        ["yt-dlp"] if shutil.which("yt-dlp") else [sys.executable, "-m", "yt_dlp"]
    ) + ["--quiet", "--no-warnings", "-f", "best[ext=mp4]/best", "-o", str(cible), url]
    res = subprocess.run(commande, capture_output=True, text=True)
    if res.returncode != 0 or not cible.exists():
        raise TelechargementError(f"yt-dlp a échoué pour {url} : {res.stderr.strip()[-500:]}")
    return cible
