import sqlite3
from typing import List, Dict, Optional, Tuple, Any
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
                CREATE TABLE IF NOT EXISTS extracted_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tier TEXT,
                    vendedor_codigo_nombre TEXT,
                    cuit TEXT NOT NULL,
                    razon_social TEXT,
                    nombre TEXT,
                    direccion_instalacion TEXT,
                    telefono TEXT,
                    terminal TEXT,
                    mc TEXT,
                    denominacion TEXT,
                    otros TEXT,
                    message_id TEXT,
                    subject TEXT,
                    email_date TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(cuit, message_id)
                );

                CREATE TABLE IF NOT EXISTS consolidated_clients (
                    cuit TEXT PRIMARY KEY,
                    razon_social TEXT,
                    nombres TEXT,
                    tier TEXT,
                    vendedores TEXT,
                    direcciones TEXT,
                    telefonos TEXT,
                    terminales TEXT,
                    mcs TEXT,
                    denominaciones TEXT,
                    otros TEXT,
                    total_tickets INTEGER DEFAULT 0,
                    ultimo_contacto TEXT,
                    synced_to_bq INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

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
            INSERT OR IGNORE INTO extracted_records 
            (tier, vendedor_codigo_nombre, cuit, razon_social, nombre, direccion_instalacion,
             telefono, terminal, mc, denominacion, otros, message_id, subject, email_date)
            VALUES 
            (:tier, :vendedor_codigo_nombre, :cuit, :razon_social, :nombre, :direccion_instalacion,
             :telefono, :terminal, :mc, :denominacion, :otros, :message_id, :subject, :email_date)
        """
        with self.get_connection() as conn:
            return conn.executemany(query, records).rowcount

    def merge_external_records(self, external_rows: List[Dict[str, Any]]):
        """Fusiona registros provenientes de BigQuery con la base local para no perder historial previo."""
        if not external_rows:
            return
        
        def to_set(text: Optional[str], sep: str = ",") -> set:
            if not text:
                return set()
            return {item.strip() for item in str(text).split(sep) if item.strip()}

        with self.get_connection() as conn:
            for er in external_rows:
                cuit = er.get("cuit")
                if not cuit:
                    continue
                
                row = conn.execute("SELECT * FROM consolidated_clients WHERE cuit = ?", (cuit,)).fetchone()
                if row:
                    # Unir listas existentes
                    nombres = to_set(row["nombres"], ",") | to_set(er.get("nombres"), ",")
                    vendedores = to_set(row["vendedores"], "|") | to_set(er.get("vendedores"), "|")
                    direcciones = to_set(row["direcciones"], "|") | to_set(er.get("direcciones"), "|")
                    telefonos = to_set(row["telefonos"], ",") | to_set(er.get("telefonos"), ",")
                    terminales = to_set(row["terminales"], ",") | to_set(er.get("terminales"), ",")
                    mcs = to_set(row["mcs"], ",") | to_set(er.get("mcs"), ",")
                    denominaciones = to_set(row["denominaciones"], ",") | to_set(er.get("denominaciones"), ",")
                    otros = to_set(row["otros"], "|") | to_set(er.get("otros"), "|")
                    
                    ultimo = max(str(row["ultimo_contacto"] or ""), str(er.get("ultimo_contacto") or ""))
                    razon = er.get("razon_social") or row["razon_social"]
                    tier = er.get("tier") or row["tier"]
                    total = (row["total_tickets"] or 0)

                    conn.execute("""
                        UPDATE consolidated_clients SET
                            razon_social = ?, nombres = ?, tier = ?, vendedores = ?,
                            direcciones = ?, telefonos = ?, terminales = ?, mcs = ?,
                            denominaciones = ?, otros = ?, ultimo_contacto = ?
                        WHERE cuit = ?
                    """, (
                        razon, ", ".join(sorted(nombres)), tier, " | ".join(sorted(vendedores)),
                        " | ".join(sorted(direcciones)), ", ".join(sorted(telefonos)),
                        ", ".join(sorted(terminales)), ", ".join(sorted(mcs)),
                        ", ".join(sorted(denominaciones)), " | ".join(sorted(otros)),
                        ultimo, cuit
                    ))
                else:
                    # Insertar nuevo registro traído de BigQuery
                    conn.execute("""
                        INSERT INTO consolidated_clients (
                            cuit, razon_social, nombres, tier, vendedores, direcciones,
                            telefonos, terminales, mcs, denominaciones, otros, total_tickets, ultimo_contacto, synced_to_bq
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """, (
                        cuit, er.get("razon_social", ""), er.get("nombres", ""),
                        er.get("tier", ""), er.get("vendedores", ""), er.get("direcciones", ""),
                        er.get("telefonos", ""), er.get("terminales", ""), er.get("mcs", ""),
                        er.get("denominaciones", ""), er.get("otros", ""),
                        int(er.get("total_tickets", 1) or 1), er.get("ultimo_contacto", "")
                    ))

    def consolidate_clients(self) -> int:
        with self.get_connection() as conn:
            existing_rows = conn.execute("SELECT * FROM consolidated_clients").fetchall()
            clients: Dict[str, Dict] = {}

            def to_set(text: Optional[str], sep: str = ",") -> set:
                if not text:
                    return set()
                return {item.strip() for item in str(text).split(sep) if item.strip()}

            for er in existing_rows:
                clients[er["cuit"]] = {
                    "cuit": er["cuit"],
                    "razon_social": er["razon_social"] or "",
                    "tier": er["tier"] or "",
                    "nombres": to_set(er["nombres"], ","),
                    "vendedores": to_set(er["vendedores"], "|"),
                    "direcciones": to_set(er["direcciones"], "|"),
                    "telefonos": to_set(er["telefonos"], ","),
                    "terminales": to_set(er["terminales"], ","),
                    "mcs": to_set(er["mcs"], ","),
                    "denominaciones": to_set(er["denominaciones"], ","),
                    "otros": to_set(er["otros"], "|"),
                    "total_tickets": er["total_tickets"] or 0,
                    "ultimo_contacto": er["ultimo_contacto"] or ""
                }

            rows = conn.execute("SELECT * FROM extracted_records ORDER BY email_date ASC").fetchall()
            for r in rows:
                cuit = r["cuit"]
                if cuit not in clients:
                    clients[cuit] = {
                        "cuit": cuit,
                        "razon_social": r["razon_social"] or "",
                        "tier": r["tier"] or "",
                        "nombres": set(),
                        "vendedores": set(),
                        "direcciones": set(),
                        "telefonos": set(),
                        "terminales": set(),
                        "mcs": set(),
                        "denominaciones": set(),
                        "otros": set(),
                        "total_tickets": 0,
                        "ultimo_contacto": r["email_date"] or ""
                    }
                c = clients[cuit]
                c["total_tickets"] += 1
                if r["razon_social"]: c["razon_social"] = r["razon_social"]
                if r["tier"]: c["tier"] = r["tier"]
                if r["nombre"]: c["nombres"].add(r["nombre"].strip())
                if r["vendedor_codigo_nombre"]: c["vendedores"].add(r["vendedor_codigo_nombre"].strip())
                if r["direccion_instalacion"]: c["direcciones"].add(r["direccion_instalacion"].strip())
                if r["telefono"]: c["telefonos"].add(r["telefono"].strip())
                if r["terminal"]: c["terminales"].add(r["terminal"].strip())
                if r["mc"]: c["mcs"].add(r["mc"].strip())
                if r["denominacion"]: c["denominaciones"].add(r["denominacion"].strip())
                if r["otros"]: c["otros"].add(r["otros"].strip())
                if r["email_date"] and r["email_date"] > c["ultimo_contacto"]:
                    c["ultimo_contacto"] = r["email_date"]

            upsert_query = """
                INSERT INTO consolidated_clients 
                (cuit, razon_social, nombres, tier, vendedores, direcciones, telefonos, terminales, mcs, denominaciones, otros, total_tickets, ultimo_contacto, synced_to_bq)
                VALUES 
                (:cuit, :razon_social, :nombres, :tier, :vendedores, :direcciones, :telefonos, :terminales, :mcs, :denominaciones, :otros, :total_tickets, :ultimo_contacto, 0)
                ON CONFLICT(cuit) DO UPDATE SET
                    razon_social = excluded.razon_social,
                    nombres = excluded.nombres,
                    tier = excluded.tier,
                    vendedores = excluded.vendedores,
                    direcciones = excluded.direcciones,
                    telefonos = excluded.telefonos,
                    terminales = excluded.terminales,
                    mcs = excluded.mcs,
                    denominaciones = excluded.denominaciones,
                    otros = excluded.otros,
                    total_tickets = excluded.total_tickets,
                    ultimo_contacto = excluded.ultimo_contacto,
                    synced_to_bq = 0,
                    updated_at = CURRENT_TIMESTAMP;
            """
            payload = []
            for c in clients.values():
                payload.append({
                    "cuit": c["cuit"],
                    "razon_social": c["razon_social"],
                    "nombres": ", ".join(sorted(c["nombres"])),
                    "tier": c["tier"],
                    "vendedores": " | ".join(sorted(c["vendedores"])),
                    "direcciones": " | ".join(sorted(c["direcciones"])),
                    "telefonos": ", ".join(sorted(c["telefonos"])),
                    "terminales": ", ".join(sorted(c["terminales"])),
                    "mcs": ", ".join(sorted(c["mcs"])),
                    "denominaciones": ", ".join(sorted(c["denominaciones"])),
                    "otros": " | ".join(sorted(c["otros"])),
                    "total_tickets": c["total_tickets"],
                    "ultimo_contacto": c["ultimo_contacto"]
                })
            conn.executemany(upsert_query, payload)
            return len(payload)

    def get_all_consolidated_records(self) -> List[sqlite3.Row]:
        """Obtiene todos los registros consolidados para sincronizar."""
        query = "SELECT * FROM consolidated_clients"
        with self.get_connection() as conn:
            return conn.execute(query).fetchall()

    def mark_all_synced(self):
        query = "UPDATE consolidated_clients SET synced_to_bq = 1"
        with self.get_connection() as conn:
            conn.execute(query)

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
