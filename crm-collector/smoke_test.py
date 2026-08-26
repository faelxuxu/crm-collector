"""Smoke test: importa tudo, cria banco, roda rotas principais em memória."""
import os
import sys
import tempfile

# Usa banco temporário
tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
os.environ["CRM_DB_PATH"] = tmp.name

# Garante que estamos no diretório do projeto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import create_app
from app import db
from app.services.detector import audit_website
from app.services.copy import generate_outreach


def main() -> int:
    app = create_app()
    client = app.test_client()

    print("1) GET /")
    r = client.get("/")
    assert r.status_code == 200, r.data[:200]
    print("   [ok] dashboard 200")

    print("2) GET /leads")
    r = client.get("/leads")
    assert r.status_code == 200
    print("   [ok] /leads 200")

    print("3) POST /leads/new (manual)")
    r = client.post("/leads/new", data={
        "business_name": "Padaria Teste",
        "niche": "padaria",
        "city": "Curitiba",
        "state": "PR",
        "country": "BR",
        "phone": "+5541999998888",
        "whatsapp": "+5541999998888",
        "website": "",
    }, follow_redirects=True)
    assert r.status_code == 200
    print("   [ok] lead criado")

    print("4) detector.audit_website (sem site)")
    audit = audit_website("")
    assert audit["score"] >= 90
    print(f"   [ok] score={audit['score']} status={audit['status']}")

    print("5) detector.audit_website (dominio social)")
    audit = audit_website("https://instagram.com/padariateste")
    assert audit["score"] >= 70, audit
    print(f"   [ok] score={audit['score']} status={audit['status']}")

    print("6) copy.generate_outreach")
    lead = {"business_name": "Padaria Teste", "city": "Curitiba", "niche": "padaria",
            "website_status": "no_site", "website": ""}
    msgs = generate_outreach(lead, your_name="José", your_company="DevSites",
                              your_whatsapp="+5541999990000", your_portfolio="https://devsites.com.br")
    assert len(msgs) == 3
    for m in msgs:
        assert "Padaria Teste" in m["text"]
        assert "Curitiba" in m["text"]
    print(f"   [ok] 3 mensagens geradas ({msgs[0]['style']}, ...)")

    print("7) GET /pipeline")
    r = client.get("/pipeline")
    assert r.status_code == 200
    print("   [ok] /pipeline 200")

    print("8) GET /api/leads")
    r = client.get("/api/leads")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list)
    assert any(l["business_name"] == "Padaria Teste" for l in data)
    print(f"   [ok] {len(data)} leads na API")

    print("9) POST /api/audit")
    r = client.post("/api/audit", json={"url": ""})
    assert r.status_code == 200
    a = r.get_json()
    assert a["score"] >= 90
    print(f"   [ok] API audit: score={a['score']}")

    print("10) /export.csv")
    r = client.get("/export.csv")
    assert r.status_code == 200
    assert b"Padaria Teste" in r.data
    print("   [ok] CSV exportado com o lead")

    print("\n[OK] Smoke test passou.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"\n[FAIL] Falhou: {e}")
        sys.exit(1)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
