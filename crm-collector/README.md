# CRM Collector 🛰️

Coletor de leads qualificados que **precisam de um site**. O sistema:

1. Raspa o **Google Maps** por nicho + cidade (ex: "restaurante" + "Curitiba").
2. Para cada empresa, **audita o site atual** (existe? HTTPS? mobile? rápido? tem contato?).
3. Calcula um **score 0–100** — quanto maior, mais "carente" de um site novo.
4. Enriquece com **Instagram** (heurística via Google).
5. Guarda tudo num **CRM interno** com pipeline kanban.
6. Gera **3 mensagens de abordagem prontas** por lead, com a "dor" detectada.
7. Permite **importar CSV** e **exportar** pra qualquer ferramenta externa.

Sem chave de API paga. Roda 100% local.

---

## Instalação

```bash
# 1) Crie o venv (Windows)
python -m venv .venv
.venv\Scripts\activate

# ou no Linux/Mac
python3 -m venv .venv
source .venv/bin/activate

# 2) Instale as dependências
pip install -r requirements.txt

# 3) (Opcional) copie o .env e edite com seu nome / WhatsApp
cp .env.example .env
```

## Rodar

```bash
python run.py
```

Acesse **http://127.0.0.1:5000**.

## Como usar

### 1) Coletar leads
Menu **Coletar** → preencha:
- **Nicho**: ex. *restaurante*, *dentista*, *salão de beleza*, *oficina mecânica*
- **Cidade**: ex. *Curitiba*
- **Máx. resultados**: até 60 (acima disso o Google começa a bloquear)
- **Delay**: 2.5s é seguro. Menos = mais risco de bloqueio.

A coleta roda em **background** (thread). Acompanhe o histórico na mesma página e vá no **Dashboard** ver os mais quentes.

### 2) Olhar o lead
Cada lead tem:
- Score 0–100 (🟢 0–40 = site OK · 🟡 40–60 = tem problema · 🔴 60–100 = precisa de site novo)
- Lista de "dores" detectadas (sem SSL, sem mobile, lento, etc.)
- Botões de WhatsApp, telefone, email direto
- **3 mensagens de abordagem** prontas pra copiar (curta, valor primeiro, conexão humana)
- Timeline de notas e interações

### 3) Mover no pipeline
- Pelo card de status na página do lead
- Ou pela página **Pipeline** (visão kanban)

### 4) Importar / Exportar
- **Importar**: CSV com colunas `business_name, niche, address, city, state, country, phone, whatsapp, email, instagram, facebook, website, notes`
- **Exportar**: link no menu superior, baixa `leads-AAAAMMDD-HHMM.csv` com UTF-8 BOM (abre no Excel)

### 5) Reauditar um site
Na página do lead, clique em **🔄 Reauditar site**. Útil quando o cliente mexeu no site dele.

---

## Estrutura

```
crm-collector/
├── app/
│   ├── main.py            # Flask factory
│   ├── routes.py          # rotas web + API
│   ├── db.py              # SQLite + CRUD
│   ├── scrapers/
│   │   ├── maps.py        # Google Maps (sem Places API)
│   │   ├── instagram.py   # heurística de @ oficial
│   │   ├── cnpj.py        # BrasilAPI (CNPJ)
│   │   └── pipeline.py    # orquestra Maps → detector → DB
│   ├── services/
│   │   ├── detector.py    # score 0-100 "precisa de site"
│   │   └── copy.py        # 3 variações de mensagem
│   ├── templates/         # Jinja2
│   └── static/            # CSS + JS
├── data/                  # SQLite fica aqui (data/crm.db)
├── exports/               # CSVs exportados
├── requirements.txt
├── run.py
└── .env.example
```

## Detector "precisa de site" — como funciona

Pontos somados (cap em 100):

| Sinal | Pontos | Razão |
|---|---|---|
| Sem site | 100 | "Sem site cadastrado" |
| Site é rede social (Instagram/FB) | 75 | "Perde SEO" |
| Não conecta / timeout | 80-90 | "Site fora do ar" |
| HTTP 4xx/5xx | 80 | "Quebrado" |
| Sem HTTPS | 20 | "Navegador marca como não seguro" |
| Lento (>4s) | 15 | "Cliente desiste" |
| Sem viewport mobile | 20 | "Ruim no celular" |
| Sem contato/WhatsApp visível | 10 | "Conversão ruim" |
| Página vazia (<1500 chars) | 15 | "Em branco" |
| CMS datado (Joomla, WP<4) | 10 | "Hacker vai amar" |

---

## API JSON (bônus)

```
GET  /api/leads?status=novo&min_score=60
POST /api/audit        body: {"url": "https://exemplo.com.br"}
GET  /api/cnpj/12345678000190
```

---

## Avisos importantes

- **Rate limit**: o Google pode bloquear IP se você raspar muito agressivo. Delay mínimo recomendado: **2s** entre resultados. Acima de 50 leads/dia, considere a **Google Places API oficial** (~US$ 32 / 1.000 requests) — é mais estável e juridicamente seguro.
- **LGPD / Termos**: só use os dados para contatar a empresa. Não revenda a base. Dê opt-out no primeiro contato.
- **Validação humana**: nenhum detector substitui seu olho. Antes de abordar, abra o site (se houver) e confirme que a dor é real.

## Próximos passos (ideias)

- [ ] Google Places API como alternativa paga
- [ ] Integração WhatsApp Web (Playwright) com botão "Enviar"
- [ ] Agendamento de follow-ups
- [ ] Análise de SEO local (Google Business Profile score)
- [ ] Exportar pra Bitrix / Hubspot / Notion
- [ ] Detector de Instagram via GraphQL (mais confiável)
