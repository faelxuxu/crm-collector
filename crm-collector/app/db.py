"""Camada de banco de dados SQLite.

Mantemos o banco em data/crm.db. Schema simples: leads, interactions, tags.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Iterable

DB_PATH = os.environ.get("CRM_DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "crm.db"))

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_name TEXT NOT NULL,
    niche TEXT,
    address TEXT,
    city TEXT,
    state TEXT,
    country TEXT,
    phone TEXT,
    whatsapp TEXT,
    email TEXT,
    instagram TEXT,
    facebook TEXT,
    website TEXT,
    website_status TEXT,         -- 'no_site' | 'broken' | 'slow' | 'no_mobile' | 'no_ssl' | 'ok'
    website_score INTEGER DEFAULT 0,  -- 0-100, quanto MAIOR mais precisa de site
    latitude REAL,
    longitude REAL,
    source TEXT,                 -- 'google_maps' | 'manual' | 'csv' | 'instagram'
    status TEXT DEFAULT 'novo',  -- 'novo' | 'contato' | 'proposta' | 'ganho' | 'perdido' | 'descartado'
    pipeline_order INTEGER DEFAULT 0,
    notes TEXT,
    pain_points TEXT,            -- JSON list
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    contacted_at TEXT,
    UNIQUE(business_name, city, country)
);

CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_city ON leads(city);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(website_score);

CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    kind TEXT,                   -- 'note' | 'call' | 'whatsapp' | 'email' | 'meeting'
    body TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_interactions_lead ON interactions(lead_id);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS lead_tags (
    lead_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (lead_id, tag_id),
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scrape_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    niche TEXT,
    city TEXT,
    country TEXT,
    max_results INTEGER,
    status TEXT DEFAULT 'pending',  -- 'pending' | 'running' | 'done' | 'error'
    found INTEGER DEFAULT 0,
    inserted INTEGER DEFAULT 0,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    finished_at TEXT
);
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn():
    with _lock:
        conn = _connect()
        try:
            # Garante schema mesmo se o arquivo foi recriado vazio
            conn.executescript(SCHEMA)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------- Helpers de alto nível ----------

PIPELINE_STATUSES = ["novo", "contato", "proposta", "ganho", "perdido"]


def upsert_lead(data: dict) -> tuple[int, bool]:
    """Insere ou atualiza lead por (business_name, city, country). Retorna (id, created)."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM leads WHERE business_name = ? AND IFNULL(city,'') = IFNULL(?, '') AND IFNULL(country,'') = IFNULL(?, '')",
            (data.get("business_name"), data.get("city"), data.get("country")),
        ).fetchone()
        now = datetime.utcnow().isoformat()
        if existing:
            lead_id = existing["id"]
            data = {k: v for k, v in data.items() if v not in (None, "", [])}
            data["updated_at"] = now
            if data:
                cols = ", ".join(f"{k} = ?" for k in data)
                vals = list(data.values()) + [lead_id]
                conn.execute(f"UPDATE leads SET {cols} WHERE id = ?", vals)
            return lead_id, False

        data = {k: v for k, v in data.items() if v not in (None, "", [])}
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        cur = conn.execute(
            f"INSERT INTO leads ({cols}) VALUES ({placeholders})",
            list(data.values()),
        )
        return cur.lastrowid, True


def get_lead(lead_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return dict(row) if row else None


def list_leads(
    status: str | None = None,
    city: str | None = None,
    min_score: int | None = None,
    search: str | None = None,
    order_by: str = "website_score DESC, updated_at DESC",
    limit: int = 500,
) -> list[dict]:
    q = "SELECT * FROM leads WHERE 1=1"
    params: list = []
    if status and status != "todos":
        q += " AND status = ?"
        params.append(status)
    if city:
        q += " AND city LIKE ?"
        params.append(f"%{city}%")
    if min_score is not None:
        q += " AND website_score >= ?"
        params.append(min_score)
    if search:
        q += " AND (business_name LIKE ? OR niche LIKE ? OR notes LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s])
    q += f" ORDER BY {order_by} LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(q, params).fetchall()]


def update_lead_status(lead_id: int, new_status: str) -> None:
    if new_status not in PIPELINE_STATUSES + ["descartado"]:
        raise ValueError(f"status inválido: {new_status}")
    with get_conn() as conn:
        now = datetime.utcnow().isoformat()
        contacted = ", contacted_at = ?" if new_status == "contato" else ""
        params: list = [new_status, now]
        if contacted:
            params.append(now)
        params.append(lead_id)
        conn.execute(
            f"UPDATE leads SET status = ?, updated_at = ?{contacted} WHERE id = ?",
            params,
        )


def update_lead(lead_id: int, fields: dict) -> None:
    if not fields:
        return
    fields["updated_at"] = datetime.utcnow().isoformat()
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [lead_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE leads SET {cols} WHERE id = ?", vals)


def delete_lead(lead_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))


def add_interaction(lead_id: int, kind: str, body: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO interactions (lead_id, kind, body) VALUES (?, ?, ?)",
            (lead_id, kind, body),
        )
        return cur.lastrowid


def list_interactions(lead_id: int) -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM interactions WHERE lead_id = ? ORDER BY created_at DESC",
            (lead_id,),
        ).fetchall()]


def dashboard_stats() -> dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
        no_site = conn.execute("SELECT COUNT(*) c FROM leads WHERE website_status = 'no_site' OR website IS NULL OR website = ''").fetchone()["c"]
        by_status = {row["status"]: row["c"] for row in conn.execute("SELECT status, COUNT(*) c FROM leads GROUP BY status").fetchall()}
        top_cities = [dict(r) for r in conn.execute("SELECT city, COUNT(*) c FROM leads WHERE city IS NOT NULL GROUP BY city ORDER BY c DESC LIMIT 5").fetchall()]
        avg_score = conn.execute("SELECT IFNULL(AVG(website_score), 0) a FROM leads").fetchone()["a"]
        high_intent = conn.execute("SELECT COUNT(*) c FROM leads WHERE website_score >= 70").fetchone()["c"]
    return {
        "total": total,
        "no_site": no_site,
        "high_intent": high_intent,
        "avg_score": round(avg_score, 1),
        "by_status": by_status,
        "top_cities": top_cities,
    }


def add_tag(name: str) -> int:
    with get_conn() as conn:
        try:
            cur = conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()["id"]


def list_tags() -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM tags ORDER BY name").fetchall()]


def tag_lead(lead_id: int, tag_id: int) -> None:
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO lead_tags (lead_id, tag_id) VALUES (?, ?)", (lead_id, tag_id))


def create_scrape_job(niche: str, city: str, country: str, max_results: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO scrape_jobs (niche, city, country, max_results, status) VALUES (?, ?, ?, ?, 'pending')",
            (niche, city, country, max_results),
        )
        return cur.lastrowid


def finish_scrape_job(job_id: int, found: int, inserted: int, error: str | None = None) -> None:
    with get_conn() as conn:
        status = "error" if error else "done"
        conn.execute(
            "UPDATE scrape_jobs SET status = ?, found = ?, inserted = ?, error = ?, finished_at = datetime('now') WHERE id = ?",
            (status, found, inserted, error, job_id),
        )


def get_scrape_job(job_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM scrape_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_recent_jobs(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM scrape_jobs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()]
