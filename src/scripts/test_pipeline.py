import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.extractor.pst_reader import PSTReader
from src.parser.regex_engine import extract_ticket_data
from src.storage.db_manager import DatabaseManager
from src.integrations.bigquery_sync import BigQuerySyncManager
from src.config import GCP_CREDENTIALS_PATH

def test_pipeline(pst_path_str: str, test_bigquery: bool = False, reset_bq: bool = False):
    pst_path = Path(pst_path_str)
    if not pst_path.exists():
        print(f"❌ Error: El archivo PST no existe en {pst_path}")
        return

    print("=" * 60)
    print("🚀 INICIANDO PRUEBA DEL PIPELINE (1 FILA POR CORREO)")
    print("=" * 60)

    db = DatabaseManager()
    pst_id = pst_path.name

    checkpoint = db.get_checkpoint(pst_id)
    skip_count = 0
    if checkpoint:
        processed, total, completed = checkpoint
        print(f"   ℹ️ Checkpoint: {processed}/{total} procesados (Completado: {completed})")
        if not completed:
            skip_count = processed

    start_time = time.time()
    with PSTReader(pst_path) as reader:
        total_messages = reader.count_total_messages()
        print(f"   📬 Total de correos en el PST: {total_messages:,}")

        batch_records = []
        cuit_counter = 0
        processed_count = skip_count

        for msg in reader.iter_messages(skip_count=skip_count):
            processed_count += 1
            data = extract_ticket_data(msg["subject"], msg["body"])
            if data:
                data["fecha_email"] = msg["delivery_time"]
                data["mail_id"] = msg["message_id"]
                batch_records.append(data)

            if len(batch_records) >= 500 or processed_count % 50 == 0:
                if batch_records:
                    inserted = db.save_records_batch(batch_records)
                    cuit_counter += inserted
                    batch_records.clear()
                db.update_checkpoint(pst_id, processed_count, total_messages, completed=False)
                print(f"   ⏳ Progreso: {processed_count:,}/{total_messages:,} | Filas nuevas: {cuit_counter:,}", end="\r")

        if batch_records:
            inserted = db.save_records_batch(batch_records)
            cuit_counter += inserted
            batch_records.clear()

        db.update_checkpoint(pst_id, processed_count, total_messages, completed=True)
        elapsed = time.time() - start_time
        print(f"\n   ✅ Extracción finalizada en {elapsed:.2f}s.")
        print(f"   📊 Correos procesados: {processed_count:,} | Filas listas para BigQuery: {cuit_counter:,}")

    if test_bigquery:
        print("\n[BigQuery] Sincronizando datos...")
        bq = BigQuerySyncManager(db_manager=db)
        bq.authenticate()
        if reset_bq:
            bq.recreate_table()
        else:
            bq.ensure_infrastructure()
        synced = bq.sync_all_pending()
        print(f"   ✅ Se subieron {synced} filas a BigQuery.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m src.scripts.test_pipeline <archivo.pst> [--bigquery] [--reset-bq]")
    else:
        pst = sys.argv[1]
        with_bq = "--bigquery" in sys.argv
        with_reset = "--reset-bq" in sys.argv
        test_pipeline(pst, test_bigquery=with_bq, reset_bq=with_reset)
