"""Sous-titres automatiques (optionnel, via faster-whisper)."""

from __future__ import annotations

from pathlib import Path

# Nombre de mots max par ligne affichée : style TikTok, court et lisible
MOTS_PAR_LIGNE = 4


def _horodatage(secondes: float) -> str:
    ms = int(round(secondes * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def mots_vers_srt(mots: list[tuple[float, float, str]], mots_par_ligne: int = MOTS_PAR_LIGNE) -> str:
    """Regroupe des mots horodatés (début, fin, texte) en blocs SRT courts."""
    blocs = []
    for i in range(0, len(mots), mots_par_ligne):
        groupe = mots[i : i + mots_par_ligne]
        texte = " ".join(m[2].strip() for m in groupe).strip()
        if not texte:
            continue
        blocs.append(
            f"{len(blocs) + 1}\n{_horodatage(groupe[0][0])} --> {_horodatage(groupe[-1][1])}\n{texte.upper()}\n"
        )
    return "\n".join(blocs)


def disponible() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def generer_srt(video: Path, sortie: Path, modele: str = "small", langue: str = "fr") -> Path:
    from faster_whisper import WhisperModel

    m = WhisperModel(modele, device="auto", compute_type="int8")
    segments, _ = m.transcribe(str(video), language=langue, word_timestamps=True, vad_filter=True)
    mots = [(w.start, w.end, w.word) for seg in segments for w in (seg.words or [])]
    sortie.write_text(mots_vers_srt(mots), encoding="utf-8")
    return sortie
