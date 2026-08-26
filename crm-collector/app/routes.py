"""Rotas Flask do CRM Collector."""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
from datetime import datetime
from typing import Optional

from flask import (
    Blueprint, abort, flash, jsonify, redirect,
    render_template, request, send_file, url_for,
)

from app import db
from app.scrapers import cnpj as cnpj_scraper
from app.scrapers import pipeline as scrape_pipeline
from app.services.copy import generate_outreach
from app.services.detector import audit_website

log = logging.getLogger("crm-collector")

bp = Blueprint("main", __name__)


# ---------- Páginas ----------

@bp.route("/")
def dashboard():
    stats = db.dashboard_stats()
    leads = db.list_leads(limit=20)
    jobs = db.list_recent_jobs(limit=5)
    return render_template("dashboard.html", stats=stats, leads=leads, jobs=jobs)


@bp.route("/leads")
def leads_list():
    status = request.args.get("status", "todos")
    city = request.args.get("city") or None
    min_score = request.args.get("min_score", type=int)
    search = request.args.get("q") or None
    order = request.args.get("order", "website_score DESC, updated_at DESC")
    leads = db.list_leads(status=status, city=city, min_score=min_score, search=search, order_by=order, limit=1000)
    return render_template("leads.html", leads=leads, status=status, city=city or "", min_score=min_score or 0, search=search or "")


@bp.route("/leads/<int:lead_id>")
def lead_detail(lead_id: int):
    lead = db.get_lead(lead_id)
    if not lead:
        abort(404)
    interactions = db.list_interactions(lead_id)
    try:
        pain_points = json.loads(lead.get("pain_points") or "[]")
    except Exception:
        pain_points = []
    lead["pain_points_list"] = pain_points
    your_name = os.environ.get("YOUR_NAME", "")
    your_company = os.environ.get("YOUR_COMPANY", "")
    your_whatsapp = os.environ.get("YOUR_WHATSAPP", "")
    your_portfolio = os.environ.get("YOUR_PORTFOLIO_URL", "")
    messages = generate_outreach(lead, your_name, your_company, your_whatsapp, your_portfolio)
    return render_template("lead_detail.html", lead=lead, interactions=interactions, messages=messages)


@bp.route("/pipeline")
def pipeline_view():
    leads = db.list_leads(limit=1000)
    cols = {s: [] for s in db.PIPELINE_STATUSES + ["descartado"]}
    for l in leads:
        cols.setdefault(l["status"], []).append(l)
    return render_template("pipeline.html", cols=cols)


@bp.route("/scrape", methods=["GET", "POST"])
def scrape_view():
    if request.method == "POST":
        niche = (request.form.get("niche") or "").strip()
        city = (request.form.get("city") or "").strip()
        country = (request.form.get("country") or "BR").strip() or "BR"
        try:
            max_results = int(request.form.get("max_results") or 15)
        except ValueError:
            max_results = 15
        try:
            delay = float(request.form.get("delay") or 2.5)
        except ValueError:
            delay = 2.5
        enrich = bool(request.form.get("enrich_instagram"))
        provider = (request.form.get("provider") or "overpass").strip() or "overpass"

        if not niche or not city:
            flash("Preencha nicho e cidade.", "error")
            return redirect(url_for("main.scrape_view"))

        job_id = db.create_scrape_job(niche, city, country, max_results)

        def _run(job_id, niche, city, country, max_results, delay, enrich, provider):
            def progress(msg):
                try:
                    log.info("[scrape %s] %s", job_id, msg)
                except Exception:
                    pass
            try:
                res = scrape_pipeline.run_scrape(
                    niche=niche, city=city, country=country,
                    max_results=max_results, delay=delay,
                    enrich_instagram=enrich, provider=provider, progress_cb=progress,
                )
                db.finish_scrape_job(job_id, res.found, res.inserted, "; ".join(res.errors) if res.errors else None)
            except Exception as e:
                try:
                    log.exception("scrape %s falhou", job_id)
                except Exception:
                    pass
                try:
                    db.finish_scrape_job(job_id, 0, 0, str(e))
                except Exception:
                    pass

        t = threading.Thread(target=_run, args=(job_id, niche, city, country, max_results, delay, enrich, provider), daemon=True)
        t.start()
        flash(f"Coleta iniciada (job #{job_id}, provedor={provider}).", "info")
        return redirect(url_for("main.scrape_view"))

    jobs = db.list_recent_jobs(limit=15)
    return render_template("scrape.html", jobs=jobs,
                           default_country=os.environ.get("DEFAULT_COUNTRY", "BR"),
                           default_niche=os.environ.get("DEFAULT_NICHE", ""),
                           default_city=os.environ.get("DEFAULT_CITY", ""))


# ---------- Ações em lead ----------

@bp.route("/leads/<int:lead_id>/status", methods=["POST"])
def change_status(lead_id: int):
    new_status = request.form.get("status") or request.json.get("status")
    db.update_lead_status(lead_id, new_status)
    if request.accept_mimetypes.accept_json and not request.form:
        return jsonify({"ok": True, "status": new_status})
    return redirect(request.referrer or url_for("main.lead_detail", lead_id=lead_id))


