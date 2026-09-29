from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Set
from google.cloud import bigquery
from google.cloud.exceptions import NotFound
from google.oauth2 import service_account

from src.config import (
    GCP_CREDENTIALS_PATH,
    DEFAULT_DATASET_ID,
    DEFAULT_TABLE_ID,
    BATCH_SIZE
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
        # 19 columnas: datos de negocio + mail_id al final
        return [
            bigquery.SchemaField("cuit", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("razon_social", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("nombre", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("tier", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("terminal", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("mc", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("denominacion", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("calle", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("altura", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("piso", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("departamento", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("codigo_postal", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("localidad", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("provincia", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("telefono", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("vendedor", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("otros", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("fecha_email", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("mail_id", "STRING", mode="NULLABLE"),  # Columna 19 para trazabilidad
        ]

    def recreate_table(self):
        if not self.client:
            self.authenticate()
        print("   🗑️ Eliminando tabla previa en BigQuery...")
        self.client.delete_table(self._table_ref, not_found_ok=True)
        print("   ✨ Creando tabla nueva con mail_id como columna 19...")
        table = bigquery.Table(self._table_ref, schema=self.get_schema())
        table.clustering_fields = ["cuit"]
        self.client.create_table(table)
        self.db_manager.mark_all_unsynced()
        print("   ✅ Tabla lista y registros locales reiniciados para sincronizar.")

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

    def get_existing_mail_ids(self) -> Set[str]:
        """Descarga únicamente los mail_id presentes en BigQuery (rápido y gratuito)."""
        try:
            table = self.client.get_table(self._table_ref)
            rows = self.client.list_rows(table, selected_fields=[
                bigquery.SchemaField("mail_id", "STRING")
            ])
            return {str(r["mail_id"]) for r in rows if r["mail_id"]}
        except NotFound:
            return set()

    def sync_batch(self, batch_size: int = BATCH_SIZE) -> int:
        self.ensure_infrastructure()

        rows = self.db_manager.get_pending_bq_records(limit=batch_size)
        if not rows:
            return 0

        cols = [
            "cuit", "razon_social", "nombre", "tier", "terminal", "mc",
            "denominacion", "calle", "altura", "piso", "departamento",
            "codigo_postal", "localidad", "provincia", "telefono",
            "vendedor", "otros", "fecha_email", "mail_id"
        ]

        payload = []
        record_ids = []
        for r in rows:
            record_ids.append(r["id"])
            item = {c: str(r[c] or "") for c in cols}
            payload.append(item)

        job_config = bigquery.LoadJobConfig(
            schema=self.get_schema(),
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )

        load_job = self.client.load_table_from_json(payload, self._table_ref, job_config=job_config)
        load_job.result()

        if load_job.errors:
            raise RuntimeError(f"Error en BigQuery: {load_job.errors}")

        self.db_manager.mark_records_synced(record_ids)
        return len(record_ids)

    def sync_all_pending(self, progress_callback: Optional[Callable[[int, int], None]] = None) -> int:
        self.ensure_infrastructure()

        # Comprobar qué mail_ids ya existen en la nube para no duplicar jamás
        cloud_ids = self.get_existing_mail_ids()
        if cloud_ids:
            self.db_manager.mark_already_in_bq(cloud_ids)

        total_synced = 0
        while True:
            synced = self.sync_batch(batch_size=BATCH_SIZE)
            if synced == 0:
                break
            total_synced += synced
            if progress_callback:
                progress_callback(synced, total_synced)

        return total_synced
