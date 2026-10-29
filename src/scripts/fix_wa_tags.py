#!/usr/bin/env python3
import re
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.integrations.crm_sync import CRMSyncManager
from src.parser.phone_parser import normalize_to_arg_international, clean_digits

WA_TAG_REGEX = re.compile(r"^wa\s*:\s*(\+?\d[\d\s\-]{6,})$", re.IGNORECASE)


def extract_wa_phone_from_tags(tags: list[str]) -> str | None:
    """Extrae y normaliza el numero de telefono desde una etiqueta tipo 'wa: 549...'."""
    for t in tags:
        m = WA_TAG_REGEX.match(str(t).strip())
        if m:
            raw_num = m.group(1)
            norm = normalize_to_arg_international(raw_num)
            if norm:
                return norm[0]
            digits = clean_digits(raw_num)
            if len(digits) >= 8:
                return f"+{digits}"
    return None


def scan_and_fix_wa_tags(dry_run: bool = False):
    crm = CRMSyncManager()
    print("=" * 85)
    mode_str = "MODO CONTROL (SOLO LECTURA)" if dry_run else "MODO EJECUCION (ACTUALIZANDO EN ATLION)"
    print(f"CONTROL DE ETIQUETAS 'wa: numero' EN ATLION CRM - {mode_str}")
    print("=" * 85)

    start_after = None
    start_after_id = None
    total_scanned = 0
    matched_contacts = 0
    already_ok = 0
    updated_ok = 0
    errors = 0

    while True:
        endpoint = f"/contacts/?locationId={crm.location_id}&limit=100"
        if start_after and start_after_id:
            endpoint += f"&startAfter={start_after}&startAfterId={start_after_id}"

        res = crm._api_call("GET", endpoint)
        contacts = res.get("contacts", [])
        if not contacts:
            break

        for c in contacts:
            total_scanned += 1
            cid = c.get("id")
            cname = c.get("contactName") or f"{c.get('firstName', '')} {c.get('lastName', '')}".strip() or "Sin Nombre"
            current_phone = (c.get("phone") or "").strip()
            raw_tags = [str(t) for t in (c.get("tags") or [])]

            wa_phone = extract_wa_phone_from_tags(raw_tags)
            if not wa_phone:
                continue

            matched_contacts += 1
            has_wa_tag = any(t.lower() == "tiene-whatsapp" for t in raw_tags)
            same_primary = clean_digits(current_phone) == clean_digits(wa_phone)

            if same_primary and has_wa_tag:
                already_ok += 1
                continue

            # Construir lista de telefonos adicionales preservando el principal anterior si era distinto
            raw_extras = c.get("additionalPhones") or []
            extras_list = []
            if current_phone and not same_primary:
                extras_list.append(current_phone)

            for item in raw_extras:
                p = item.get("phone") if isinstance(item, dict) else str(item)
                if p and clean_digits(p) != clean_digits(wa_phone):
                    if clean_digits(p) not in [clean_digits(x) for x in extras_list]:
                        extras_list.append(p.strip())

            # Actualizar conjunto de etiquetas
            updated_tags = [
                t for t in raw_tags
                if t.lower() not in ("sin-telefono", "solo-telefono-fijo")
            ]
            if not has_wa_tag:
                updated_tags.append("tiene-whatsapp")

            print(f"[{matched_contacts}] {cname} (ID: {cid})")
            print(f"    Etiquetas actuales : {', '.join(raw_tags)}")
            print(f"    Tel. Principal     : '{current_phone or 'VACIO'}' -> '{wa_phone}'")
            if extras_list:
                print(f"    Tel. Adicionales   : {', '.join(extras_list)}")
            print(f"    Nuevas Etiquetas   : {', '.join(updated_tags)}")

            if not dry_run:
                ok = crm.update_contact_phones_and_tags(
                    contact_id=cid,
                    phone=wa_phone,
                    additional_phones=extras_list if extras_list else None,
                    tags=updated_tags
                )
                if ok:
                    updated_ok += 1
                    print("    Estado             : ACTUALIZADO OK")
                else:
                    errors += 1
                    print("    Estado             : ERROR AL ACTUALIZAR")
            else:
                print("    Estado             : PENDIENTE DE ACTUALIZAR (Dry-Run)")
            print("-" * 85)

        if total_scanned % 500 == 0:
            print(f"... Escaneados {total_scanned:,} contactos en Atlion ...")

        meta = res.get("meta", {})
        start_after = meta.get("startAfter")
        start_after_id = meta.get("startAfterId")
        if not meta.get("nextPage") or not start_after or not start_after_id:
            break

    print("\n" + "=" * 85)
    print("RESUMEN FINAL:")
    print(f"  Contactos totales escaneados : {total_scanned:,}")
    print(f"  Con etiqueta 'wa: numero'    : {matched_contacts:,}")
    print(f"  Ya estaban correctos         : {already_ok:,}")
    if dry_run:
        print(f"  Pendientes por corregir      : {matched_contacts - already_ok:,}")
    else:
        print(f"  Actualizados con exito       : {updated_ok:,}")
        print(f"  Errores                      : {errors:,}")
    print("=" * 85)


if __name__ == "__main__":
    is_check_only = "--check" in sys.argv or "--dry-run" in sys.argv
    scan_and_fix_wa_tags(dry_run=is_check_only)
