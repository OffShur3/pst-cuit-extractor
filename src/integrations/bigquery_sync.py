from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from google.cloud import bigquery
from google.cloud.exceptions import NotFound
from google.oauth2 import service_account

from src.config import (
    GCP_CREDENTIALS_PATH,
    DEFAULT_DATASET_ID,
    DEFAULT_TABLE_ID
)
from src.storage.db_manager import DatabaseManager


class BigQuerySyncManager:
    def __init__(
        self,
        credentials_path: Path = GCP_CREDENTIALS_PATH,
        dataset_id: str = DEFAULT_DATASET_ID,
        table_id: str = DEFAULT_TABLE_ID,
        db_manager: Optional[DatabaseManager] = None
    ):
        self.credentials_path = Path(credentials_path)
        self.dataset_id = dataset_id
        self.table_id = table_id
        self.db_manager = db_manager or DatabaseManager()
        self.client: Optional[bigquery.Client] = None
        self._table_ref = None

    def authenticate(self) -> bool:
        if not self.credentials_path.exists():
            raise FileNotFoundError(f"No se encontró el archivo: {self.credentials_path}")

        credentials = service_account.Credentials.from_service_account_file(
            str(self.credentials_path),
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        self.client = bigquery.Client(credentials=credentials, project=credentials.project_id)
        self._table_ref = bigquery.DatasetReference(self.client.project, self.dataset_id).table(self.table_id)
        return True

    def get_schema(self) -> List[bigquery.SchemaField]:
        """Define el orden comercial estricto y los tipos de datos correctos."""
        return [
            bigquery.SchemaField("cuit", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("razon_social", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("nombres", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("tier", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("terminales", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("telefonos", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("direcciones", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("mcs", "STRING", mode="NULLABLE"),  # OBLIGATORIO STRING
            bigquery.SchemaField("denominaciones", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("vendedores", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("otros", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("total_tickets", "INTEGER", mode="NULLABLE"),
            bigquery.SchemaField("ultimo_contacto", "STRING", mode="NULLABLE"),
        ]

    def recreate_table(self):
        """Fuerza el borrado y creación limpia de la tabla con el esquema ordenado."""
        if not self.client:
            self.authenticate()
        
        print("   🗑️ Eliminando tabla vieja en BigQuery para reordenar columnas...")
        self.client.delete_table(self._table_ref, not_found_ok=True)

        print("   ✨ Creando tabla con orden estricto (CUIT primero, MCS como texto)...")
        table = bigquery.Table(self._table_ref, schema=self.get_schema())
        table.clustering_fields = ["cuit"]
        self.client.create_table(table)
        print("   ✅ Tabla recreada correctamente.")

    def ensure_infrastructure(self):
        if not self.client:
            self.authenticate()

        dataset_ref = bigquery.DatasetReference(self.client.project, self.dataset_id)
        try:
            self.client.get_dataset(dataset_ref)
        except NotFound:
            dataset = bigquery.Dataset(dataset_ref)
            dataset.location = "southamerica-east1"
            self.client.create_dataset(dataset, timeout=30)

        try:
            self.client.get_table(self._table_ref)
        except NotFound:
            table = bigquery.Table(self._table_ref, schema=self.get_schema())
            table.clustering_fields = ["cuit"]
            self.client.create_table(table)

    def fetch_existing_bq_records(self) -> List[Dict[str, Any]]:
        try:
            table = self.client.get_table(self._table_ref)
            rows = self.client.list_rows(table)
            return [dict(r) for r in rows]
        except NotFound:
            return []

    def sync_all_pending(self, progress_callback: Optional[Callable[[int, int], None]] = None) -> int:
        self.ensure_infrastructure()

        rows = self.db_manager.get_all_consolidated_records()
        if not rows:
            return 0

        cols = [
            "cuit", "razon_social", "nombres", "tier", "terminales",
            "telefonos", "direcciones", "mcs", "denominaciones",
            "vendedores", "otros", "total_tickets", "ultimo_contacto"
        ]

        payload = []
        for r in rows:
            item = {}
            for c in cols:
                val = r[c]
                if c == "total_tickets":
                    item[c] = int(val or 1)
                else:
                    item[c] = str(val or "")
            payload.append(item)

        # Se envía con el esquema explícito en el job_config
        job_config = bigquery.LoadJobConfig(
            schema=self.get_schema(),
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )

        load_job = self.client.load_table_from_json(payload, self._table_ref, job_config=job_config)
        load_job.result()

        if load_job.errors:
            raise RuntimeError(f"Error en BigQuery: {load_job.errors}")

        self.db_manager.mark_all_synced()
        if progress_callback:
            progress_callback(len(payload), len(payload))

        return len(payload)
