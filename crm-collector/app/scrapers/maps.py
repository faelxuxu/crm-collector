"""Scraper de Google Maps (sem API paga).

Estratégia: faz uma busca em maps.google.com e extrai os cards de resultado
com nome, endereço, telefone, site, link para Google Maps. Não é perfeito
(o Google muda layout), mas é o melhor equilíbrio sem pagar Places API.

Para rodar grande volume, use uma chave real do Google Places API.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from typing import Iterable

import requests
from bs4 import BeautifulSoup

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]


def _ua() -> str:
    return USER_AGENTS[hash(time.time_ns()) % len(USER_AGENTS)]


def _search_html(query: str, country: str, language: str = "pt-BR") -> str:
    """Faz a busca em maps.google.com e devolve o HTML."""
    url = "https://www.google.com/maps/search/" + urllib.parse.quote(query)
    params = {"hl": language, "gl": country.lower()}
    headers = {
        "User-Agent": _ua(),
        "Accept-Language": f"{language};q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    r = requests.get(url, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    return r.text


def _extract_initial_data(html: str) -> dict | None:
    """O Google embeda um JSON gigante em window.APP_INITIALIZATION_STATE."""
    m = re.search(r"window\.APP_INITIALIZATION_STATE=([^;]+);", html)
    if not m:
        return None
    try:
        # O JS tem encoding custom; usamos unquote com latin-1
        from urllib.parse import unquote
        raw = unquote(m.group(1))
        raw = raw.strip('"')
        return json.loads(raw)
    except Exception:
        return None


def _parse_leads_from_initial(data: dict, limit: int) -> Iterable[dict]:
    """Tenta extrair leads do JSON do Maps."""
    # Estrutura típica: data[3] contém lista de resultados
    try:
        # Navega na estrutura dinâmica
        candidates = []
        stack = [data]
        while stack and len(candidates) < limit * 3:
            cur = stack.pop()
            if isinstance(cur, dict):
                if "name" in cur and isinstance(cur.get("name"), str) and len(cur["name"]) > 2:
                    if any(k in cur for k in ("address", "phone", "website", "url")) or cur.get("category"):
                        candidates.append(cur)
                for v in cur.values():
                    stack.append(v)
            elif isinstance(cur, list):
                for v in cur:
                    stack.append(v)

        seen = set()
        out = []
        for c in candidates:
            name = (c.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            out.append({
                "business_name": name,
                "address": c.get("address") or c.get("vicinity"),
                "phone": c.get("phone") or c.get("international_phone_number"),
                "website": c.get("website"),
                "category": c.get("category"),
                "google_maps_url": c.get("url") or c.get("link"),
                "latitude": c.get("latitude") or c.get("lat"),
                "longitude": c.get("longitude") or c.get("lng"),
            })
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def _parse_leads_from_html(html: str, limit: int) -> Iterable[dict]:
    """Fallback: regex no HTML (menos confiável, mas funciona em muitos casos)."""
    out = []
    # Encontra blocos de resultado do Maps
    blocks = re.findall(r"<div class=\"[^\"]*section-result[^\"]*\"[^>]*>(.*?)(?=<div class=\"section-result|$)", html, re.DOTALL)
    for b in blocks:
        name_m = re.search(r"class=\"[^\"]*section-result-title[^\"]*\"[^>]*>([^<]+)</a>", b)
        if not name_m:
            name_m = re.search(r"class=\"[^\"]*place-name[^\"]*\"[^>]*>([^<]+)</", b)
        if not name_m:
            continue
        name = name_m.group(1).strip()
        phone_m = re.search(r"(\+?\d[\d\s().-]{7,}\d)", b)
        addr_m = re.search(r"class=\"[^\"]*section-result-address[^\"]*\"[^>]*>([^<]+)</", b)
        site_m = re.search(r"href=\"(https?://(?!www\.google|google\.com|maps\.google)[^\"]+)\"", b)
        out.append({
            "business_name": name,
            "address": addr_m.group(1).strip() if addr_m else None,
            "phone": phone_m.group(1).strip() if phone_m else None,
            "website": site_m.group(1) if site_m else None,
            "source": "google_maps",
        })
        if len(out) >= limit:
            break
    return out


def search_google_maps(niche: str, city: str, country: str = "BR", limit: int = 20, delay: float = 2.5, language: str = "pt-BR") -> list[dict]:
    """Busca empresas no Google Maps por nicho + cidade."""
    query = f"{niche} {city}"
    try:
        html = _search_html(query, country, language=language)
    except requests.HTTPError as e:
        # Se o Google barrar, devolve vazio e o caller registra o erro.
        raise RuntimeError(f"Google bloqueou a busca (HTTP {e.response.status_code}). Tente outro nicho/cidade ou diminua o volume.") from e
    except Exception as e:
        raise RuntimeError(f"Falha na busca: {e}") from e

    initial = _extract_initial_data(html)
    leads: list[dict] = []
    if initial:
        leads = list(_parse_leads_from_initial(initial, limit))

    if not leads:
        leads = list(_parse_leads_from_html(html, limit))

    # Normaliza país/cidade
    for l in leads:
        l["city"] = city
        l["country"] = country
        l["niche"] = niche
        l.setdefault("source", "google_maps")
    return leads[:limit]
