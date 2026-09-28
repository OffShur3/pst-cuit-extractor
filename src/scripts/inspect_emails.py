import sys
from pathlib import Path

# Agregar la raíz del proyecto al path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.extractor.pst_reader import PSTReader
from src.config import DATA_DIR

def inspect_pst(pst_path_str: str, max_samples: int = 3):
    pst_path = Path(pst_path_str)
    if not pst_path.exists():
        print(f"❌ Error: El archivo no existe en {pst_path}")
        return

    output_file = DATA_DIR / "muestras_emails.txt"
    print(f"🔍 Inspeccionando {max_samples} correos de muestra en: {pst_path.name}...")

    with PSTReader(pst_path) as reader:
        with open(output_file, "w", encoding="utf-8") as f:
            for idx, msg in enumerate(reader.iter_messages()):
                if idx >= max_samples:
                    break

                separator = "=" * 80
                f.write(f"\n{separator}\n")
                f.write(f"MUESTRA #{idx + 1}\n")
                f.write(f"{separator}\n")
                f.write(f"📌 ASUNTO: {msg['subject']}\n")
                f.write(f"📅 FECHA:  {msg['delivery_time']}\n")
                f.write(f"🆔 ID:     {msg['message_id']}\n")
                f.write(f"{'-' * 80}\n")
                f.write("📄 CUERPO DEL MENSAJE (BODY COMPLETO):\n")
                f.write(f"{'-' * 80}\n")
                f.write(msg['body'] if msg['body'].strip() else "[CUERPO VACÍO O NO PUDO SER DECODIFICADO]")
                f.write("\n\n")

    print(f"✅ ¡Listo! Se guardaron {max_samples} muestras completas en:")
    print(f"👉 {output_file.resolve()}")
    print("\nPuedes abrirlo con:")
    print(f"   code {output_file}   (si usas VS Code)")
    print(f"   cat {output_file}    (para verlo en consola)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m src.scripts.inspect_emails <ruta_al_pst> [cantidad_muestras]")
    else:
        samples = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        inspect_pst(sys.argv[1], max_samples=samples)
