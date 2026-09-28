import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pypff

def explore_folder(folder, path=""):
    folder_name = folder.name or "Raíz"
    current_path = f"{path}/{folder_name}"
    msg_count = folder.number_of_sub_messages
    subfolder_count = folder.number_of_sub_folders

    if msg_count > 0:
        print(f"📁 {current_path:<50} ➔ ✉️  {msg_count} correos")

    for i in range(subfolder_count):
        sub_folder = folder.get_sub_folder(i)
        explore_folder(sub_folder, current_path)

def diagnose(pst_path_str: str):
    pst = pypff.file()
    pst.open(pst_path_str)
    root = pst.get_root_folder()
    print("=" * 70)
    print(f"🔍 INSPECCIÓN DE CARPETAS EN: {Path(pst_path_str).name}")
    print("=" * 70)
    explore_folder(root)
    pst.close()
    print("=" * 70)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        diagnose(sys.argv[1])
    else:
        print("Uso: python -m src.scripts.diagnose_pst ~/Descargas/agus.pst")
