#!/usr/bin/env python3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.db_manager import DatabaseManager
from src.parser.phone_parser import process_client_phones_with_baileys
from src.verifier.baileys_bridge import WhatsAppVerifier

def run_preview(limit_sample: int = 15):
    print("=" * 85)
    print("🔬 SIMULACIÓN LOCAL: ESCANEO DE CADA TELÉFONO EN BAILEYS")
    print("=" * 85)

    db = DatabaseManager()
    records = db.get_all_unique_clients()
    if not records:
        print("❌ La base de datos local SQLite está vacía.")
        return

    sample_items = records[:limit_sample]
    print(f"📊 Analizando {len(sample_items)} CUITs consolidados con sus teléfonos...\n")

    verifier = WhatsAppVerifier()

    for idx, data in enumerate(sample_items, start=1):
        cuit = str(data.get("cuit", "")).strip()
        nombre = (data.get("nombre") or data.get("razon_social") or f"Cliente {cuit}").strip()
        tel_crudo = (data.get("telefono") or "").strip()

        phone_info = process_client_phones_with_baileys(tel_crudo, verifier=verifier)

        primary = phone_info["primary_phone"]
        details = phone_info["all_details"]

        print(f"#{idx:<2} CUIT: {cuit:<11} | Nombre: {nombre[:35]}")
        print(f"   ├─ Teléfono(s) Crudo(s): '{tel_crudo}'")
        
        if details:
            print(f"   ├─ Teléfonos Analizados ({len(details)}):")
            for d in details:
                is_p = " ⭐ (Elegido como Principal)" if d["phone"] == primary else ""
                print(f"   │    • {d['phone']:<18} ➔ {d['label']}{is_p}")
        else:
            print(f"   ├─ Teléfonos Analizados: [NINGÚN NÚMERO VÁLIDO ENCONTRADO]")

        tags = []
        if phone_info["has_whatsapp"]:
            tags.append("tiene-whatsapp")
        else:
            tags.append("solo-telefono-fijo")
        if phone_info.get("has_landline") and phone_info["has_whatsapp"]:
            tags.append("tiene-fijo")

        print(f"   └─ Tags asignados al Contacto: {', '.join(tags)}")
        print("-" * 85)

    print("\n✅ Simulación completada.")

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    run_preview(limit_sample=n)
