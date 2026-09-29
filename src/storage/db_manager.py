import sqlite3
from typing import List, Dict, Optional, Tuple, Set
from pathlib import Path
from src.config import DB_PATH

class DatabaseManager:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = str(db_path)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS email_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cuit TEXT NOT NULL,
                    razon_social TEXT,
                    nombre TEXT,
                    tier TEXT,
                    terminal TEXT,
                    mc TEXT,
                    denominacion TEXT,
                    calle TEXT,
                    altura TEXT,
                    piso TEXT,
                    departamento TEXT,
                    codigo_postal TEXT,
                    localidad TEXT,
                    provincia TEXT,
                    telefono TEXT,
                    vendedor TEXT,
                    otros TEXT,
                    fecha_email TEXT,
                    mail_id TEXT NOT NULL UNIQUE,
                    synced_to_bq INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_records_cuit ON email_records(cuit);
                CREATE INDEX IF NOT EXISTS idx_records_mailid ON email_records(mail_id);
                CREATE INDEX IF NOT EXISTS idx_records_synced ON email_records(synced_to_bq);

                CREATE TABLE IF NOT EXISTS processing_checkpoint (
                    pst_identifier TEXT PRIMARY KEY,
                    total_messages INTEGER DEFAULT 0,
                    processed_messages INTEGER DEFAULT 0,
                    completed INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def save_records_batch(self, records: List[Dict]) -> int:
        if not records:
            return 0
        query = """
            INSERT OR IGNORE INTO email_records 
            (cuit, razon_social, nombre, tier, terminal, mc, denominacion,
             calle, altura, piso, departamento, codigo_postal, localidad, provincia,
             telefono, vendedor, otros, fecha_email, mail_id)
            VALUES 
            (:cuit, :razon_social, :nombre, :tier, :terminal, :mc, :denominacion,
             :calle, :altura, :piso, :departamento, :codigo_postal, :localidad, :provincia,
             :telefono, :vendedor, :otros, :fecha_email, :mail_id)
        """
        with self.get_connection() as conn:
            cursor = conn.executemany(query, records)
            return cursor.rowcount

    def get_pending_bq_records(self, limit: int = 5000) -> List[sqlite3.Row]:
        query = "SELECT * FROM email_records WHERE synced_to_bq = 0 LIMIT ?"
        with self.get_connection() as conn:
            return conn.execute(query, (limit,)).fetchall()

    def mark_records_synced(self, record_ids: List[int]):
        if not record_ids:
            return
        query = "UPDATE email_records SET synced_to_bq = 1 WHERE id = ?"
        with self.get_connection() as conn:
            conn.executemany(query, [(rid,) for rid in record_ids])

    def mark_all_unsynced(self):
        with self.get_connection() as conn:
            conn.execute("UPDATE email_records SET synced_to_bq = 0")

    def mark_already_in_bq(self, existing_mail_ids: Set[str]):
        """Marca como ya sincronizados en SQLite los mail_ids que ya existen en BigQuery."""
        if not existing_mail_ids:
            return
        query = "UPDATE email_records SET synced_to_bq = 1 WHERE mail_id = ?"
        with self.get_connection() as conn:
            conn.executemany(query, [(mid,) for mid in existing_mail_ids])

    def count_total_records(self) -> int:
        with self.get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM email_records").fetchone()[0]

    def update_checkpoint(self, pst_id: str, processed: int, total: int, completed: bool = False):
        query = """
            INSERT INTO processing_checkpoint (pst_identifier, total_messages, processed_messages, completed, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(pst_identifier) DO UPDATE SET
                processed_messages = excluded.processed_messages,
                total_messages = excluded.total_messages,
                completed = excluded.completed,
                updated_at = CURRENT_TIMESTAMP;
        """
        with self.get_connection() as conn:
            conn.execute(query, (pst_id, total, processed, 1 if completed else 0))

    def get_checkpoint(self, pst_id: str) -> Optional[Tuple[int, int, bool]]:
        query = "SELECT processed_messages, total_messages, completed FROM processing_checkpoint WHERE pst_identifier = ?"
        with self.get_connection() as conn:
            row = conn.execute(query, (pst_id,)).fetchone()
            return (row["processed_messages"], row["total_messages"], bool(row["completed"])) if row else None
