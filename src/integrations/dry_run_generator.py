import json
import time
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Callable, Optional

from src.config import BASE_DIR
from src.integrations.crm_sync import CRMSyncManager
from src.integrations.bigquery_sync import BigQuerySyncManager
from src.parser.phone_parser import process_client_phones_with_baileys, split_raw_phones, normalize_to_arg_international

OUTPUT_FILE = BASE_DIR / "intent_upload_contact.txt"

def is_whatsapp_session_alive() -> bool:
    probe_script = BASE_DIR / "src" / "verifier" / "check_session.js"
    try:
        res = subprocess.run(["node", str(probe_script)], capture_output=True, text=True, timeout=6)
        return "STATUS:ACTIVE" in res.stdout
    except Exception:
        return False

def get_consolidated_records_from_source(db_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(db_records) >= 50:
        return db_records

    try:
        bq = BigQuerySyncManager()
        bq.authenticate()
        query = f"""
            SELECT 
                cuit,
                ANY_VALUE(razon_social) as razon_social,
                ANY_VALUE(nombre) as nombre,
                ANY_VALUE(calle) as calle,
                ANY_VALUE(altura) as altura,
                ANY_VALUE(localidad) as localidad,
                ANY_VALUE(provincia) as provincia,
                ANY_VALUE(codigo_postal) as codigo_postal,
                STRING_AGG(DISTINCT telefono, ' / ') as telefono
            FROM `{bq.client.project}.{bq.dataset_id}.{bq.table_id}`
            WHERE cuit IS NOT NULL AND cuit != ''
            GROUP BY cuit
        """
        rows = bq.client.query(query).result()
        bq_records = [dict(r) for r in rows]
        if len(bq_records) > len(db_records):
            return bq_records
    except Exception:
        pass

    return db_records

def generate_intent_upload_file(
    db_records: List[Dict[str, Any]],
    crm: CRMSyncManager,
    progress_callback: Optional[Callable[[str, float], None]] = None
) -> Dict[str, Any]:
    
    if progress_callback:
        progress_callback("Descargando mapa completo de contactos de Atlion CRM...", 0.05)

    atlion_map = crm.get_atlion_contacts_map()
    records = get_consolidated_records_from_source(db_records)

    if progress_callback:
        progress_callback(f"Comparando {len(records):,} CUITs contra {len(atlion_map):,} de Atlion...", 0.12)

    new_records = []
    updates_needed = []
    already_complete = 0

    def clean_digits(num: str) -> str:
        import re
        return re.sub(r"\D", "", num or "")

    for r in records:
        cuit = str(r.get("cuit", "")).strip()
        if not cuit:
            continue
            
        if cuit in atlion_map:
            atlion_contact = atlion_map[cuit]
            current_phone = atlion_contact.get("phone", "").strip()
            existing_extras = atlion_contact.get("additional_phones", [])
            
            existing_digits = set()
            if current_phone:
                existing_digits.add(clean_digits(current_phone))
            for ep in existing_extras:
                cd = clean_digits(ep)
                if cd:
                    existing_digits.add(cd)

            # Analizar teléfonos provenientes del PST
            pst_raw = (r.get("telefono") or "").strip()
            pst_candidates = split_raw_phones(pst_raw)
            pst_normalized_clean = []
            for pc in pst_candidates:
                norm = normalize_to_arg_international(pc)
                if norm:
                    pst_normalized_clean.append((norm[0], clean_digits(norm[1])))

            # Chequear si hay números en PST no registrados en Atlion
            brand_new_for_contact = [
                e164 for e164, c_dig in pst_normalized_clean
                if c_dig not in existing_digits
            ]

            if brand_new_for_contact or (not current_phone and pst_normalized_clean):
                updates_needed.append({
                    "atlion": atlion_contact,
                    "pst": r,
                    "brand_new_phones": list(dict.fromkeys(brand_new_for_contact))
                })
            else:
                already_complete += 1
        else:
            new_records.append(r)

    total_new = len(new_records)
    total_updates = len(updates_needed)

    # 1. Pre-verificación masiva en WhatsApp (Baileys) en paquetes de 100
    if progress_callback:
        progress_callback("Recolectando teléfonos para verificación rápida por lotes...", 0.20)

    phones_to_check = []
    clients_to_scan = new_records + [item["pst"] for item in updates_needed]
    for client in clients_to_scan:
        raw_t = client.get("telefono", "")
        for p in split_raw_phones(raw_t):
            norm = normalize_to_arg_international(p)
            if norm:
                phones_to_check.append(norm[1])

    unique_phones = list(set(phones_to_check))
    BATCH_SIZE = 100
    for b_idx in range(0, len(unique_phones), BATCH_SIZE):
        batch = unique_phones[b_idx : b_idx + BATCH_SIZE]
        crm.verifier.verify_phones_batch(batch)
        if progress_callback:
            pct = 0.20 + (min(b_idx + BATCH_SIZE, len(unique_phones)) / max(1, len(unique_phones))) * 0.35
            progress_callback(f"Escaneando en WhatsApp ({min(b_idx + BATCH_SIZE, len(unique_phones)):,}/{len(unique_phones):,})...", pct)

    if progress_callback:
        progress_callback("Redactando 'intent_upload_contact.txt'...", 0.60)

    lines = []
    lines.append("=" * 95)
    lines.append("PLAN DE CARGA: CONTACTOS A CREAR Y ENRIQUECER EN ATALION CRM")
    lines.append(f"Fecha de Generación:             {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Base Analizada:                  {len(records):,} CUITs únicos")
    lines.append(f"Contactos NUEVOS para Incorporar:{total_new:,}")
    lines.append(f"Existentes que RECUPERAN TELÉFONO:{total_updates:,}")
    lines.append(f"Existentes Completos (Omitidos): {already_complete:,}")
    lines.append("=" * 95)

    # --- SECCIÓN A: CONTACTOS EXISTENTES QUE RECUPERAN O SUMAN TELÉFONOS ---
    if updates_needed:
        lines.append("\n" + "#" * 95)
        lines.append(f"SECCIÓN 1: CONTACTOS EN ATALION QUE RECUPERAN O SUMAN TELÉFONOS ({total_updates:,})")
        lines.append("#" * 95 + "\n")
        
        for idx, item in enumerate(updates_needed, start=1):
            atlion_info = item["atlion"]
            pst_info = item["pst"]
            cuit = pst_info.get("cuit")
            cid = atlion_info.get("id")
            cname = atlion_info.get("name")
            current_phone = atlion_info.get("phone", "").strip()
            existing_tags = set(atlion_info.get("tags") or [])

            raw_tel = pst_info.get("telefono", "")
            phone_info = process_client_phones_with_baileys(raw_tel, verifier=crm.verifier)
            primary = phone_info["primary_phone"]
            has_wa = phone_info["has_whatsapp"]
            wa_numbers = phone_info.get("wa_numbers", [])

            # Determinación de tags
            tags_to_add = []
            if not current_phone:
                tags_to_add.append("telefono-recuperado")
                target_phone = primary
            else:
                tags_to_add.append("telefono-adicional")
                target_phone = current_phone

            if has_wa:
                tags_to_add.append("tiene-whatsapp")
            elif not any("tiene-whatsapp" in t for t in existing_tags):
                tags_to_add.append("solo-telefono-fijo")

            final_tags = sorted(list(existing_tags.union(tags_to_add)))

            # Construir additionalPhones para no pisar
            additional_phones = []
            for p in atlion_info.get("additional_phones", []):
                additional_phones.append({"phone": p, "phoneLabel": "Anterior"})

            for extra in item["brand_new_phones"]:
                if extra != target_phone and extra not in [ap["phone"] for ap in additional_phones]:
                    lbl = "WhatsApp" if extra in wa_numbers else "Fijo"
                    additional_phones.append({"phone": extra, "phoneLabel": lbl})

            link = f"https://app.gohighlevel.com/v2/location/{crm.location_id}/contacts/detail/{cid}"
            lines.append(f"[UPDATE {idx}/{total_updates}] CUIT: {cuit} | {cname}")
            lines.append(f"  • Enlace en Atlion:     {link}")
            lines.append(f"  • Teléfono Principal:   {target_phone or '[SIN PRINCIPAL]'}")
            if item['brand_new_phones']:
                lines.append(f"  • Nuevos detectados:    {', '.join(item['brand_new_phones'])}")
            lines.append(f"  • Nuevos Tags:          {', '.join(tags_to_add)}")
            lines.append(f"  • Acción planificada:   PUT /contacts/{cid}")
            lines.append(f"  • Payload de update:    {json.dumps({'phone': target_phone or None, 'additionalPhones': additional_phones, 'tags': final_tags}, ensure_ascii=False)}")
            lines.append("-" * 95)

    # --- SECCIÓN B: CONTACTOS NUEVOS A INCORPORAR ---
    lines.append("\n" + "#" * 95)
    lines.append(f"SECCIÓN 2: CONTACTOS NUEVOS PARA CREAR EN ATALION CRM ({total_new:,})")
    lines.append("#" * 95 + "\n")

    con_wa = 0
    solo_fijo = 0
    sin_tel = 0

    for idx, client in enumerate(new_records, start=1):
        cuit = str(client.get("cuit", "")).strip()
        razon_social = (client.get("razon_social") or "").strip()
        nombre_dest = (client.get("nombre") or "").strip()

        if razon_social and nombre_dest:
            first_name = nombre_dest
            last_name = f"({razon_social})"
        elif razon_social:
            first_name = razon_social
            last_name = ""
        elif nombre_dest:
            first_name = nombre_dest
            last_name = ""
        else:
            first_name = f"Cliente CUIT {cuit}"
            last_name = ""

        raw_tel = client.get("telefono", "")
        phone_info = process_client_phones_with_baileys(raw_tel, verifier=crm.verifier)
        primary = phone_info["primary_phone"]
        has_wa = phone_info["has_whatsapp"]
        extras = phone_info["additional_phones"]

        tags = ["origen-base"]
        if primary:
            if has_wa:
                tags.append("tiene-whatsapp")
                con_wa += 1
            else:
                tags.append("solo-telefono-fijo")
                solo_fijo += 1
            if phone_info.get("has_landline") and has_wa:
                tags.append("tiene-fijo")
        else:
            tags.append("sin-telefono")
            sin_tel += 1

        calle = (client.get("calle") or "").strip()
        altura = (client.get("altura") or "").strip()
        localidad = (client.get("localidad") or "").strip()
        provincia = (client.get("provincia") or "").strip()
        cp = (client.get("codigo_postal") or "").strip()
        domicilio = f"{calle} {altura}".strip()
        if localidad or provincia:
            domicilio += f", {localidad} ({provincia})"
        if cp:
            domicilio += f" - CP: {cp}"

        lines.append(f"[CREATE {idx}/{total_new}] CUIT: {cuit}")
        lines.append(f"  • Nombre de Contacto:   {first_name} {last_name}".strip())
        lines.append(f"  • Teléfono Original:    '{raw_tel}'")
        if primary:
            tipo_lbl = "🟢 Móvil (WhatsApp Activo)" if has_wa else "🔴 Teléfono Fijo / Sin WhatsApp"
            lines.append(f"  • Teléfono Principal:   {primary} ({tipo_lbl})")
        else:
            lines.append(f"  • Teléfono Principal:   [SIN TELÉFONO - SE CARGA IGUAL CON CUIT]")
            
        if extras:
            lines.append(f"  • Teléfonos Extras:     {', '.join(extras)}")
        lines.append(f"  • Dirección:            {domicilio or 'S/D'}")
        lines.append(f"  • Etiquetas (Tags):     {', '.join(tags)}")

        payload = {
            "firstName": first_name[:40],
            "lastName": last_name[:40],
            "name": f"{first_name} {last_name}".strip(),
            "phone": primary or None,
            "locationId": crm.location_id,
            "address1": f"{calle} {altura}".strip() or None,
            "city": localidad or None,
            "state": provincia or None,
            "postalCode": cp or None,
            "tags": tags,
            "customFields": [{"id": crm.cuit_field_id, "value": cuit}]
        }
        lines.append(f"  • Payload POST:         {json.dumps(payload, ensure_ascii=False)}")
        lines.append("-" * 95)

        if progress_callback and (idx % 50 == 0 or idx == total_new):
            pct = 0.60 + (idx / total_new) * 0.38
            progress_callback(f"Redactando plan de carga {idx:,}/{total_new:,}...", pct)

    lines.append("\n" + "=" * 95)
    lines.append("RESUMEN GENERAL DEL PLAN:")
    lines.append(f"• Nuevos con WhatsApp:            {con_wa:,}")
    lines.append(f"• Nuevos con Sólo Fijo:           {solo_fijo:,}")
    lines.append(f"• Nuevos Sin Teléfono (Cargados): {sin_tel:,}")
    lines.append(f"• Existentes que suman Teléfono:  {total_updates:,}")
    lines.append(f"• Existentes ya completos:        {already_complete:,}")
    lines.append("=" * 95)

    OUTPUT_FILE.write_text("\n".join(lines), encoding="utf-8")

    if progress_callback:
        progress_callback("Archivo intent_upload_contact.txt completado con éxito.", 1.0)

    return {
        "total_local": len(records),
        "existing_crm": already_complete,
        "new_count": total_new,
        "updates_count": total_updates,
        "file_path": OUTPUT_FILE,
        "new_records": new_records,
        "updates_needed": updates_needed
    }
