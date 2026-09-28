"""Stockage SQLite : clips, comptes TikTok connectés."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    streamer TEXT NOT NULL,
    titre TEXT NOT NULL,
    url TEXT NOT NULL,
    vues_twitch INTEGER NOT NULL DEFAULT 0,
    duree REAL NOT NULL DEFAULT 0,
    cree_le TEXT,
    statut TEXT NOT NULL DEFAULT 'trouve',
    fichier_brut TEXT,
    fichier_monte TEXT,
    compte_tiktok TEXT,
    publish_id TEXT,
    video_id TEXT,
    vues_tiktok INTEGER NOT NULL DEFAULT 0,
    erreur TEXT,
    maj_le REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS comptes (
    nom TEXT PRIMARY KEY,
    open_id TEXT,
    pseudo TEXT,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expire_le REAL NOT NULL,
    refresh_expire_le REAL NOT NULL,
    scopes TEXT
);
"""

# Cycle de vie d'un clip
STATUTS = ("trouve", "telecharge", "monte", "en_attente", "publie", "echec", "ignore")


class Base:
    def __init__(self, chemin: Path):
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(chemin)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # --- clips ---------------------------------------------------------

    def ajouter_clip(self, clip: dict) -> bool:
        """Ajoute un clip s'il est nouveau. Renvoie True si ajouté."""
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO clips (id, streamer, titre, url, vues_twitch, duree, cree_le, maj_le)
               VALUES (:id, :streamer, :titre, :url, :vues_twitch, :duree, :cree_le, :maj_le)""",
            {**clip, "maj_le": time.time()},
        )
        if cur.rowcount == 0:
            # Déjà connu : on met juste à jour le nombre de vues Twitch
            self.conn.execute(
                "UPDATE clips SET vues_twitch = ? WHERE id = ?", (clip["vues_twitch"], clip["id"])
            )
        self.conn.commit()
        return cur.rowcount == 1

    def maj_clip(self, clip_id: str, **champs) -> None:
        if "statut" in champs and champs["statut"] not in STATUTS:
            raise ValueError(f"Statut inconnu : {champs['statut']}")
        champs["maj_le"] = time.time()
        cols = ", ".join(f"{k} = :{k}" for k in champs)
        self.conn.execute(f"UPDATE clips SET {cols} WHERE id = :id", {**champs, "id": clip_id})
        self.conn.commit()

    def clips(self, statut: str | None = None, streamer: str | None = None) -> list[sqlite3.Row]:
        req, params = "SELECT * FROM clips WHERE 1=1", []
        if statut:
            req += " AND statut = ?"
            params.append(statut)
        if streamer:
            req += " AND streamer = ?"
            params.append(streamer.lower())
        req += " ORDER BY vues_twitch DESC"
        return list(self.conn.execute(req, params))

    def clip(self, clip_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()

    # --- comptes TikTok ------------------------------------------------

    def enregistrer_compte(self, nom: str, jeton: dict, open_id: str = "", pseudo: str = "") -> None:
        maintenant = time.time()
        self.conn.execute(
            """INSERT INTO comptes (nom, open_id, pseudo, access_token, refresh_token, expire_le, refresh_expire_le, scopes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(nom) DO UPDATE SET
                 open_id = COALESCE(NULLIF(excluded.open_id, ''), comptes.open_id),
                 pseudo = COALESCE(NULLIF(excluded.pseudo, ''), comptes.pseudo),
                 access_token = excluded.access_token,
                 refresh_token = excluded.refresh_token,
                 expire_le = excluded.expire_le,
                 refresh_expire_le = excluded.refresh_expire_le,
                 scopes = excluded.scopes""",
            (
                nom,
                open_id or jeton.get("open_id", ""),
                pseudo,
                jeton["access_token"],
                jeton["refresh_token"],
                maintenant + int(jeton.get("expires_in", 0)),
                maintenant + int(jeton.get("refresh_expires_in", 0)),
                jeton.get("scope", ""),
            ),
        )
        self.conn.commit()

    def compte(self, nom: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM comptes WHERE nom = ?", (nom,)).fetchone()

    def comptes(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM comptes ORDER BY nom"))

    def supprimer_compte(self, nom: str) -> bool:
        cur = self.conn.execute("DELETE FROM comptes WHERE nom = ?", (nom,))
        self.conn.commit()
        return cur.rowcount == 1
