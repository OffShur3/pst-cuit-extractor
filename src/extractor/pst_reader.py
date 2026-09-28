import pypff
from pathlib import Path
from typing import Generator, Dict, Any, Optional

def smart_decode(raw_bytes: Optional[bytes]) -> str:
    """Decodifica texto probando UTF-8 y fallbacks a codificaciones de Windows/Outlook."""
    if not raw_bytes:
        return ""
    for enc in ("utf-8", "cp1252", "iso-8859-1", "latin1"):
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


class PSTReader:
    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)
        if not self.file_path.exists():
            raise FileNotFoundError(f"El archivo PST no existe: {self.file_path}")
        self.pst_file: Optional[pypff.file] = None
        self._current_index = 0

    def open(self):
        self.pst_file = pypff.file()
        self.pst_file.open(str(self.file_path))

    def close(self):
        if self.pst_file:
            self.pst_file.close()
            self.pst_file = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def count_total_messages(self) -> int:
        if not self.pst_file:
            self.open()
        root = self.pst_file.get_root_folder()
        return self._count_folder_messages(root)

    def _count_folder_messages(self, folder) -> int:
        total = folder.number_of_sub_messages
        for i in range(folder.number_of_sub_folders):
            sub_folder = folder.get_sub_folder(i)
            total += self._count_folder_messages(sub_folder)
        return total

    def iter_messages(self, skip_count: int = 0) -> Generator[Dict[str, Any], None, None]:
        if not self.pst_file:
            self.open()

        root = self.pst_file.get_root_folder()
        self._current_index = 0
        yield from self._traverse_folder(root, skip_count)

    def _traverse_folder(self, folder, skip_count: int) -> Generator[Dict[str, Any], None, None]:
        for msg_idx in range(folder.number_of_sub_messages):
            self._current_index += 1
            if self._current_index <= skip_count:
                continue

            try:
                msg = folder.get_sub_message(msg_idx)
                
                # Decodificación inteligente para preservar acentos y caracteres especiales
                body = ""
                if msg.plain_text_body:
                    body = smart_decode(msg.plain_text_body)
                elif msg.html_body:
                    body = smart_decode(msg.html_body)

                subject = msg.subject or ""
                delivery_time = str(msg.delivery_time) if msg.delivery_time else ""
                msg_id = f"{folder.name or 'root'}_{msg.identifier}_{msg_idx}"

                yield {
                    "index": self._current_index,
                    "message_id": msg_id,
                    "subject": subject,
                    "body": body,
                    "delivery_time": delivery_time
                }
            except Exception:
                continue

        for sub_idx in range(folder.number_of_sub_folders):
            sub_folder = folder.get_sub_folder(sub_idx)
            yield from self._traverse_folder(sub_folder, skip_count)
