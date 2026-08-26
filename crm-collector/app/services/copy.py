"""Geração de copy de abordagem.

Não chama LLM externa (custa $$) — usa templates parametrizados com:
- nome do negócio
- cidade / estado
- nicho
- "dor" detectada (sem site, sem SSL, sem mobile, lento...)
"""
from __future__ import annotations

import os
from typing import Optional


def _first_name(your_name: str) -> str:
    return (your_name or "Eu").split()[0] if your_name else "Eu"


def _pain_phrase(lead: dict) -> str:
    status = (lead.get("website_status") or "").lower()
    has_site = bool(lead.get("website"))
    if not has_site or status == "no_site":
        return "hoje você praticamente não tem presença online"
    if status == "no_ssl":
        return "o site aparece como 'não seguro' no navegador, o que espanta cliente"
    if status == "no_mobile":
        return "o site não funciona bem no celular — onde estão a maioria dos seus clientes"
    if status == "slow":
        return "o site demora pra abrir e o cliente desiste antes de ver"
    if status == "broken":
        return "o site está com problemas técnicos (erros, fora do ar, etc.)"
    return "o site atual não está te gerando o retorno que poderia"


def _niche_callout(lead: dict) -> str:
    niche = (lead.get("niche") or "").lower()
    business = lead.get("business_name", "")
    if any(k in niche for k in ("restaurante", "pizzaria", "lanchonete", "bar ", "hamburgueria")):
        return f"para {business} aparecer quando alguém pesquisa 'comer perto de mim' no Google"
    if any(k in niche for k in ("dentista", "clinica", "médic", "fisioterap", "psicólog", "odonto")):
        return f"para {business} ser encontrado por quem está procurando agenda aberta"
    if any(k in niche for k in ("salão", "barbearia", "cabeleireiro", "manicure", "estética", "beleza")):
        return f"para lotar a agenda de {business} com clientes novos do bairro"
    if any(k in niche for k in ("loja", "roupa", "boutique", "ecommerce", "e-commerce")):
        return f"para {business} vender também pela internet 24h"
    if any(k in niche for k in ("academia", "pilates", "crossfit", "personal", "studio")):
        return f"para captar alunos novos pela internet para {business}"
    if any(k in niche for k in ("advogad", "escritório", "contabilidade", "consultoria")):
        return f"para {business} transmitir credibilidade e captar clientes corporativos"
    if any(k in niche for k in ("imobili", "corretor", "aluguel")):
        return f"para {business} anunciar imóveis e receber leads direto no WhatsApp"
    if any(k in niche for k in ("mecânic", "oficina", "auto")):
        return f"para {business} ser encontrado quando o carro quebra e a pessoa pesquisa no Google"
    return f"para {business} aparecer no Google e converter visitas em clientes"


def generate_outreach(lead: dict, your_name: str = "", your_company: str = "", your_whatsapp: str = "", your_portfolio: str = "") -> list[dict]:
    """Retorna 3 variações de mensagem para o primeiro contato."""
    business = lead.get("business_name") or "tudo bem?"
    city = lead.get("city") or ""
    name = _first_name(your_name)
    pain = _pain_phrase(lead)
    callout = _niche_callout(lead)
    sender = your_company or f"{name} (desenvolvedor de sites)"

    local = f" em {city}" if city else ""

    signature_parts = [name]
    if your_company:
        signature_parts.append(your_company)
    if your_whatsapp:
        signature_parts.append(f"WhatsApp: {your_whatsapp}")
    if your_portfolio:
        signature_parts.append(f"Portfólio: {your_portfolio}")
    signature = " | ".join(signature_parts)

    # Variação 1 — Curta e direta (WhatsApp)
    short = (
        f"Oi, tudo bem? Sou {name}, da {sender}. "
        f"Vi que {business}{local} {pain} — {callout}. "
        f"Posso te mandar uma ideia rápida de como ficaria? Sem compromisso."
    )

    # Variação 2 — Valor primeiro + pergunta
    value = (
        f"Olá! Passei pelo {business}{local} e notei uma oportunidade: "
        f"{pain}. Já ajudei negócios do seu segmento a {callout.replace('para ', '')} — "
        f"o investimento normalmente se paga no primeiro mês. "
        f"Posso te mostrar um exemplo rápido (2 min) e você decide se faz sentido?"
    )

    # Variação 3 — Conexão humana (Instagram / DM)
    nicho_frase = ("para " + (lead.get("niche") or "negócios locais")) if lead.get("niche") else "para negócios locais"
    dor_frase = ("resolva isso: " + pain) if pain else "te ajude a aparecer mais"
    dm = (
        f"Ei! Acompanho o {business}{local} há um tempo e sou fã. "
        f"Sou {name}, faço sites {nicho_frase}. "
        f"Se fizer sentido, posso montar um site que {dor_frase}. "
        f"Quer trocar uma ideia?"
    )

    return [
        {"style": "Curta (WhatsApp)", "text": short, "signature": signature},
        {"style": "Valor primeiro", "text": value, "signature": signature},
        {"style": "Conexão humana (DM)", "text": dm, "signature": signature},
    ]
