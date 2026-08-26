"""Orquestrador de scraping: junta o provedor escolhido + detector + Instagram, e grava no banco."""
from __future__ import annotations

import json as _json
import re
import sys
import time
from dataclasses import dataclass
from typing import Callable

from app import db
from app.scrapers import instagram as ig_scraper
from app.scrapers import overpass as overpass_scraper
from app.services.detector import audit_website


def _safe_print(msg: str) -> None:
    """Imprime sem quebrar em consoles que não aceitam unicode (ex: cp1252)."""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def _clean_phone(phone: str) -> str:
    if not phone:
        return ""
    return re.sub(r"[^\d+]", "", phone).strip()


def _extract_whatsapp(phone: str, country: str = "BR") -> str:
    p = _clean_phone(phone)
    if not p:
        return ""
    if country.upper() == "BR" and len(p) >= 10 and not p.startswith("+"):
        p = "+55" + p
    return p


@dataclass
class ScrapeResult:
    found: int = 0
    inserted: int = 0
    updated: int = 0
    errors: list[str] = None
    provider: str = ""

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def _search(provider: str, niche: str, city: str, country: str, limit: int, delay: float):
    """Despacha para o provedor certo."""
    if provider == "overpass":
        return overpass_scraper.search_overpass(
            niche=niche, city=city, country=country, limit=limit,
        )
    # default
    return overpass_scraper.search_overpass(
        niche=niche, city=city, country=country, limit=limit,
    )


def run_scrape(
    niche: str,
    city: str,
    country: str = "BR",
    max_results: int = 20,
    delay: float = 2.5,
    enrich_instagram: bool = True,
    provider: str = "overpass",
    progress_cb: Callable[[str], None] | None = None,
) -> ScrapeResult:
    """Coleta leads do provedor escolhido, audita site, enriquece com Instagram, salva no DB."""
    res = ScrapeResult(provider=provider)
    log = progress_cb or (lambda m: _safe_print(m))

    log(f"Buscando '{niche}' em '{city}' via {provider}...")
    try:
        leads = _search(provider, niche, city, country, max_results, delay)
    except Exception as e:
        res.errors.append(str(e))
        log(f"Erro: {e}")
        return res

    res.found = len(leads)
    if not leads:
        log("Nenhum resultado. Tente outro nicho ou cidade mais específica.")
        return res

    log(f"{res.found} resultados. Auditando sites...")

    for i, l in enumerate(leads, 1):
        name = l.get("business_name") or "?"
        try:
            audit = audit_website(l.get("website"))
            l["website_status"] = audit["status"]
            l["website_score"] = audit["score"]
            pain = "; ".join(audit.get("reasons", []))
            l["notes"] = (l.get("notes") or "") + (" | " if l.get("notes") else "") + pain
            l["pain_points"] = _json.dumps(audit.get("reasons", []), ensure_ascii=False)
            l["whatsapp"] = _extract_whatsapp(l.get("phone"), country)

            lead_id, created = db.upsert_lead(l)
            if created:
                res.inserted += 1
            else:
                res.updated += 1
            log(f"  {i}/{res.found} {name} -> score {audit['score']} ({audit['status']})")

            if enrich_instagram and not l.get("instagram"):
                time.sleep(0.4)
                handle = ig_scraper.find_instagram(name, city)
                if handle:
                    db.update_lead(lead_id, {"instagram": handle})
                    log(f"     IG: {handle}")

        except Exception as e:
            res.errors.append(f"{name}: {e}")
            log(f"  ERRO {name}: {e}")

        if i < res.found:
            time.sleep(delay)

    return res
