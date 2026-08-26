"""Scraper simples de Instagram: dado nome de empresa, tenta achar @ oficial.

Útil para preencher o campo instagram do lead depois de coletar no Maps.
Faz só a busca pública (sem login) e extrai o primeiro resultado plausível.
"""
from __future__ import annotations

import re
import time
import urllib.parse
from typing import Optional

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _slug(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", "", s)
    s = s[:30]
    return s


def guess_instagram_handle(business_name: str, city: str = "") -> Optional[str]:
    """Tenta achar o @ oficial no Google (busca site:instagram.com)."""
    q = f"site:instagram.com {business_name} {city}".strip()
    url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": q, "num": 5, "hl": "pt-BR"})
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR"}, timeout=10)
    except Exception:
        return None
    soup = BeautifulSoup(r.text, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"instagram\.com/([A-Za-z0-9_.]{3,30})", href)
        if m and m.group(1).lower() not in {"p", "reel", "stories", "explore"}:
            return "@" + m.group(1)
    return None


def _check_profile_exists(handle: str) -> bool:
    """Confere se um @ existe (sem precisar de login)."""
    if handle.startswith("@"):
        handle = handle[1:]
    url = f"https://www.instagram.com/{handle}/"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10, allow_redirects=True)
        return r.status_code == 200 and "Page Not Found" not in r.text
    except Exception:
        return False


def find_instagram(business_name: str, city: str = "") -> Optional[str]:
    """Tenta Google + heurística de slug."""
    found = guess_instagram_handle(business_name, city)
    if found:
        return found
    # Fallback: testa slug simples
    slug = _slug(business_name)
    if slug and _check_profile_exists(slug):
        return "@" + slug
    return None
