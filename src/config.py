import os
import sys
from pathlib import Path

def get_base_dir() -> Path:
    """Retorna la ruta base del proyecto o del ejecutable empaquetado."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Rutas de base de datos local y credenciales de BigQuery
DB_PATH = DATA_DIR / "extraction_cache.db"
GCP_CREDENTIALS_PATH = BASE_DIR / "service_account.json"

# Parámetros por defecto para BigQuery
DEFAULT_DATASET_ID = "pst_extraction_data"
DEFAULT_TABLE_ID = "gcnet-database"  # Sin espacio al final
BATCH_SIZE = 5000  # Tamaño del lote para inserción en SQLite y BigQuery
