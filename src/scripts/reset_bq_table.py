import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.integrations.bigquery_sync import BigQuerySyncManager

def reset():
    print("Iniciando reseteo de tabla en BigQuery...")
    manager = BigQuerySyncManager()
    manager.authenticate()
    manager.recreate_table()
    print("Sincronizando registros limpios...")
    total = manager.sync_all_pending()
    print(f"🎉 ¡Listo! Se subieron {total} registros con el orden de columnas perfecto.")

if __name__ == "__main__":
    reset()
