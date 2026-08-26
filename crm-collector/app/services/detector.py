"""Detector de "precisa de site".

Para cada lead com `website`, mede:
- Status HTTP (404, 5xx, redireciona para rede social, etc.)
- HTTPS / SSL
- Tempo de resposta
- Mobile-friendly básico (presença de viewport meta)
- Tem página de contato / WhatsApp link
- Indícios de CMS datado (generator WordPress/Joomla muito antigo)

Retorna um dict:
  {
    "status": "no_site" | "broken" | "slow" | "no_ssl" | "no_mobile" | "ok",
    "score": 0-100,   # quanto MAIOR, mais precisa de um site NOVO
    "reasons": [str],
    "details": {...}
  }
"""
from __future__ import annotations

import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

DEFAULT_TIMEOUT = 8
SLOW_THRESHOLD = 4.0  # segundos

# Redes sociais que "viram site" para muita empresa pequena.
SOCIAL_DOMAINS = {
    "instagram.com", "facebook.com", "fb.com", "linktr.ee",
    "beacons.ai", "wa.me", "whatsapp.com", "t.me", "twitter.com",
    "x.com", "youtube.com", "bit.ly", "linktree.com",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass
class SiteAudit:
    status: str = "ok"
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def add(self, pts: int, reason: str, **detail) -> None:
        self.score += pts
        if reason:
            self.reasons.append(reason)
        if detail:
            self.details.update(detail)

    def finalize(self) -> dict:
        self.score = max(0, min(100, self.score))
        if self.score >= 70:
            self.status = "no_site" if not self.details.get("has_website") else "broken"
        elif self.score >= 40:
            # piora o status se um dos motivos for grave
            if "sem_ssl" in self.details.get("flags", []):
                self.status = "no_ssl"
            elif "lento" in self.details.get("flags", []):
                self.status = "slow"
            elif "sem_mobile" in self.details.get("flags", []):
                self.status = "no_mobile"
            else:
                self.status = "broken"
        else:
            self.status = "ok"
        return {
            "status": self.status,
            "score": self.score,
            "reasons": self.reasons,
            "details": self.details,
        }


def _normalize_url(url: str) -> Optional[str]:
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    parsed = urlparse(url)
    if not parsed.netloc:
        return None
    return urlunparse(parsed)


def _is_social(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    host = host.replace("www.", "")
    return any(host == d or host.endswith("." + d) for d in SOCIAL_DOMAINS)


def _has_mobile_viewport(html: str) -> bool:
    return bool(re.search(r'name=["\']viewport["\']', html, re.IGNORECASE))


def _has_contact_signals(html: str) -> bool:
    soup = BeautifulSoup(html or "", "lxml")
    text = soup.get_text(" ", strip=True).lower()
    if re.search(r"\bwhats?app\b|wa\.me/|api\.whatsapp", text):
        return True
    if re.search(r"tel:\+?\d", html):
        return True
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", html):
        return True
    return False


def _detect_https(host: str, port: int = 443, timeout: int = 5) -> bool:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host):
                return True
    except Exception:
        return False


def audit_website(url: Optional[str]) -> dict:
    """Audita um site. Retorna dict pronto pra persistir."""
    audit = SiteAudit()
    normalized = _normalize_url(url or "")

    if not normalized:
        audit.add(100, "Sem site cadastrado", has_website=False)
        return audit.finalize()

    if _is_social(normalized):
        audit.add(
            75,
            "O único 'site' é uma rede social — perde SEO e profissionalismo",
            has_website=False,
            flags=["only_social"],
        )
        return audit.finalize()

    audit.details["has_website"] = True
    audit.details["url"] = normalized
    parsed = urlparse(normalized)
    host = parsed.hostname or ""

    # 1) SSL
    if parsed.scheme != "https":
        audit.add(20, "Site sem HTTPS (navegador marca como não seguro)", flags=["sem_ssl"])
        audit.details["https"] = False
    else:
        audit.details["https"] = _detect_https(host)

    # 2) HTTP status + tempo
    try:
        t0 = time.perf_counter()
        resp = requests.get(
            normalized,
            timeout=DEFAULT_TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"},
        )
        elapsed = time.perf_counter() - t0
        audit.details["http_status"] = resp.status_code
        audit.details["elapsed_seconds"] = round(elapsed, 2)
        audit.details["final_url"] = resp.url

        if resp.status_code >= 400:
            audit.add(80, f"Site retornou HTTP {resp.status_code} (quebrado)", flags=["quebrado"])
            return audit.finalize()

        if elapsed > SLOW_THRESHOLD:
            audit.add(15, f"Site lento: {elapsed:.1f}s para carregar", flags=["lento"])

        # Redireciona para rede social? zera o 'tem site'
        if _is_social(resp.url) and _is_social(resp.url) != _is_social(normalized):
            audit.add(70, "Site redireciona para rede social", flags=["only_social"])
            return audit.finalize()

        html = resp.text or ""
    except requests.exceptions.SSLError:
        audit.add(70, "Erro de SSL — site não é confiável", flags=["sem_ssl", "quebrado"])
        return audit.finalize()
    except requests.exceptions.ConnectionError:
        audit.add(90, "Não foi possível conectar ao site", flags=["quebrado"])
        return audit.finalize()
    except requests.exceptions.Timeout:
        audit.add(80, "Site demorou demais para responder (timeout)", flags=["lento", "quebrado"])
        return audit.finalize()
    except Exception as e:
        audit.add(90, f"Erro ao acessar site: {e}", flags=["quebrado"])
        return audit.finalize()

    # 3) Mobile viewport
    if not _has_mobile_viewport(html):
        audit.add(20, "Site sem viewport mobile (ruim no celular)", flags=["sem_mobile"])

    # 4) Contato / WhatsApp visível
    if not _has_contact_signals(html):
        audit.add(10, "Site não mostra contato / WhatsApp claro")

    # 5) Tamanho do HTML (página vazia?)
    if len(html) < 1500:
        audit.add(15, "Página muito pequena — possivelmente em branco")

    # 6) CMS datado
    gen = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', html, re.IGNORECASE)
    if gen:
        audit.details["generator"] = gen.group(1)
        if any(v in gen.group(1).lower() for v in ("joomla", "wordpress 3", "wordpress 2")):
            audit.add(10, f"CMS datado: {gen.group(1)}")

    return audit.finalize()
