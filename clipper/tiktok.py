"""Client pour les API officielles TikTok : Login Kit (OAuth) et Content Posting API."""

from __future__ import annotations

import math
import secrets
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API = "https://open.tiktokapis.com/v2"
SCOPES = "user.info.basic,video.publish,video.list"

MIN_CHUNK = 5 * 1024 * 1024
MAX_CHUNK = 64 * 1024 * 1024


class TikTokError(Exception):
    pass


def url_autorisation(client_key: str, redirect_uri: str, state: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode(
        {
            "client_key": client_key,
            "scope": SCOPES,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )


def attendre_code(redirect_uri: str, state: str, delai: int = 300) -> str:
    """Démarre un mini serveur local sur redirect_uri et attend le code OAuth."""
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.hostname not in ("localhost", "127.0.0.1"):
        raise TikTokError("La récupération automatique du code nécessite une redirect_uri en localhost.")
    recu: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            recu.update({k: v[0] for k, v in q.items()})
            ok = "code" in recu and recu.get("state") == state
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Compte connecté, tu peux fermer cet onglet." if ok else "Échec de la connexion."
            self.wfile.write(f"<h2>{msg}</h2>".encode())

        def log_message(self, *args):
            pass

    serveur = HTTPServer((parsed.hostname, parsed.port or 80), Handler)
    serveur.timeout = 1
    fin = time.time() + delai
    try:
        while "code" not in recu and "error" not in recu and time.time() < fin:
            serveur.handle_request()
    finally:
        serveur.server_close()

    if "error" in recu:
        raise TikTokError(f"Connexion refusée : {recu.get('error_description', recu['error'])}")
    if "code" not in recu:
        raise TikTokError("Délai dépassé sans réponse de TikTok.")
    if recu.get("state") != state:
        raise TikTokError("Paramètre `state` invalide (tentative de connexion suspecte).")
    return recu["code"]


def nouveau_state() -> str:
    return secrets.token_urlsafe(16)


def plan_morceaux(taille: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) selon les règles de TikTok.

    - fichier < 5 Mo : un seul morceau de la taille du fichier ;
    - sinon morceaux de 10 Mo, le dernier absorbant le reste (jusqu'à 128 Mo).
    """
    if taille <= 0:
        raise TikTokError("Fichier vidéo vide.")
    if taille < MIN_CHUNK:
        return taille, 1
    chunk = min(10 * 1024 * 1024, MAX_CHUNK)
    return chunk, max(1, math.floor(taille / chunk))


class TikTok:
    def __init__(self, client_key: str, client_secret: str, session: requests.Session | None = None):
        self.client_key = client_key
        self.client_secret = client_secret
        self.http = session or requests.Session()

    # --- OAuth -----------------------------------------------------------

    def _token(self, donnees: dict) -> dict:
        r = self.http.post(
            f"{API}/oauth/token/",
            data={"client_key": self.client_key, "client_secret": self.client_secret, **donnees},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
        data = r.json()
        if r.status_code != 200 or "access_token" not in data:
            raise TikTokError(f"Échec OAuth TikTok : {data.get('error_description') or data}")
        return data

    def echanger_code(self, code: str, redirect_uri: str) -> dict:
        return self._token({"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri})

    def rafraichir(self, refresh_token: str) -> dict:
        return self._token({"refresh_token": refresh_token, "grant_type": "refresh_token"})

    # --- Appels authentifiés --------------------------------------------

    def _post(self, access_token: str, chemin: str, json: dict | None = None, params: dict | None = None) -> dict:
        r = self.http.post(
            f"{API}/{chemin}",
            json=json or {},
            params=params,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
            timeout=30,
        )
        try:
            data = r.json()
        except ValueError:
            raise TikTokError(f"Réponse invalide de TikTok ({r.status_code}) : {r.text[:300]}")
        err = data.get("error") or {}
        if r.status_code != 200 or err.get("code", "ok") != "ok":
            raise TikTokError(f"TikTok {chemin} : {err.get('code')} — {err.get('message') or r.text[:300]}")
        return data.get("data") or {}

    def infos_utilisateur(self, access_token: str) -> dict:
        r = self.http.get(
            f"{API}/user/info/",
            params={"fields": "open_id,display_name"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        data = r.json()
        if r.status_code != 200:
            raise TikTokError(f"TikTok user/info : {data}")
        return (data.get("data") or {}).get("user") or {}

    def infos_createur(self, access_token: str) -> dict:
        """Options autorisées pour ce compte (niveaux de confidentialité, durée max…)."""
        return self._post(access_token, "post/publish/creator_info/query/")

    def publier_video(
        self,
        access_token: str,
        fichier: Path,
        titre: str,
        confidentialite: str,
        contenu_sponsorise: bool = False,
    ) -> str:
        """Envoie la vidéo (upload direct) et renvoie le publish_id."""
        taille = fichier.stat().st_size
        chunk, total = plan_morceaux(taille)
        init = self._post(
            access_token,
            "post/publish/video/init/",
            json={
                "post_info": {
                    "title": titre[:2200],
                    "privacy_level": confidentialite,
                    "disable_duet": False,
                    "disable_comment": False,
                    "disable_stitch": False,
                    "brand_content_toggle": contenu_sponsorise,
                    "brand_organic_toggle": False,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": taille,
                    "chunk_size": chunk,
                    "total_chunk_count": total,
                },
            },
        )
        publish_id, upload_url = init["publish_id"], init["upload_url"]

        with fichier.open("rb") as f:
            for i in range(total):
                debut = i * chunk
                fin = taille - 1 if i == total - 1 else debut + chunk - 1
                f.seek(debut)
                morceau = f.read(fin - debut + 1)
                r = self.http.put(
                    upload_url,
                    data=morceau,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(morceau)),
                        "Content-Range": f"bytes {debut}-{fin}/{taille}",
                    },
                    timeout=300,
                )
                if r.status_code not in (200, 201, 206):
                    raise TikTokError(f"Upload du morceau {i + 1}/{total} refusé ({r.status_code}) : {r.text[:300]}")
        return publish_id

    def statut_publication(self, access_token: str, publish_id: str) -> dict:
        return self._post(access_token, "post/publish/status/fetch/", json={"publish_id": publish_id})

    def stats_videos(self, access_token: str, video_ids: list[str]) -> dict[str, int]:
        """video_id -> nombre de vues (20 vidéos max par requête)."""
        vues: dict[str, int] = {}
        for i in range(0, len(video_ids), 20):
            data = self._post(
                access_token,
                "video/query/",
                json={"filters": {"video_ids": video_ids[i : i + 20]}},
                params={"fields": "id,view_count"},
            )
            for v in data.get("videos", []):
                vues[str(v["id"])] = int(v.get("view_count", 0))
        return vues
