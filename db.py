import json
import os

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")

psycopg2.extras.register_default_json(loads=json.loads, globally=True)
psycopg2.extras.register_default_jsonb(loads=json.loads, globally=True)


def get_conn():
    if not DB_URL:
        raise RuntimeError("DATABASE_URL is not set.")
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def create_claimant(full_name, email, phone=None, national_id=None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO claimants (full_name, email, phone, national_id)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (full_name, email, phone, national_id),
        )
        return cur.fetchone()["id"]


def create_claim(claimant_id, drive_folder_id=None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO claims (claimant_id, drive_folder_id)
            VALUES (%s, %s) RETURNING id
            """,
            (claimant_id, drive_folder_id),
        )
        return cur.fetchone()["id"]


def set_claim_status(claim_id, status):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE claims
            SET status = %s
            WHERE id = %s
            """,
            (status, claim_id),
        )


def save_result(claim_id, result: dict):
    triage = result.get("triage_card", {})
    verdict = triage.get("verdict")
    docs = triage.get("documents_processed", [])
    errors = []

    prosecutor = result.get("prosecutor", {})
    if isinstance(prosecutor, dict) and prosecutor.get("agent_error"):
        errors.append({"source": "prosecutor", "detail": prosecutor.get("error_detail")})

    defender = result.get("defender", {})
    if isinstance(defender, dict) and defender.get("agent_error"):
        errors.append({"source": "defender", "detail": defender.get("error_detail")})

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE claims SET
                status         = 'complete',
                verdict        = %s,
                result_json    = %s,
                documents_json = %s,
                error_log      = %s
            WHERE id = %s
            """,
            (
                verdict,
                psycopg2.extras.Json(result),
                psycopg2.extras.Json(docs),
                psycopg2.extras.Json(errors) if errors else None,
                claim_id,
            ),
        )


def save_error(claim_id, error_detail: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE claims SET status = 'error', error_log = %s WHERE id = %s
            """,
            (psycopg2.extras.Json({"error": error_detail}), claim_id),
        )


def worker_decision(claim_id, decision: str, notes: str = None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE claims SET
                status          = %s,
                worker_decision = %s,
                worker_notes    = %s,
                reviewed_at     = NOW()
            WHERE id = %s
            """,
            (decision, decision, notes, claim_id),
        )


def get_all_claims():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.status, c.verdict, c.submitted_at, c.reviewed_at,
                   c.drive_folder_id, c.documents_json, c.result_json,
                   c.error_log, c.worker_decision, c.worker_notes,
                   cl.full_name, cl.email, cl.phone, cl.national_id
            FROM claims c JOIN claimants cl ON c.claimant_id = cl.id
            ORDER BY c.submitted_at DESC
            """
        )
        return cur.fetchall()


def get_claim_detail(claim_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.*, cl.full_name, cl.email, cl.phone, cl.national_id
            FROM claims c JOIN claimants cl ON c.claimant_id = cl.id
            WHERE c.id = %s
            """,
            (claim_id,),
        )
        return cur.fetchone()