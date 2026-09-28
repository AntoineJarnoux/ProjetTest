"""Rapport des vues TikTok et du montant dû par chaque streamer."""

from __future__ import annotations

from clipper.config import Config


def calculer_rapport(cfg: Config, clips_publies) -> list[dict]:
    lignes: dict[str, dict] = {}
    for c in clips_publies:
        l = lignes.setdefault(c["streamer"], {"streamer": c["streamer"], "videos": 0, "vues": 0, "montant": 0.0})
        l["videos"] += 1
        l["vues"] += int(c["vues_tiktok"] or 0)
    for l in lignes.values():
        s = cfg.streamer(l["streamer"])
        taux = s.remuneration_par_1000_vues if s else 0.0
        l["montant"] = round(l["vues"] / 1000 * taux, 2)
    return sorted(lignes.values(), key=lambda l: l["montant"], reverse=True)


def formater_rapport(lignes: list[dict]) -> str:
    if not lignes:
        return "Aucune vidéo publiée pour l'instant."
    out = [f"{'Streamer':<20} {'Vidéos':>7} {'Vues':>12} {'À facturer':>12}"]
    for l in lignes:
        out.append(f"{l['streamer']:<20} {l['videos']:>7} {l['vues']:>12,} {l['montant']:>10.2f} €".replace(",", " "))
    total = sum(l["montant"] for l in lignes)
    out.append(f"{'TOTAL':<20} {'':>7} {sum(l['vues'] for l in lignes):>12,} {total:>10.2f} €".replace(",", " "))
    return "\n".join(out)
