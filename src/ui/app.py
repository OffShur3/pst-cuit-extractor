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

        self.title("PST CUIT Extractor")
        window_width = 500
        window_height = 580
        self.minsize(460, 520)

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
            text="1 fila por correo, CUIT numérico y direcciones desglosadas.",
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
            text="Sincronizar a BigQuery al finalizar",
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
            text="Esperando archivo...",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.status_lbl.pack(anchor="w", padx=12, pady=(2, 2))

        self.counters_lbl = ctk.CTkLabel(
            self.progress_card,
            text="Correos: 0 / 0 | Registros válidos: 0",
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
        self.actions_frame.pack(fill="x", padx=16, pady=(6, 16))

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
            title="Seleccionar PST",
            filetypes=[("Archivos Outlook PST", "*.pst"), ("Todos los archivos", "*.*")]
        )
        if file_selected:
            self.selected_pst = Path(file_selected)
            self.file_path_entry.delete(0, "end")
            self.file_path_entry.insert(0, str(self.selected_pst))
            self._log(f"Seleccionado: {self.selected_pst.name}")
            self.status_lbl.configure(text="Listo para procesar.")

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
        self.btn_stop.configure(state="normal")

        thread = threading.Thread(target=self._worker_process, daemon=True)
        thread.start()

    def _stop_processing(self):
        if self.is_running:
            self.stop_requested = True
            self.btn_stop.configure(state="disabled")
            self._log("⚠️ Deteniendo proceso...")

    def _worker_process(self):
        start_time = time.time()
        pst_id = self.selected_pst.name

        try:
            self._log(f"Abriendo {pst_id}...")
            self.after(0, lambda: self.status_lbl.configure(text="Contando correos..."))

            checkpoint = self.db.get_checkpoint(pst_id)
            skip_count = 0
            if checkpoint:
                processed, total, completed = checkpoint
                if not completed:
                    skip_count = processed
                    self._log(f"Reanudando desde correo {skip_count + 1}...")

            with PSTReader(self.selected_pst) as reader:
                total_messages = reader.count_total_messages()
                self._log(f"Total a procesar: {total_messages:,} correos")

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
                    self._log(f"✅ Extracción finalizada. {cuit_counter:,} correos válidos guardados.")

                    if self.chk_bigquery.get():
                        self._sync_bigquery()

                    elapsed = time.time() - start_time
                    self._log(f"🎉 Completado en {elapsed:.1f}s.")
                    messagebox.showinfo("Éxito", f"Extracción finalizada.\nTotal correos procesados: {cuit_counter:,}")
                else:
                    self._log("🛑 Detenido por el usuario. Avance guardado.")

        except Exception as e:
            self._log(f"❌ Error: {str(e)}")
            messagebox.showerror("Error", str(e))
        finally:
            self.is_running = False
            self.after(0, self._reset_ui_state)

    def _sync_bigquery(self):
        self._log("Sincronizando con BigQuery...")
        self.after(0, lambda: self.status_lbl.configure(text="Subiendo a BigQuery..."))
        try:
            bq = BigQuerySyncManager(db_manager=self.db)
            bq.authenticate()
            bq.ensure_infrastructure()
            synced = bq.sync_all_pending()
            self._log(f"☁️ BigQuery actualizado: {synced:,} filas agregadas.")
        except Exception as e:
            self._log(f"⚠️ Error BigQuery: {str(e)}")

    def _update_progress(self, progress: float, processed: int, total: int, valid: int):
        self.progress_bar.set(progress)
        pct = int(progress * 100)
        self.status_lbl.configure(text=f"Procesando: {pct}%")
        self.counters_lbl.configure(text=f"Correos: {processed:,} / {total:,} | Válidos: {valid:,}")

    def _reset_ui_state(self):
        self.btn_start.configure(state="normal")
        self.btn_browse.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.status_lbl.configure(text="Finalizado.")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
