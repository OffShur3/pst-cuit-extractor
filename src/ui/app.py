import sys
import threading
import time
from pathlib import Path
from typing import Optional
import customtkinter as ctk
from tkinter import filedialog, messagebox

from src.extractor.pst_reader import PSTReader
from src.parser.regex_engine import extract_ticket_data
from src.storage.db_manager import DatabaseManager
from src.integrations.bigquery_sync import BigQuerySyncManager

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("PST CUIT Extractor - Enterprise Data Management")
        window_width = 500
        window_height = 640
        self.minsize(460, 560)

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        self.geometry(f"{window_width}x{window_height}+{x}+{y}")

        self.db = DatabaseManager()
        self.is_running = False
        self.stop_requested = False
        self.selected_pst: Optional[Path] = None

        self._build_ui()

    def _build_ui(self):
        self.header = ctk.CTkFrame(self, corner_radius=8, fg_color="transparent")
        self.header.pack(fill="x", padx=16, pady=(16, 6))

        self.title_lbl = ctk.CTkLabel(
            self.header,
            text="Extractor de Correos & CUITs",
            font=ctk.CTkFont(size=17, weight="bold")
        )
        self.title_lbl.pack(anchor="w")

        self.desc_lbl = ctk.CTkLabel(
            self.header,
            text="Procesamiento granular, validación AFIP y sincronización en BigQuery.",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.desc_lbl.pack(anchor="w")

        self.file_card = ctk.CTkFrame(self, corner_radius=8)
        self.file_card.pack(fill="x", padx=16, pady=6)

        self.file_path_entry = ctk.CTkEntry(
            self.file_card,
            placeholder_text="Seleccione archivo .pst...",
            height=32,
            font=ctk.CTkFont(size=11)
        )
        self.file_path_entry.pack(fill="x", padx=12, pady=(10, 6))

        self.btn_browse = ctk.CTkButton(
            self.file_card,
            text="Examinar archivo PST",
            height=28,
            font=ctk.CTkFont(size=11),
            command=self._browse_file
        )
        self.btn_browse.pack(anchor="e", padx=12, pady=(0, 10))

        self.progress_card = ctk.CTkFrame(self, corner_radius=8)
        self.progress_card.pack(fill="x", padx=16, pady=6)

        self.chk_bigquery = ctk.CTkCheckBox(
            self.progress_card,
            text="Sincronizar a BigQuery al finalizar extracción",
            font=ctk.CTkFont(size=11),
            checkbox_width=20,
            checkbox_height=20,
            onvalue=True,
            offvalue=False
        )
        self.chk_bigquery.select()
        self.chk_bigquery.pack(anchor="w", padx=12, pady=(10, 8))

        self.progress_bar = ctk.CTkProgressBar(self.progress_card, height=10)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=12, pady=4)

        self.status_lbl = ctk.CTkLabel(
            self.progress_card,
            text="Estado: En espera de archivo.",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.status_lbl.pack(anchor="w", padx=12, pady=(2, 2))

        self.counters_lbl = ctk.CTkLabel(
            self.progress_card,
            text="Correos: 0 / 0 | Registros procesados: 0",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        )
        self.counters_lbl.pack(anchor="w", padx=12, pady=(0, 10))

        self.log_box = ctk.CTkTextbox(
            self,
            height=130,
            font=ctk.CTkFont(family="monospace", size=10),
            corner_radius=8
        )
        self.log_box.pack(fill="both", expand=True, padx=16, pady=6)
        self.log_box.configure(state="disabled")

        self.actions_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.actions_frame.pack(fill="x", padx=16, pady=(6, 6))

        self.btn_start = ctk.CTkButton(
            self.actions_frame,
            text="Iniciar Extracción",
            fg_color="#2EA043",
            hover_color="#238636",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=36,
            command=self._start_processing
        )
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_stop = ctk.CTkButton(
            self.actions_frame,
            text="Detener",
            fg_color="#DA3633",
            hover_color="#B62324",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=36,
            width=90,
            state="disabled",
            command=self._stop_processing
        )
        self.btn_stop.pack(side="right")

        # Botón para descargar directamente la base de BigQuery a Excel
        self.btn_download_bq = ctk.CTkButton(
            self,
            text="Descargar Base de Datos a Excel (.xlsx)",
            fg_color="#107C41",
            hover_color="#0D5C30",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=36,
            command=self._prompt_download_bigquery
        )
        self.btn_download_bq.pack(fill="x", padx=16, pady=(0, 16))

    def _log(self, message: str):
        def append():
            self.log_box.configure(state="normal")
            ts = time.strftime("%H:%M:%S")
            self.log_box.insert("end", f"[{ts}] {message}\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, append)

    def _browse_file(self):
        file_selected = filedialog.askopenfilename(
            title="Seleccionar archivo PST",
            filetypes=[("Archivos Outlook PST", "*.pst"), ("Todos los archivos", "*.*")]
        )
        if file_selected:
            self.selected_pst = Path(file_selected)
            self.file_path_entry.delete(0, "end")
            self.file_path_entry.insert(0, str(self.selected_pst))
            self._log(f"Archivo seleccionado: {self.selected_pst.name}")
            self.status_lbl.configure(text="Estado: Listo para procesar.")

    def _start_processing(self):
        path_str = self.file_path_entry.get().strip()
        if not path_str or not Path(path_str).exists():
            messagebox.showwarning("Atención", "Seleccione un archivo .pst válido.")
            return

        self.selected_pst = Path(path_str)
        self.is_running = True
        self.stop_requested = False

        self.btn_start.configure(state="disabled")
        self.btn_browse.configure(state="disabled")
        self.btn_download_bq.configure(state="disabled")
        self.btn_stop.configure(state="normal")

        thread = threading.Thread(target=self._worker_process, daemon=True)
        thread.start()

    def _stop_processing(self):
        if self.is_running:
            self.stop_requested = True
            self.btn_stop.configure(state="disabled")
            self._log("Deteniendo proceso de extracción...")

    def _worker_process(self):
        start_time = time.time()
        pst_id = self.selected_pst.name

        try:
            self._log(f"Abriendo archivo: {pst_id}")
            self.after(0, lambda: self.status_lbl.configure(text="Estado: Contando correos..."))

            checkpoint = self.db.get_checkpoint(pst_id)
            skip_count = 0
            if checkpoint:
                processed, total, completed = checkpoint
                if not completed:
                    skip_count = processed
                    self._log(f"Reanudando desde el correo #{skip_count + 1}...")

            with PSTReader(self.selected_pst) as reader:
                total_messages = reader.count_total_messages()
                self._log(f"Total a procesar: {total_messages:,} correos.")

                processed_count = skip_count
                batch_records = []
                cuit_counter = 0

                for msg in reader.iter_messages(skip_count=skip_count):
                    if self.stop_requested:
                        break

                    processed_count += 1
                    data = extract_ticket_data(msg["subject"], msg["body"])
                    if data:
                        data["fecha_email"] = msg["delivery_time"]
                        data["mail_id"] = msg["message_id"]
                        batch_records.append(data)

                    if len(batch_records) >= 500 or processed_count % 50 == 0:
                        if batch_records:
                            inserted = self.db.save_records_batch(batch_records)
                            cuit_counter += inserted
                            batch_records.clear()
                        self.db.update_checkpoint(pst_id, processed_count, total_messages, completed=False)

                        progress = processed_count / max(1, total_messages)
                        self.after(0, lambda p=progress, c=processed_count, t=total_messages, v=cuit_counter: self._update_progress(p, c, t, v))

                if batch_records:
                    inserted = self.db.save_records_batch(batch_records)
                    cuit_counter += inserted
                    batch_records.clear()

                if not self.stop_requested:
                    self.db.update_checkpoint(pst_id, processed_count, total_messages, completed=True)
                    self._log(f"Extracción finalizada. {cuit_counter:,} registros guardados localmente.")

                    if self.chk_bigquery.get():
                        self._sync_bigquery()

                    elapsed = time.time() - start_time
                    self._log(f"Operación finalizada en {elapsed:.1f} segundos.")
                    messagebox.showinfo("Extracción Finalizada", f"Proceso completado exitosamente.\n\nTotal registros procesados: {cuit_counter:,}")
                else:
                    self._log("Proceso detenido por el usuario. El avance ha sido guardado.")

        except Exception as e:
            self._log(f"Error durante el procesamiento: {str(e)}")
            messagebox.showerror("Error", str(e))
        finally:
            self.is_running = False
            self.after(0, self._reset_ui_state)

    def _sync_bigquery(self):
        self._log("Iniciando sincronización con Google BigQuery...")
        self.after(0, lambda: self.status_lbl.configure(text="Estado: Sincronizando con BigQuery..."))
        try:
            bq = BigQuerySyncManager(db_manager=self.db)
            bq.authenticate()
            bq.ensure_infrastructure()
            synced = bq.sync_all_pending()
            self._log(f"BigQuery actualizado: {synced:,} filas registradas.")
        except Exception as e:
            self._log(f"Error de sincronización en BigQuery: {str(e)}")

    def _prompt_download_bigquery(self):
        if self.is_running:
            messagebox.showwarning("Operación en Curso", "Aguarde a que finalice la tarea actual.")
            return

        file_selected = filedialog.asksaveasfilename(
            title="Guardar base de datos como Excel",
            defaultextension=".xlsx",
            initialfile="Extraccion de Datos Clientes PST GCNET.xlsx",
            filetypes=[("Libro de Excel (*.xlsx)", "*.xlsx"), ("Todos los archivos", "*.*")]
        )

        if not file_selected:
            return

        save_path = Path(file_selected)
        self.is_running = True
        self.btn_download_bq.configure(state="disabled")
        self.btn_start.configure(state="disabled")
        self.btn_browse.configure(state="disabled")

        thread = threading.Thread(target=self._worker_download_bq, args=(save_path,), daemon=True)
        thread.start()

    def _worker_download_bq(self, save_path: Path):
        try:
            self._log(f"Iniciando descarga desde BigQuery...")
            self.after(0, lambda: self.status_lbl.configure(text="Estado: Conectando con BigQuery..."))

            bq = BigQuerySyncManager(db_manager=self.db)
            bq.authenticate()

            def on_progress(msg: str):
                self._log(msg)
                self.after(0, lambda m=msg: self.status_lbl.configure(text=f"Estado: {m}"))

            total_rows = bq.download_to_excel(save_path, progress_callback=on_progress)

            self._log(f"Descarga completada: {total_rows:,} registros guardados en {save_path.name}")
            self.after(0, lambda: self.status_lbl.configure(text="Estado: Descarga completada."))
            self.after(0, lambda: messagebox.showinfo(
                "Exportación Exitosa",
                f"La base de datos se ha exportado correctamente.\n\n"
                f"Total de registros: {total_rows:,}\n"
                f"Archivo: {save_path.name}"
            ))
        except Exception as e:
            self._log(f"Error en la exportación: {str(e)}")
            self.after(0, lambda err=str(e): messagebox.showerror("Error de Exportación", f"No se pudo completar la descarga:\n{err}"))
        finally:
            self.is_running = False
            self.after(0, self._reset_ui_state)

    def _update_progress(self, progress: float, processed: int, total: int, valid: int):
        self.progress_bar.set(progress)
        pct = int(progress * 100)
        self.status_lbl.configure(text=f"Estado: Procesando ({pct}%)")
        self.counters_lbl.configure(text=f"Correos: {processed:,} / {total:,} | Válidos: {valid:,}")

    def _reset_ui_state(self):
        self.btn_start.configure(state="normal")
        self.btn_browse.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.btn_download_bq.configure(state="normal")
        self.status_lbl.configure(text="Estado: Listo.")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
