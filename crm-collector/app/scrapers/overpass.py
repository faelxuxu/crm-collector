"""Scraper baseado em OpenStreetMap (Overpass + Nominatim).

Vantagens sobre o Google Maps:
- Sem chave de API
- Sem bloqueio agressivo
- Sem CAPTCHA
- Retorna nome, telefone, site, lat/lon, endereço
- Cobre bem nichos de negócio local (POIs)

Mapeamento de nicho humano -> tags OSM (amenity/shop/office/etc).
"""
from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import unquote

import requests

USER_AGENT = "CRM-Collector/1.0 (+https://duocore.com.br)"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Mapeamento de nicho (PT/EN) -> (chave, valor) OSM
# Quanto mais sinônimos, mais resultados o usuário consegue.
NICHE_MAP: dict[str, list[tuple[str, str]]] = {
    # alimentos
    "restaurante": [("amenity", "restaurant")],
    "restaurantes": [("amenity", "restaurant")],
    "pizzaria": [("amenity", "restaurant"), ("cuisine", "pizza")],
    "lanchonete": [("amenity", "fast_food")],
    "hamburgueria": [("amenity", "restaurant"), ("cuisine", "burger")],
    "bar": [("amenity", "bar")],
    "cafeteria": [("amenity", "cafe")],
    "padaria": [("shop", "bakery")],
    "doceria": [("shop", "confectionery")],
    "sorveteria": [("amenity", "ice_cream")],
    "food truck": [("amenity", "food_truck")],
    # saude
    "dentista": [("amenity", "dentist")],
    "clinica": [("amenity", "clinic")],
    "clinica medica": [("amenity", "clinic")],
    "medico": [("amenity", "doctors")],
    "fisioterapia": [("healthcare", "physiotherapist")],
    "psicologo": [("healthcare", "psychologist")],
    "farmacia": [("amenity", "pharmacy")],
    "veterinaria": [("amenity", "veterinary")],
    # beleza
    "salao": [("shop", "beauty")],
    "salao de beleza": [("shop", "beauty")],
    "barbearia": [("shop", "hairdresser")],
    "manicure": [("shop", "beauty")],
    "estetica": [("shop", "beauty")],
    # servicos
    "oficina mecanica": [("shop", "car_repair")],
    "oficina": [("shop", "car_repair")],
    "mecanico": [("shop", "car_repair")],
    "automovel": [("shop", "car")],
    "lavagem de carro": [("amenity", "car_wash")],
    "lavacar": [("amenity", "car_wash")],
    # comercio
    "loja": [("shop", "yes")],
    "loja de roupa": [("shop", "clothes")],
    "roupa": [("shop", "clothes")],
    "boutique": [("shop", "clothes")],
    "pet shop": [("shop", "pet")],
    "petshop": [("shop", "pet")],
    "floricultura": [("shop", "florist")],
    "livraria": [("shop", "books")],
    # fitness
    "academia": [("leisure", "fitness_centre")],
    "pilates": [("leisure", "fitness_centre")],
    "crossfit": [("sport", "fitness")],
    # educacao
    "escola": [("amenity", "school")],
    "creche": [("amenity", "kindergarten")],
    "idiomas": [("amenity", "language_school")],
    # profissoes
    "advogado": [("office", "lawyer")],
    "escritorio de advocacia": [("office", "lawyer")],
    "contador": [("office", "accountant")],
    "imobiliaria": [("office", "estate_agent")],
    "corretor de imoveis": [("office", "estate_agent")],
    "arquiteto": [("office", "architect")],
    "consultoria": [("office", "consulting")],
    # hospedagem
    "hotel": [("tourism", "hotel")],
    "pousada": [("tourism", "guest_house")],
    "hostel": [("tourism", "hostel")],
    # outros
    "igreja": [("amenity", "place_of_worship")],
    "coworking": [("amenity", "coworking_space")],
    "estudio de tatuagem": [("shop", "tattoo")],
}


def _to_overpass_filters(niche: str) -> list[tuple[str, str]]:
    """Resolve o nicho humano para tags OSM."""
    n = niche.lower().strip()
    if n in NICHE_MAP:
        return NICHE_MAP[n]
    # tenta match parcial
    for k, v in NICHE_MAP.items():
        if n in k or k in n:
            return v
    # fallback: nome genérico
    return [(n, "yes")]


