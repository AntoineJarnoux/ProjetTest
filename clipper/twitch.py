"""Client minimal pour l'API officielle Twitch Helix."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import requests

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API = "https://api.twitch.tv/helix"


class TwitchError(Exception):
    pass


class Twitch:
    def __init__(self, client_id: str, client_secret: str, session: requests.Session | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = session or requests.Session()
        self._token: str | None = None
        self._expire = 0.0

    def _jeton(self) -> str:
        if self._token and time.time() < self._expire - 60:
            return self._token
        r = self.http.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
            timeout=20,
        )
        if r.status_code != 200:
            raise TwitchError(f"Authentification Twitch refusée ({r.status_code}) : {r.text}")
        data = r.json()
        self._token = data["access_token"]
        self._expire = time.time() + data.get("expires_in", 3600)
        return self._token

    def _get(self, chemin: str, params: dict) -> dict:
        r = self.http.get(
            f"{API}/{chemin}",
            params=params,
            headers={"Client-Id": self.client_id, "Authorization": f"Bearer {self._jeton()}"},
            timeout=20,
        )
        if r.status_code != 200:
            raise TwitchError(f"Erreur Twitch {chemin} ({r.status_code}) : {r.text}")
        return r.json()

    def ids_utilisateurs(self, logins: list[str]) -> dict[str, str]:
        """login -> broadcaster_id (par paquets de 100, limite de l'API)."""
        resultat: dict[str, str] = {}
        for i in range(0, len(logins), 100):
            data = self._get("users", [("login", l) for l in logins[i : i + 100]])
            for u in data.get("data", []):
                resultat[u["login"].lower()] = u["id"]
        return resultat

    def clips(self, broadcaster_id: str, jours: int = 7, max_clips: int = 20) -> list[dict]:
        """Clips les plus vus du streamer sur les `jours` derniers jours."""
        fin = datetime.now(timezone.utc)
        debut = fin - timedelta(days=jours)
        data = self._get(
            "clips",
            {
                "broadcaster_id": broadcaster_id,
                "started_at": debut.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "ended_at": fin.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "first": min(max(max_clips, 1), 100),
            },
        )
        return data.get("data", [])


def normaliser_clip(brut: dict, streamer: str) -> dict:
    return {
        "id": brut["id"],
        "streamer": streamer.lower(),
        "titre": brut.get("title", "").strip(),
        "url": brut["url"],
        "vues_twitch": int(brut.get("view_count", 0)),
        "duree": float(brut.get("duration", 0)),
        "cree_le": brut.get("created_at"),
    }