@bp.route("/leads/<int:lead_id>/note", methods=["POST"])
def add_note(lead_id: int):
    body = (request.form.get("body") or "").strip()
    if not body:
        return redirect(request.referrer or url_for("main.lead_detail", lead_id=lead_id))
    db.add_interaction(lead_id, "note", body)
    return redirect(url_for("main.lead_detail", lead_id=lead_id) + "#notes")


@bp.route("/leads/<int:lead_id>/recheck", methods=["POST"])
def recheck(lead_id: int):
    lead = db.get_lead(lead_id)
    if not lead:
        abort(404)
    audit = audit_website(lead.get("website"))
    db.update_lead(lead_id, {
        "website_status": audit["status"],
        "website_score": audit["score"],
        "notes": "; ".join(audit.get("reasons", [])),
        "pain_points": json.dumps(audit.get("reasons", []), ensure_ascii=False),
    })
    flash(f"Reauditoria: score {audit['score']} ({audit['status']})", "info")
    return redirect(url_for("main.lead_detail", lead_id=lead_id))


@bp.route("/leads/<int:lead_id>/delete", methods=["POST"])
def delete_lead(lead_id: int):
    db.delete_lead(lead_id)
    flash("Lead removido.", "info")
    return redirect(url_for("main.leads_list"))


@bp.route("/leads/<int:lead_id>/edit", methods=["POST"])
def edit_lead(lead_id: int):
    fields = {
        "business_name": request.form.get("business_name"),
        "niche": request.form.get("niche"),
        "address": request.form.get("address"),
        "city": request.form.get("city"),
        "state": request.form.get("state"),
        "phone": request.form.get("phone"),
        "whatsapp": request.form.get("whatsapp"),
        "email": request.form.get("email"),
        "instagram": request.form.get("instagram"),
        "facebook": request.form.get("facebook"),
        "website": request.form.get("website"),
        "notes": request.form.get("notes"),
    }
    fields = {k: v for k, v in fields.items() if v is not None and v != ""}
    db.update_lead(lead_id, fields)
    flash("Lead atualizado.", "info")
    return redirect(url_for("main.lead_detail", lead_id=lead_id))


@bp.route("/leads/new", methods=["POST"])
def create_lead():
    fields = {
        "business_name": (request.form.get("business_name") or "").strip(),
        "niche": request.form.get("niche"),
        "address": request.form.get("address"),
        "city": request.form.get("city"),
        "state": request.form.get("state"),
        "country": request.form.get("country") or "BR",
        "phone": request.form.get("phone"),
        "whatsapp": request.form.get("whatsapp"),
        "email": request.form.get("email"),
        "instagram": request.form.get("instagram"),
        "website": request.form.get("website"),
        "source": "manual",
    }
    if not fields["business_name"]:
        flash("Nome do negócio é obrigatório.", "error")
        return redirect(url_for("main.leads_list"))
    lead_id, created = db.upsert_lead(fields)
    flash(f"{'Lead criado' if created else 'Lead já existia'} (#{lead_id}).", "info")
    return redirect(url_for("main.lead_detail", lead_id=lead_id))


# ---------- API JSON (pra integrações futuras) ----------

@bp.route("/api/leads")
def api_leads():
    status = request.args.get("status")
    city = request.args.get("city")
    min_score = request.args.get("min_score", type=int)
    return jsonify(db.list_leads(status=status, city=city, min_score=min_score, limit=1000))


@bp.route("/api/audit", methods=["POST"])
def api_audit():
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(audit_website(data.get("url")))


@bp.route("/api/cnpj/<cnpj>")
def api_cnpj(cnpj: str):
    return jsonify(cnpj_scraper.lookup_cnpj(cnpj) or {})


# ---------- Importar / Exportar ----------

@bp.route("/import", methods=["GET", "POST"])
def import_csv():
    if request.method == "POST":
        f = request.files.get("file")
        if not f:
            flash("Selecione um CSV.", "error")
            return redirect(url_for("main.import_csv"))
        text = io.StringIO(f.read().decode("utf-8", errors="ignore")).getvalue()
        reader = csv.DictReader(io.StringIO(text))
        inserted = updated = 0
        for row in reader:
            data = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            if not data.get("business_name"):
                continue
            data.setdefault("source", "csv")
            _, created = db.upsert_lead(data)
            if created:
                inserted += 1
            else:
                updated += 1
        flash(f"Importação: {inserted} novos, {updated} atualizados.", "info")
        return redirect(url_for("main.leads_list"))
    return render_template("import.html")


@bp.route("/export.csv")
def export_csv():
    status = request.args.get("status")
    min_score = request.args.get("min_score", type=int)
    leads = db.list_leads(status=status, min_score=min_score, limit=100000)
    output = io.StringIO()
    writer = csv.writer(output)
    cols = ["business_name", "niche", "city", "state", "country", "phone", "whatsapp",
            "email", "instagram", "website", "website_status", "website_score",
            "status", "notes", "address", "created_at"]
    writer.writerow(cols)
    for l in leads:
        writer.writerow([l.get(c) or "" for c in cols])
    output.seek(0)
    fname = f"leads-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"
    return send_file(io.BytesIO(output.getvalue().encode("utf-8-sig")), as_attachment=True,
                     download_name=fname, mimetype="text/csv")
