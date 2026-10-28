import sys
import threading
import time
import subprocess
from pathlib import Path
from typing import Optional
from PIL import Image
import customtkinter as ctk
from tkinter import filedialog, messagebox

from src.config import BASE_DIR, DATA_DIR
from src.extractor.pst_reader import PSTReader
from src.parser.regex_engine import extract_ticket_data
from src.storage.db_manager import DatabaseManager
from src.integrations.bigquery_sync import BigQuerySyncManager
from src.integrations.crm_sync import CRMSyncManager
from src.integrations.dry_run_generator import generate_intent_upload_file, OUTPUT_FILE

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class QRDialog(ctk.CTkToplevel):
    """Ventana flotante de alta resolución para escanear el QR si no hay sesión."""
    def __init__(self, parent, on_connected_callback=None):
        super().__init__(parent)
        self.parent = parent
        self.on_connected_callback = on_connected_callback
        self.title("Vincular WhatsApp")
        self.geometry("380x450")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.update_idletasks()
        px = parent.winfo_x() + (parent.winfo_width() // 2) - 190
        py = parent.winfo_y() + (parent.winfo_height() // 2) - 225
        self.geometry(f"+{px}+{py}")

        self.title_lbl = ctk.CTkLabel(
            self,
            text="Escanear con tu WhatsApp",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.title_lbl.pack(pady=(16, 4))

        self.sub_lbl = ctk.CTkLabel(
            self,
            text="Dispositivos vinculados > Vincular un dispositivo",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.sub_lbl.pack(pady=(0, 10))

        self.qr_frame = ctk.CTkFrame(self, width=280, height=280, corner_radius=8, fg_color="#FFFFFF")
        self.qr_frame.pack(padx=20, pady=10)
        self.qr_frame.pack_propagate(False)

        self.qr_lbl = ctk.CTkLabel(
            self.qr_frame,
            text="Iniciando WhatsApp...\nEspere unos segundos.",
            font=ctk.CTkFont(size=12),
            text_color="#333333"
        )
        self.qr_lbl.pack(expand=True)

        self.status_lbl = ctk.CTkLabel(
            self,
            text="Verificando sesión...",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.status_lbl.pack(pady=(10, 4))

        self.btn_cancel = ctk.CTkButton(
            self,
            text="Cancelar",
            fg_color="#DA3633",
            hover_color="#B62324",
            width=100,
            command=self._on_close
        )
        self.btn_cancel.pack(pady=(4, 12))

        self.proc = None
        self.is_active = True
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_worker()

    def _start_worker(self):
        thread = threading.Thread(target=self._run_node_process, daemon=True)
        thread.start()

    def _run_node_process(self):
        login_script = BASE_DIR / "src" / "verifier" / "login_whatsapp.js"
        qr_img_path = DATA_DIR / "whatsapp_qr.png"

        try:
            self.proc = subprocess.Popen(
                ["node", str(login_script)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            for line in iter(self.proc.stdout.readline, ''):
                if not self.is_active:
                    break
                line_str = line.strip()

                if "EVENT:QR_GENERATED" in line_str:
                    time.sleep(0.3)
                    self.after(0, lambda: self._display_qr_image(qr_img_path))
                elif "EVENT:SESSION_EXPIRED" in line_str:
                    self.after(0, lambda: self.status_lbl.configure(text="Sesión vencida. Creando nuevo QR..."))
                elif "EVENT:CONNECTED" in line_str:
                    phone = line_str.split(":")[-1]
                    self.after(0, lambda p=phone: self._on_success(p))
                    break

            if self.proc:
                self.proc.stdout.close()
                self.proc.wait()

        except Exception as e:
            if self.is_active:
                self.after(0, lambda err=str(e): self.status_lbl.configure(text=f"Error: {err}"))

    def _display_qr_image(self, path):
        if not self.is_active:
            return
        if path.exists():
            try:
                pil_img = Image.open(str(path))
                ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(260, 260))
                self.qr_lbl.configure(image=ctk_img, text="")
                self.status_lbl.configure(text="Listo. Escanea el código con tu celular.")
            except Exception:
                pass

    def _on_success(self, phone):
        self.status_lbl.configure(text=f"Conectado: {phone}")
        self.parent._log(f"WhatsApp vinculado exitosamente: {phone}")
        if self.on_connected_callback:
            self.on_connected_callback()
        self.after(1500, self._on_close)

    def _on_close(self):
        self.is_active = False
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.destroy()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("PST CUIT Extractor & Atlion CRM Sync")
        window_width = 520
        window_height = 660
        self.minsize(480, 580)

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
        # Encabezado
        self.header = ctk.CTkFrame(self, corner_radius=8, fg_color="transparent")
        self.header.pack(fill="x", padx=16, pady=(14, 4))

        self.title_lbl = ctk.CTkLabel(
            self.header,
            text="Extractor de Correos & CUITs",
            font=ctk.CTkFont(size=17, weight="bold")
        )
        self.title_lbl.pack(anchor="w")

        self.desc_lbl = ctk.CTkLabel(
            self.header,
            text="Extracción de archivos PST y auditoría controlada para Atlion CRM.",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.desc_lbl.pack(anchor="w")

        # 1. Explorar PST
        self.file_card = ctk.CTkFrame(self, corner_radius=8)
        self.file_card.pack(fill="x", padx=16, pady=4)

        self.file_path_entry = ctk.CTkEntry(
            self.file_card,
            placeholder_text="Seleccione archivo .pst...",
            height=30,
            font=ctk.CTkFont(size=11)
        )
        self.file_path_entry.pack(fill="x", padx=12, pady=(8, 4))

        self.btn_browse = ctk.CTkButton(
            self.file_card,
            text="Examinar archivo PST",
            height=26,
            font=ctk.CTkFont(size=11),
            command=self._browse_file
        )
        self.btn_browse.pack(anchor="e", padx=12, pady=(0, 8))

        # Barra de progreso y estado
        self.progress_card = ctk.CTkFrame(self, corner_radius=8)
        self.progress_card.pack(fill="x", padx=16, pady=4)

        self.chk_bigquery = ctk.CTkCheckBox(
            self.progress_card,
            text="Sincronizar a BigQuery al finalizar extracción",
            font=ctk.CTkFont(size=11),
            checkbox_width=18,
            checkbox_height=18,
            onvalue=True,
            offvalue=False
        )
        self.chk_bigquery.select()
        self.chk_bigquery.pack(anchor="w", padx=12, pady=(8, 6))

        self.progress_bar = ctk.CTkProgressBar(self.progress_card, height=8)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=12, pady=2)

        self.status_lbl = ctk.CTkLabel(
            self.progress_card,
            text="Estado: En espera de archivo.",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.status_lbl.pack(anchor="w", padx=12, pady=(2, 1))

        self.counters_lbl = ctk.CTkLabel(
            self.progress_card,
            text="Correos: 0 / 0 | Registros procesados: 0",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        )
        self.counters_lbl.pack(anchor="w", padx=12, pady=(0, 6))

        # Caja de Logs
        self.log_box = ctk.CTkTextbox(
            self,
            height=130,
            font=ctk.CTkFont(family="monospace", size=10),
            corner_radius=8
        )
        self.log_box.pack(fill="both", expand=True, padx=16, pady=4)
        self.log_box.configure(state="disabled")

        # 2 y 3. Iniciar Extracción y Detener
        self.actions_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.actions_frame.pack(fill="x", padx=16, pady=(4, 2))

        self.btn_start = ctk.CTkButton(
            self.actions_frame,
            text="Iniciar Extracción",
            fg_color="#2EA043",
            hover_color="#238636",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=32,
            command=self._start_processing
        )
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_stop = ctk.CTkButton(
            self.actions_frame,
            text="Detener",
            fg_color="#DA3633",
            hover_color="#B62324",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=32,
            width=80,
            state="disabled",
            command=self._stop_processing
        )
        self.btn_stop.pack(side="right")

        # 4. Descargar Base de Datos a Excel (.xlsx)
        self.btn_download_bq = ctk.CTkButton(
            self,
            text="Descargar Base de Datos a Excel (.xlsx)",
            fg_color="#107C41",
            hover_color="#0D5C30",
            font=ctk.CTkFont(size=11, weight="bold"),
            height=32,
            command=self._prompt_download_bigquery
        )
        self.btn_download_bq.pack(fill="x", padx=16, pady=3)

        # 5. Sincronizacion manual con Atlion CRM
        self.btn_upload_crm = ctk.CTkButton(
            self,
            text="Subir Contactos a Atlion CRM",
            fg_color="#D97706",
            hover_color="#B45309",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
            command=self._start_production_upload
        )
        self.btn_upload_crm.pack(fill="x", padx=16, pady=(3, 14))

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
            messagebox.showwarning("Atencion", "Seleccione un archivo .pst valido.")
            return

        self.selected_pst = Path(path_str)
        self.is_running = True
        self.stop_requested = False

        self.btn_start.configure(state="disabled")
        self.btn_browse.configure(state="disabled")
        self.btn_download_bq.configure(state="disabled")
        self.btn_upload_crm.configure(state="disabled")
        self.btn_stop.configure(state="normal")

        thread = threading.Thread(target=self._worker_process, daemon=True)
        thread.start()

    def _stop_processing(self):
        if self.is_running:
            self.stop_requested = True
            self.btn_stop.configure(state="disabled")
            self._log("Deteniendo proceso de extraccion...")

    def _sync_crm_core(self) -> dict:
        self.after(0, lambda: self.status_lbl.configure(text="Estado: Sincronizando con Atlion CRM..."))
        crm = CRMSyncManager()
        clients = self.db.get_all_unique_clients()
        if not clients:
            self._log("No hay clientes en la base local para sincronizar con Atlion CRM.")
            return {"created": 0, "updated": 0, "errors": 0}

        def on_prep_progress(msg: str, pct: float):
            self._log(msg)
            self.after(0, lambda: self.progress_bar.set(pct * 0.4))
            self.after(0, lambda: self.status_lbl.configure(text=f"Preparando CRM: {int(pct*40)}%"))

        dry_run = generate_intent_upload_file(clients, crm=crm, progress_callback=on_prep_progress)
        new_records = dry_run.get("new_records", [])
        updates_needed = dry_run.get("updates_needed", [])

        total_ops = len(new_records) + len(updates_needed)
        if total_ops == 0:
            self._log("Atlion CRM al dia: no hay contactos ni telefonos pendientes.")
            return {"created": 0, "updated": 0, "errors": 0}

        def on_sync_progress(msg: str, pct: float):
            self._log(msg)
            total_pct = 0.4 + (pct * 0.6)
            self.after(0, lambda: self.progress_bar.set(total_pct))
            self.after(0, lambda: self.status_lbl.configure(text=f"Subiendo a CRM: {int(total_pct*100)}%"))

        self._log(f"Enviando a Atlion CRM: {len(new_records):,} altas y {len(updates_needed):,} enriquecimientos...")
        results = crm.execute_production_sync(new_records, updates_needed, progress_callback=on_sync_progress)
        self._log(f"Sincronizacion CRM finalizada: {results['created']:,} creados | {results['updated']:,} actualizados | {results['errors']:,} fallos.")
        return results

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
                    self._log(f"Extraccion finalizada. {cuit_counter:,} registros guardados localmente.")

                    if self.chk_bigquery.get():
                        self._sync_bigquery()

                    self._log("Iniciando subida automatica a Atlion CRM...")
                    self._sync_crm_core()

                    elapsed = time.time() - start_time
                    self._log(f"Operacion finalizada en {elapsed:.1f} segundos.")
                    messagebox.showinfo("Proceso Finalizado", f"Extraccion y sincronizaciones completadas exitosamente.\n\nTotal registros procesados: {cuit_counter:,}")
                else:
                    self._log("Proceso detenido por el usuario. El avance ha sido guardado.")

        except Exception as e:
            self._log(f"Error durante el procesamiento: {str(e)}")
            messagebox.showerror("Error", str(e))
        finally:
            self.is_running = False
            self.after(0, self._reset_ui_state)

    def _sync_bigquery(self):
        self._log("Iniciando sincronizacion con Google BigQuery...")
        self.after(0, lambda: self.status_lbl.configure(text="Estado: Sincronizando con BigQuery..."))
        try:
            bq = BigQuerySyncManager(db_manager=self.db)
            bq.authenticate()
            bq.ensure_infrastructure()
            synced = bq.sync_all_pending()
            self._log(f"BigQuery actualizado: {synced:,} filas registradas.")
        except Exception as e:
            self._log(f"Error de sincronizacion en BigQuery: {str(e)}")

    def _prompt_download_bigquery(self):
        if self.is_running:
            messagebox.showwarning("Operacion en Curso", "Aguarde a que finalice la tarea actual.")
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
        self.btn_upload_crm.configure(state="disabled")
        self.btn_start.configure(state="disabled")
        self.btn_browse.configure(state="disabled")

        thread = threading.Thread(target=self._worker_download_bq, args=(save_path,), daemon=True)
        thread.start()

    def _worker_download_bq(self, save_path: Path):
        try:
            self._log("Iniciando descarga desde BigQuery...")
            self.after(0, lambda: self.status_lbl.configure(text="Estado: Conectando con BigQuery..."))

            bq = BigQuerySyncManager(db_manager=self.db)
            bq.authenticate()

            def on_progress(msg: str):
                self._log(msg)
                self.after(0, lambda m=msg: self.status_lbl.configure(text=f"Estado: {m}"))

            total_rows = bq.download_to_excel(save_path, progress_callback=on_progress)
            self._log(f"Descarga completada: {total_rows:,} registros guardados en {save_path.name}")

            self._log("Iniciando sincronizacion con Atlion CRM tras descarga...")
            self._sync_crm_core()

            self.after(0, lambda: self.status_lbl.configure(text="Estado: Descarga y sincronizacion completadas."))
            self.after(0, lambda: messagebox.showinfo(
                "Exportacion y Sincronizacion Exitosa",
                f"La base de datos se exporto correctamente y se sincronizo con Atlion CRM.\n\nTotal registros descargados: {total_rows:,}\nArchivo: {save_path.name}"
            ))
        except Exception as e:
            self._log(f"Error en la operacion: {str(e)}")
            self.after(0, lambda err=str(e): messagebox.showerror("Error", f"Fallo durante la descarga o sincronizacion:\n{err}"))
        finally:
            self.is_running = False
            self.after(0, self._reset_ui_state)

    def _start_production_upload(self):
        if self.is_running:
            messagebox.showwarning("Atencion", "Aguarde a que finalice la tarea actual.")
            return

        total_local = self.db.count_total_records()
        if total_local == 0:
            messagebox.showinfo("Sin Datos", "Primero procese un archivo PST para tener clientes en la base local.")
            return

        from src.integrations.dry_run_generator import is_whatsapp_session_alive

        if not is_whatsapp_session_alive():
            self._log("Sesion de WhatsApp requerida para categorizacion de numeros. Abriendo QR...")
            QRDialog(self, on_connected_callback=self._execute_production_thread)
            return

        self._execute_production_thread()

    def _execute_production_thread(self):
        self.is_running = True
        self.btn_start.configure(state="disabled")
        self.btn_browse.configure(state="disabled")
        self.btn_download_bq.configure(state="disabled")
        self.btn_upload_crm.configure(state="disabled")

        thread = threading.Thread(target=self._worker_production_upload, daemon=True)
        thread.start()

    def _worker_production_upload(self):
        try:
            self._log("Iniciando proceso de subida a Atlion CRM...")
            results = self._sync_crm_core()
            self.after(0, lambda: messagebox.showinfo(
                "Sincronizacion Completada",
                f"Resultado de la carga en Atlion CRM:\n\n"
                f"Nuevos contactos creados: {results['created']:,}\n"
                f"Contactos enriquecidos: {results['updated']:,}\n"
                f"Errores / Reintentos: {results['errors']:,}"
            ))
        except Exception as e:
            self._log(f"Error en subida a produccion: {str(e)}")
            self.after(0, lambda err=str(e): messagebox.showerror("Error en Subida", f"Ocurrio un error:\n{err}"))
        finally:
            self.is_running = False
            self.after(0, self._reset_ui_state)

    def _update_progress(self, progress: float, processed: int, total: int, valid: int):
        self.progress_bar.set(progress)
        pct = int(progress * 100)
        self.status_lbl.configure(text=f"Estado: Procesando ({pct}%)")
        self.counters_lbl.configure(text=f"Correos: {processed:,} / {total:,} | Validos: {valid:,}")

    def _reset_ui_state(self):
        self.btn_start.configure(state="normal")
        self.btn_browse.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.btn_download_bq.configure(state="normal")
        self.btn_upload_crm.configure(state="normal")
        self.status_lbl.configure(text="Estado: Listo.")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
