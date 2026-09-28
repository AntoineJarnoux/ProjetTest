"""Montage vertical 9:16 pour TikTok avec ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from clipper.config import Facecam

LARGEUR, HAUTEUR = 1080, 1920
# Disposition "facecam" : facecam en haut, jeu en bas
HAUTEUR_CAM = 640
HAUTEUR_JEU = HAUTEUR - HAUTEUR_CAM

STYLE_SOUS_TITRES = (
    "FontName=Arial,FontSize=14,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
    "BorderStyle=1,Outline=3,Shadow=0,Alignment=2,MarginV=90"
)


class MontageError(Exception):
    pass


def trouver_ffmpeg() -> str:
    chemin = shutil.which("ffmpeg")
    if chemin:
        return chemin
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as e:
        raise MontageError("ffmpeg introuvable : installe-le (apt install ffmpeg / brew install ffmpeg).") from e


def _echapper_chemin_filtre(chemin: Path) -> str:
    """Échappe un chemin pour l'utiliser dans un filtre ffmpeg (subtitles=...)."""
    s = str(chemin).replace("\\", "/")
    for c in (":", "'", ",", "[", "]", ";"):
        s = s.replace(c, "\\" + c)
    return s


def filtre_video(disposition: str, facecam: Facecam | None = None, srt: Path | None = None) -> str:
    """Construit le filter_complex ffmpeg. La sortie vidéo s'appelle [v]."""
    if disposition == "flou":
        f = (
            f"[0:v]scale={LARGEUR}:{HAUTEUR}:force_original_aspect_ratio=increase,"
            f"crop={LARGEUR}:{HAUTEUR},boxblur=20:5[fond];"
            f"[0:v]scale={LARGEUR}:-2[avant];"
            f"[fond][avant]overlay=(W-w)/2:(H-h)/2"
        )
    elif disposition == "facecam":
        if facecam is None:
            raise MontageError("La disposition `facecam` nécessite la zone `facecam` du streamer dans config.yaml.")
        # Coordonnées données pour du 1920x1080, mises à l'échelle de la vidéo réelle
        cam = (
            f"crop=iw*{facecam.largeur}/1920:ih*{facecam.hauteur}/1080:"
            f"iw*{facecam.x}/1920:ih*{facecam.y}/1080"
        )
        f = (
            f"[0:v]{cam},scale={LARGEUR}:{HAUTEUR_CAM}:force_original_aspect_ratio=increase,"
            f"crop={LARGEUR}:{HAUTEUR_CAM}[cam];"
            f"[0:v]crop='trunc(ih*{LARGEUR}/{HAUTEUR_JEU}/2)*2':ih,scale={LARGEUR}:{HAUTEUR_JEU}[jeu];"
            f"[cam][jeu]vstack=inputs=2"
        )
    else:
        raise MontageError(f"Disposition inconnue : {disposition}")

    if srt is not None:
        f += f",subtitles='{_echapper_chemin_filtre(srt)}':force_style='{STYLE_SOUS_TITRES}'"
    return f + ",setsar=1,fps=30,format=yuv420p[v]"


def commande_ffmpeg(
    ffmpeg: str,
    entree: Path,
    sortie: Path,
    disposition: str = "flou",
    duree_max: int = 60,
    facecam: Facecam | None = None,
    srt: Path | None = None,
) -> list[str]:
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(entree),
        "-t", str(duree_max),
        "-filter_complex", filtre_video(disposition, facecam, srt),
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
        "-movflags", "+faststart",
        str(sortie),
    ]


def monter(
    entree: Path,
    sortie: Path,
    disposition: str = "flou",
    duree_max: int = 60,
    facecam: Facecam | None = None,
    srt: Path | None = None,
) -> Path:
    sortie.parent.mkdir(parents=True, exist_ok=True)
    cmd = commande_ffmpeg(trouver_ffmpeg(), entree, sortie, disposition, duree_max, facecam, srt)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise MontageError(f"ffmpeg a échoué : {res.stderr.strip()[-800:]}")
    return sortie
