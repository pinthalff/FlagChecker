"""
database.py — FlagChecker persistent database layer.

MySQL  → flagged_users table (structured user records)
MongoDB → rocleaner collection (646k imported Discord IDs + servers)

Railway env vars required:
  MySQL:   MYSQLHOST, MYSQLPORT, MYSQLUSER, MYSQLPASSWORD, MYSQLDATABASE
  MongoDB: MONGO_URL  (e.g. mongodb://user:pass@host:port)
"""
from __future__ import annotations

import json
import logging
import os
import gzip
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("bot.database")


# ── MySQL ──────────────────────────────────────────────────────────────────────

def _mysql_conn():
    import mysql.connector
    return mysql.connector.connect(
        host     = os.environ["MYSQLHOST"],
        port     = int(os.environ.get("MYSQLPORT", 3306)),
        user     = os.environ["MYSQLUSER"],
        password = os.environ["MYSQLPASSWORD"],
        database = os.environ["MYSQLDATABASE"],
    )


def mysql_setup():
    """Create tables if they don't exist. Call once at bot startup."""
    conn = _mysql_conn()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS flagged_users (
            discord_id   VARCHAR(32)  PRIMARY KEY,
            username     VARCHAR(255) NOT NULL DEFAULT '',
            sources      JSON         NOT NULL,
            servers      JSON         NOT NULL,
            added_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                      ON UPDATE CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    log.info("MySQL: flagged_users table ready")


def mysql_add_flagged_user(user_id: str, username: str, sources: list, servers: list) -> None:
    conn = _mysql_conn()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO flagged_users (discord_id, username, sources, servers, added_at)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            username   = VALUES(username),
            sources    = VALUES(sources),
            servers    = VALUES(servers),
            updated_at = CURRENT_TIMESTAMP
    """, (
        str(user_id),
        username,
        json.dumps(list(sources)),
        json.dumps(list(servers)[:20]),
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    ))
    conn.commit()
    cur.close()
    conn.close()


def mysql_remove_flagged_user(user_id: str) -> bool:
    conn = _mysql_conn()
    cur  = conn.cursor()
    cur.execute("DELETE FROM flagged_users WHERE discord_id = %s", (str(user_id),))
    affected = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return affected > 0


def mysql_get_flagged_user(user_id: str) -> Optional[dict]:
    conn = _mysql_conn()
    cur  = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM flagged_users WHERE discord_id = %s", (str(user_id),))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "discord_id": row["discord_id"],
        "username":   row["username"],
        "sources":    json.loads(row["sources"]) if isinstance(row["sources"], str) else row["sources"],
        "servers":    json.loads(row["servers"])  if isinstance(row["servers"],  str) else row["servers"],
        "added_at":   str(row["added_at"]),
    }


def mysql_is_flagged(user_id: str) -> bool:
    conn = _mysql_conn()
    cur  = conn.cursor()
    cur.execute("SELECT 1 FROM flagged_users WHERE discord_id = %s LIMIT 1", (str(user_id),))
    found = cur.fetchone() is not None
    cur.close()
    conn.close()
    return found


def mysql_list_flagged_users(limit: int = 50) -> list:
    conn = _mysql_conn()
    cur  = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT * FROM flagged_users ORDER BY added_at DESC LIMIT %s", (limit,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = []
    for row in rows:
        result.append({
            "discord_id": row["discord_id"],
            "username":   row["username"],
            "sources":    json.loads(row["sources"]) if isinstance(row["sources"], str) else row["sources"],
            "servers":    json.loads(row["servers"])  if isinstance(row["servers"],  str) else row["servers"],
            "added_at":   str(row["added_at"]),
        })
    return result


def mysql_flagged_count() -> int:
    conn = _mysql_conn()
    cur  = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM flagged_users")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count


# ── MongoDB ────────────────────────────────────────────────────────────────────

def _mongo_db():
    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGO_URL"])
    return client["flagchecker"]


def mongo_setup():
    """Create indexes. Call once at bot startup."""
    db = _mongo_db()
    db["rocleaner"].create_index("discord_id", unique=True)
    log.info("MongoDB: rocleaner collection ready")


def mongo_import_rocleaner(path: str) -> int:
    """
    Import the RoCleaner JSON/JSON.GZ file into MongoDB.
    Format: {"discord_id": ["server1", "server2"], ...}
    Only imports if collection is empty (won't re-import on every restart).
    Returns number of documents inserted (0 if already imported).
    """
    db         = _mongo_db()
    collection = db["rocleaner"]

    if collection.count_documents({}) > 0:
        count = collection.count_documents({})
        log.info("MongoDB: RoCleaner already imported (%d users), skipping", count)
        return 0

    # Load the file
    gz_path = path if path.endswith(".gz") else path + ".gz"
    if os.path.exists(gz_path):
        log.info("MongoDB: Loading RoCleaner from %s ...", gz_path)
        with gzip.open(gz_path, "rt", encoding="utf-8") as f:
            data = json.load(f)
    elif os.path.exists(path):
        log.info("MongoDB: Loading RoCleaner from %s ...", path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        log.warning("MongoDB: RoCleaner file not found at %s", path)
        return 0

    # Batch insert
    BATCH = 5000
    items = list(data.items())
    total = 0
    for i in range(0, len(items), BATCH):
        batch = items[i:i + BATCH]
        docs  = []
        for uid, servers in batch:
            if isinstance(servers, list):
                server_list = [{"name": s} if isinstance(s, str) else s for s in servers]
            else:
                server_list = []
            docs.append({"discord_id": str(uid), "servers": server_list})
        try:
            collection.insert_many(docs, ordered=False)
            total += len(docs)
        except Exception as exc:
            log.warning("MongoDB batch insert error: %s", exc)

    log.info("MongoDB: Imported %d RoCleaner users", total)
    return total


def mongo_get_rocleaner_servers(user_id: str) -> list:
    """Returns list of server dicts for a user, or [] if not found."""
    db  = _mongo_db()
    doc = db["rocleaner"].find_one({"discord_id": str(user_id)}, {"_id": 0, "servers": 1})
    if not doc:
        return []
    return [
        {"name": (s.get("name", "Unknown") if isinstance(s, dict) else str(s)),
         "id":   (s.get("id") if isinstance(s, dict) else None),
         "sources": ["RoCleaner"]}
        for s in doc.get("servers", [])
    ]


def mongo_is_rocleaner_flagged(user_id: str) -> bool:
    db = _mongo_db()
    return db["rocleaner"].count_documents({"discord_id": str(user_id)}, limit=1) > 0


def mongo_rocleaner_count() -> int:
    return _mongo_db()["rocleaner"].count_documents({})


# ── Unified setup ──────────────────────────────────────────────────────────────

_ROCLEANER_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "imported_flagged.json"
)

def setup_databases() -> dict:
    """
    Call at bot startup. Connects to both databases, creates tables/indexes,
    and imports RoCleaner if needed.
    Returns a status dict: {"mysql": bool, "mongodb": bool}
    """
    status = {"mysql": False, "mongodb": False}

    # MySQL
    try:
        mysql_setup()
        status["mysql"] = True
        log.info("MySQL: connected and ready")
    except Exception as exc:
        log.error("MySQL setup failed: %s", exc)

    # MongoDB
    try:
        mongo_setup()
        imported = mongo_import_rocleaner(_ROCLEANER_PATH)
        if imported:
            log.info("MongoDB: imported %d RoCleaner users", imported)
        status["mongodb"] = True
        log.info("MongoDB: connected and ready")
    except Exception as exc:
        log.error("MongoDB setup failed: %s", exc)

    return status


# ── Unified DatabaseLayer (used by storage.py) ─────────────────────────────────

class DatabaseLayer:
    """Thin wrapper so storage.py calls one object instead of bare functions."""

    # Flagged users (MySQL)
    def add_flagged_user(self, user_id, username, sources, servers):
        mysql_add_flagged_user(user_id, username, sources, servers)
    def remove_flagged_user(self, user_id) -> bool:
        return mysql_remove_flagged_user(user_id)
    def get_flagged_user(self, user_id):
        return mysql_get_flagged_user(user_id)
    def is_flagged(self, user_id) -> bool:
        return mysql_is_flagged(user_id)
    def list_flagged_users(self, limit=50) -> list:
        return mysql_list_flagged_users(limit)
    def flagged_count(self) -> int:
        return mysql_flagged_count()

    # RoCleaner (MongoDB)
    def get_rocleaner_servers(self, user_id) -> list:
        return mongo_get_rocleaner_servers(user_id)
    def is_rocleaner_flagged(self, user_id) -> bool:
        return mongo_is_rocleaner_flagged(user_id)
    def rocleaner_count(self) -> int:
        return mongo_rocleaner_count()
