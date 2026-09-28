import sys
import time
from pathlib import Path

# Asegurar raíz del proyecto en sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.extractor.pst_reader import PSTReader
from src.parser.regex_engine import extract_ticket_data
from src.storage.db_manager import DatabaseManager
from src.integrations.bigquery_sync import BigQuerySyncManager
from src.config import GCP_CREDENTIALS_PATH

def test_pipeline(pst_path_str: str, test_bigquery: bool = False):
    pst_path = Path(pst_path_str)
    if not pst_path.exists():
        print(f"❌ Error: El archivo PST no existe en {pst_path}")
        return

    print("=" * 60)
    print("🚀 INICIANDO PRUEBA DEL PIPELINE (Fases 1, 2 y 3)")
    print("=" * 60)

    # 1. Inicializar Base de Datos Local
    print("\n[1/4] Inicializando SQLite local...")
    db = DatabaseManager()
    pst_id = pst_path.name

    checkpoint = db.get_checkpoint(pst_id)
    skip_count = 0
    if checkpoint:
        processed, total, completed = checkpoint
        print(f"   ℹ️ Checkpoint encontrado: {processed}/{total} procesados (Completado: {completed})")
        if not completed:
            skip_count = processed
            print(f"   🔁 Reanudando desde el mensaje {skip_count + 1}...")
    else:
        print("   ℹ️ Sin checkpoint previo, procesando desde el inicio.")

    # 2. Conteo de Mensajes en el PST
    print("\n[2/4] Abriendo PST y contando mensajes...")
    start_time = time.time()
    with PSTReader(pst_path) as reader:
        total_messages = reader.count_total_messages()
        print(f"   📬 Total de correos en el PST: {total_messages:,}")

        # 3. Procesamiento y Extracción
        print("\n[3/4] Extrayendo datos fiscales y guardando en SQLite...")
        batch_records = []
        cuit_counter = 0
        processed_count = skip_count

        for msg in reader.iter_messages(skip_count=skip_count):
            processed_count += 1
            
            # Extraer todos los campos estructurados del correo
            data = extract_ticket_data(msg["subject"], msg["body"])
            if data:
                data["message_id"] = msg["message_id"]
                data["subject"] = msg["subject"][:200]
                data["email_date"] = msg["delivery_time"]
                batch_records.append(data)
                cuit_counter += 1

            # Guardar en SQLite cada 500 registros o cada 100 correos
            if len(batch_records) >= 500 or processed_count % 100 == 0:
                if batch_records:
                    db.save_records_batch(batch_records)
                    batch_records.clear()
                db.update_checkpoint(pst_id, processed_count, total_messages, completed=False)
                print(f"   ⏳ Progreso: {processed_count:,}/{total_messages:,} correos | Tickets encontrados: {cuit_counter:,}", end="\r")

        # Guardar registros remanentes
        if batch_records:
            db.save_records_batch(batch_records)
            batch_records.clear()

        db.update_checkpoint(pst_id, processed_count, total_messages, completed=True)
        print("\n   🔄 Consolidando tickets por CUIT único...")
        total_consolidados = db.consolidate_clients()

        elapsed = time.time() - start_time
        print(f"   ✅ Extracción completada en {elapsed:.2f}s.")
        print(f"   📊 Correos procesados: {processed_count:,} | Clientes únicos consolidados: {total_consolidados:,}")

    # 4. Prueba opcional de BigQuery
    if test_bigquery:
        print("\n[4/4] Probando conexión y sincronización con BigQuery...")
        if not GCP_CREDENTIALS_PATH.exists():
            print(f"   ⚠️ No se encontró {GCP_CREDENTIALS_PATH.name}. Salteando prueba de BigQuery.")
        else:
            try:
                bq_manager = BigQuerySyncManager(db_manager=db)
                print("   🔑 Autenticando con Service Account...")
                bq_manager.authenticate()
                print("   🛠️ Asegurando Dataset y Tabla en BigQuery...")
                bq_manager.ensure_infrastructure()
                print("   ⬆️ Sincronizando registros pendientes...")
                synced = bq_manager.sync_all_pending(
                    progress_callback=lambda batch, total: print(f"      Subidos {total} registros...", end="\r")
                )
                print(f"\n   ✅ Éxito en BigQuery: {synced} registros sincronizados.")
            except Exception as e:
                print(f"\n   ❌ Error en BigQuery: {e}")
    else:
        print("\n[4/4] Salteando prueba de BigQuery (usa --bigquery si quieres probar la subida).")

    print("\n" + "=" * 60)
    print("🎉 PRUEBA FINALIZADA")
    print("=" * 60)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m src.scripts.test_pipeline <ruta_al_archivo.pst> [--bigquery]")
    else:
        pst_file = sys.argv[1]
        with_bq = "--bigquery" in sys.argv
        test_pipeline(pst_file, test_bigquery=with_bq)
