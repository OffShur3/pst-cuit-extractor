import json
import sqlite3
import subprocess
from pathlib import Path
from typing import List, Dict, Set

from src.config import BASE_DIR, DB_PATH

NODE_SCRIPT = BASE_DIR / "src" / "verifier" / "check_whatsapp_batch.js"

class WhatsAppVerifier:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = str(db_path)
        self._init_cache_table()

    def _init_cache_table(self):
        """Crea la tabla de caché para no consultar a WhatsApp dos veces por el mismo número."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS phone_verifications (
                    phone TEXT PRIMARY KEY,
                    has_whatsapp INTEGER,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def get_cached_verifications(self, phones: List[str]) -> Dict[str, bool]:
        """Recupera del caché local los números ya consultados."""
        if not phones:
            return {}
        clean_phones = [p.replace("+", "").replace("-", "").strip() for p in phones]
        placeholders = ",".join(["?"] * len(clean_phones))
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT phone, has_whatsapp FROM phone_verifications WHERE phone IN ({placeholders})",
                clean_phones
            ).fetchall()
            return {r["phone"]: bool(r["has_whatsapp"]) for r in rows}

    def save_verifications_to_cache(self, results: Dict[str, bool]):
        """Guarda en SQLite los nuevos números verificados."""
        if not results:
            return
        records = [(phone, 1 if has_wa else 0) for phone, has_wa in results.items()]
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO phone_verifications (phone, has_whatsapp, checked_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, records)

    def verify_phones_batch(self, raw_phones: List[str]) -> Dict[str, bool]:
        """
        Verifica una lista de números. Primero consulta SQLite.
        Los que falten, los envía a Baileys en una sola llamada de Node.js.
        """
        if not raw_phones:
            return {}

        clean_map = {}
        for p in raw_phones:
            c = p.replace("+", "").replace("-", "").strip()
            if c:
                clean_map[c] = p

        all_clean = list(clean_map.keys())
        results = self.get_cached_verifications(all_clean)

        # Números que aún no están en caché
        missing = [p for p in all_clean if p not in results]

        if missing:
            # Escribir archivo temporal para el script de Node
            temp_json = BASE_DIR / "data" / "_temp_verify.json"
            temp_json.parent.mkdir(exist_ok=True)
            temp_json.write_text(json.dumps(missing), encoding="utf-8")

            try:
                cmd = ["node", str(NODE_SCRIPT), str(temp_json)]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if res.stdout.strip():
                    new_verifications = json.loads(res.stdout.strip())
                    self.save_verifications_to_cache(new_verifications)
                    results.update(new_verifications)
            except Exception as e:
                print(f"⚠️ Error al consultar Baileys: {e}")
            finally:
                if temp_json.exists():
                    temp_json.unlink()

        return results

    def check_single(self, phone: str) -> bool:
        clean = phone.replace("+", "").replace("-", "").strip()
        res = self.verify_phones_batch([clean])
        return res.get(clean, False)