def _geocode_city(city: str, country: str) -> Optional[dict]:
    """Usa Nominatim para resolver cidade -> bbox. Retorna dict com lat, lon, bbox."""
    q = city if not country else f"{city}, {country}"
    try:
        r = requests.get(
            NOMINATIM_URL,
            params={"q": q, "format": "json", "limit": 1, "addressdetails": 1},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR"},
            timeout=15,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if not data:
            return None
        item = data[0]
        bb = item.get("boundingbox", [])  # [s, n, w, e]
        if len(bb) != 4:
            return None
        return {
            "name": item.get("display_name", city),
            "south": float(bb[0]),
            "north": float(bb[1]),
            "west": float(bb[2]),
            "east": float(bb[3]),
            "lat": float(item.get("lat", 0)),
            "lon": float(item.get("lon", 0)),
        }
    except Exception:
        return None


def _build_query(filters: list[tuple[str, str]], bbox: dict, limit: int) -> str:
    """Monta a query Overpass QL."""
    # bbox = south, west, north, east (formato OSM: S,W,N,E)
    bbox_str = f"{bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']}"
    # Se muitas combinações de filtro, OR encadeado
    filter_parts = []
    for k, v in filters:
        filter_parts.append(f'  node["{k}"="{v}"]({bbox_str});')
        filter_parts.append(f'  way["{k}"="{v}"]({bbox_str});')
        filter_parts.append(f'  relation["{k}"="{v}"]({bbox_str});')
    inner = "\n".join(filter_parts)
    return (
        "[out:json][timeout:30];\n"
        "(\n"
        f"{inner}\n"
        ");\n"
        f"out center {limit};\n"
    )


def _tag_to_phone(t: dict) -> str:
    return (t.get("phone") or t.get("contact:phone") or t.get("contact:mobile") or "").strip()


def _tag_to_website(t: dict) -> str:
    site = (t.get("website") or t.get("contact:website") or t.get("url") or "").strip()
    if not site:
        return ""
    if not site.startswith(("http://", "https://")):
        site = "http://" + site
    return site


def _tag_to_address(t: dict) -> str:
    parts = [
        t.get("addr:street"),
        t.get("addr:housenumber"),
        t.get("addr:suburb") or t.get("addr:neighbourhood"),
    ]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    base = ", ".join(parts)
    extras = []
    if t.get("addr:city"):
        extras.append(t["addr:city"])
    if t.get("addr:state"):
        extras.append(t["addr:state"])
    if extras:
        base = f"{base} - {'/'.join(extras)}"
    return base


def _normalize_name(n: str) -> str:
    return re.sub(r"\s+", " ", (n or "")).strip()


def search_overpass(
    niche: str,
    city: str,
    country: str = "BR",
    limit: int = 20,
) -> list[dict]:
    """Busca empresas no OpenStreetMap por nicho + cidade."""
    # 1) Geocoding
    geo = _geocode_city(city, country)
    if not geo:
        raise RuntimeError(
            f"Não consegui localizar a cidade '{city}'. Tente um nome mais simples (ex: 'Curitiba')."
        )

    # 2) Filtros OSM
    filters = _to_overpass_filters(niche)
    query = _build_query(filters, geo, limit)

    # 3) Overpass
    try:
        r = requests.post(
            OVERPASS_URL,
            data={"data": query},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=45,
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("Overpass demorou demais. Tente reduzir o máximo de resultados.")
    except Exception as e:
        raise RuntimeError(f"Falha ao chamar Overpass: {e}")

    if r.status_code == 429:
        raise RuntimeError("Overpass rate limit. Espere 1-2 minutos e tente de novo.")
    if r.status_code != 200:
        raise RuntimeError(f"Overpass retornou HTTP {r.status_code}: {r.text[:200]}")

    try:
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"Overpass retornou resposta inválida: {e}")

    elements = data.get("elements", []) or []
    out: list[dict] = []
    seen = set()
    for e in elements:
        t = e.get("tags") or {}
        name = _normalize_name(t.get("name") or t.get("name:pt") or t.get("operator") or "")
        if not name or len(name) < 2:
            continue
        # dedup
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        # lat/lon
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")

        out.append({
            "business_name": name,
            "niche": niche,
            "address": _tag_to_address(t),
            "city": t.get("addr:city") or geo["name"].split(",")[0].strip(),
            "state": t.get("addr:state") or "",
            "country": country.upper(),
            "phone": _tag_to_phone(t),
            "whatsapp": "",
            "email": t.get("contact:email") or t.get("email") or "",
            "instagram": "",
            "website": _tag_to_website(t),
            "latitude": lat,
            "longitude": lon,
            "source": "openstreetmap",
            "notes": "OSM id: " + str(e.get("id", "")),
        })
        if len(out) >= limit:
            break

    return out
