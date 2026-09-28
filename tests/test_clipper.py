from pathlib import Path

import pytest

from clipper.config import ConfigError, Facecam, charger_config
from clipper.db import Base
from clipper.montage import commande_ffmpeg, filtre_video
from clipper.rapport import calculer_rapport, formater_rapport
from clipper.sous_titres import mots_vers_srt
from clipper.tiktok import MIN_CHUNK, plan_morceaux, url_autorisation
from clipper.twitch import normaliser_clip

CONFIG = """
streamers:
  - login: Alice
    accord: true
    remuneration_par_1000_vues: 2
    facecam: {x: 0, y: 0, largeur: 480, hauteur: 270}
  - login: bob
    accord: false
montage:
  disposition: facecam
"""


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(CONFIG + f"dossier_donnees: {tmp_path / 'data'}\n")
    return charger_config(p)


def test_config_ne_garde_que_les_streamers_avec_accord(cfg):
    assert [s.login for s in cfg.streamers_autorises()] == ["alice"]
    assert cfg.streamer("ALICE").facecam == Facecam(0, 0, 480, 270)


def test_config_disposition_invalide(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("montage: {disposition: nimporte}\n")
    with pytest.raises(ConfigError):
        charger_config(p)


def test_db_cycle_clip(cfg):
    db = Base(cfg.dossier_donnees / "t.db")
    clip = normaliser_clip(
        {"id": "abc", "url": "https://clips.twitch.tv/abc", "title": " Gros clutch ", "view_count": 900, "duration": 28.5},
        "Alice",
    )
    assert db.ajouter_clip(clip) is True
    assert db.ajouter_clip({**clip, "vues_twitch": 1200}) is False
    assert db.clip("abc")["vues_twitch"] == 1200
    db.maj_clip("abc", statut="publie", vues_tiktok=5000)
    assert [c["id"] for c in db.clips(statut="publie", streamer="alice")] == ["abc"]
    with pytest.raises(ValueError):
        db.maj_clip("abc", statut="nimporte")


def test_db_comptes(cfg):
    db = Base(cfg.dossier_donnees / "t.db")
    jeton = {"access_token": "a", "refresh_token": "r", "expires_in": 86400, "refresh_expires_in": 100, "open_id": "o1"}
    db.enregistrer_compte("principal", jeton, pseudo="moi")
    db.enregistrer_compte("principal", {**jeton, "access_token": "b"})
    c = db.compte("principal")
    assert (c["access_token"], c["pseudo"], c["open_id"]) == ("b", "moi", "o1")
    assert db.supprimer_compte("principal") and db.compte("principal") is None


def test_filtre_flou():
    f = filtre_video("flou")
    assert "boxblur" in f and f.endswith("[v]")


def test_filtre_facecam_et_sous_titres():
    f = filtre_video("facecam", Facecam(10, 20, 480, 270), Path("/tmp/a b:c.srt"))
    assert "vstack=inputs=2" in f
    assert "crop=iw*480/1920:ih*270/1080:iw*10/1920:ih*20/1080" in f
    assert "subtitles='/tmp/a b\\:c.srt'" in f


def test_filtre_facecam_sans_zone():
    from clipper.montage import MontageError

    with pytest.raises(MontageError):
        filtre_video("facecam")


def test_commande_ffmpeg():
    cmd = commande_ffmpeg("ffmpeg", Path("in.mp4"), Path("out.mp4"), duree_max=45)
    assert cmd[cmd.index("-t") + 1] == "45"
    assert cmd[-1] == "out.mp4" and "0:a?" in cmd


def test_plan_morceaux():
    assert plan_morceaux(1000) == (1000, 1)
    chunk, total = plan_morceaux(MIN_CHUNK * 5 + 123)
    assert chunk == 10 * 1024 * 1024 and total == 2  # le dernier morceau absorbe le reste


def test_url_autorisation():
    url = url_autorisation("key", "http://localhost:8765/callback", "xyz")
    assert "client_key=key" in url and "video.publish" in url and "state=xyz" in url


def test_srt():
    srt = mots_vers_srt([(0.0, 0.4, " Oh"), (0.4, 0.9, " non"), (1.0, 1.5, " quoi"), (1.5, 2.0, " ?"), (61.2, 62.0, " gg")])
    assert "00:00:00,000 --> 00:00:02,000\nOH NON QUOI ?" in srt
    assert "2\n00:01:01,200 --> 00:01:02,000\nGG" in srt


def test_rapport(cfg):
    clips = [
        {"streamer": "alice", "vues_tiktok": 12000},
        {"streamer": "alice", "vues_tiktok": 3000},
        {"streamer": "bob", "vues_tiktok": 999},
    ]
    lignes = calculer_rapport(cfg, clips)
    assert lignes[0] == {"streamer": "alice", "videos": 2, "vues": 15000, "montant": 30.0}
    assert lignes[1]["montant"] == 0.0
    assert "TOTAL" in formater_rapport(lignes)
