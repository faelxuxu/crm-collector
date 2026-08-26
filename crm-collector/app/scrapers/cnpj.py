"""Scraper de CNPJ via ReceitaWS / BrasilAPI (gratuitos, sem chave).

Útil como enriquecimento: dado nome + cidade, acha CNPJ e razão social.
Hoje não rodamos isso automaticamente, mas está exposto como ferramenta.
"""
from __future__ import annotations

import re
import time
from typing import Optional

import requests


def lookup_cnpj(cnpj: str) -> Optional[dict]:
    """Limpa e consulta. Retorna dict com dados básicos ou None."""
    digits = re.sub(r"\D", "", cnpj or "")
    if len(digits) != 14:
        return None
    try:
        r = requests.get(f"https://brasilapi.com.br/api/cnpj/v1/{digits}", timeout=10)
        if r.status_code == 200:
            d = r.json()
            return {
                "cnpj": d.get("cnpj"),
                "razao_social": d.get("razao_social"),
                "nome_fantasia": d.get("nome_fantasia"),
                "telefone": d.get("ddd_telefone_1"),
                "email": d.get("email"),
                "logradouro": d.get("logradouro"),
                "numero": d.get("numero"),
                "bairro": d.get("bairro"),
                "municipio": d.get("municipio"),
                "uf": d.get("uf"),
                "cep": d.get("cep"),
            }
    except Exception:
        return None
    return None
