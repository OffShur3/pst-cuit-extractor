import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Set, Tuple

from src.config import BASE_DIR
from src.parser.phone_parser import process_client_phones_with_baileys
from src.verifier.baileys_bridge import WhatsAppVerifier

CONFIG_PATH = BASE_DIR / "CRM_account.json"

class CRMSyncManager:
    def __init__(self, config_path: Path = CONFIG_PATH):
        self.config_path = config_path
        self.api_url = ""
        self.api_token = ""
        self.location_id = ""
        self.api_ver = "2021-07-28"
        self.cuit_field_id = ""
        self.verifier = WhatsAppVerifier()
        self._load_config()

    def _load_config(self):
        if not self.config_path.exists():
            raise FileNotFoundError(f"No se encontró el archivo de credenciales en {self.config_path}.")
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.api_url = data.get("api_url", "https://services.leadconnectorhq.com").rstrip("/")
            self.api_token = data.get("api_token", "")
            self.location_id = data.get("location_id", "")
            self.api_ver = data.get("api_version", "2021-07-28")
            self.cuit_field_id = data.get("cuit_field_id", "QWtFH64E79RTPVj1dyYP")

    def _api_call(self, method: str, endpoint: str, payload: Optional[Dict] = None) -> Dict[str, Any]:
        import urllib.request
        import urllib.error

        url = f"{self.api_url}{endpoint}"
        data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Version": self.api_ver,
            "Accept": "application/json"
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return {}

    def get_atlion_contacts_map(self) -> Dict[str, Dict[str, Any]]:
        """
        Descarga TODOS los contactos de Atlion CRM y devuelve un diccionario con teléfonos y tags:
        { cuit: { "id": contact_id, "phone": phone_number, "name": name, "additional_phones": [...], "tags": [...] } }
        """
        atlion_map = {}
        start_after = None
        start_after_id = None
        
        while True:
            endpoint = f"/contacts/?locationId={self.location_id}&limit=100"
            if start_after and start_after_id:
                endpoint += f"&startAfter={start_after}&startAfterId={start_after_id}"
            
            res = self._api_call("GET", endpoint)
            contacts = res.get("contacts", [])
            if not contacts:
                break
                
            for c in contacts:
                cid = c.get("id")
                cphone = (c.get("phone") or "").strip()
                cname = c.get("contactName") or f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
                
                # Extraer additionalPhones existentes
                raw_extras = c.get("additionalPhones") or []
                c_extras = []
                for item in raw_extras:
                    if isinstance(item, dict):
                        p = item.get("phone")
                    elif isinstance(item, str):
                        p = item
                    else:
                        p = None
                    if p:
                        c_extras.append(str(p).strip())

                ctags = [str(t) for t in (c.get("tags") or [])]

                for cf in c.get("customFields", []):
                    if cf.get("id") == self.cuit_field_id and cf.get("value"):
                        val = str(cf.get("value")).strip()
                        if val:
                            atlion_map[val] = {
                                "id": cid,
                                "phone": cphone,
                                "name": cname,
                                "additional_phones": c_extras,
                                "tags": ctags
                            }
                            
            meta = res.get("meta", {})
            start_after = meta.get("startAfter")
            start_after_id = meta.get("startAfterId")
            if not meta.get("nextPage") or not start_after or not start_after_id:
                break
                
        return atlion_map

    def get_existing_cuits(self) -> Set[str]:
        return set(self.get_atlion_contacts_map().keys())

    def update_contact_phones_and_tags(
        self,
        contact_id: str,
        phone: Optional[str],
        additional_phones: Optional[List[Dict[str, str]]],
        tags: List[str]
    ) -> bool:
        """Actualiza el teléfono principal, teléfonos adicionales y tags combinados."""
        payload: Dict[str, Any] = {
            "tags": tags
        }
        if phone:
            payload["phone"] = phone
        if additional_phones is not None:
            payload["additionalPhones"] = additional_phones

        res = self._api_call("PUT", f"/contacts/{contact_id}", payload)
        return bool(res.get("contact", {}).get("id"))

    def update_contact_phone(self, contact_id: str, phone: str, tags: List[str]) -> bool:
        """Compatibilidad hacia atrás."""
        return self.update_contact_phones_and_tags(contact_id, phone=phone, additional_phones=None, tags=tags)

    def create_contact(self, client_data: Dict[str, Any]) -> Optional[str]:
        """Crea un contacto nuevo en Atlion, incluso si no tiene teléfono."""
        cuit = client_data.get("cuit", "").strip()
        razon_social = client_data.get("razon_social", "").strip()
        nombre_dest = client_data.get("nombre", "").strip()

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

        raw_tel = client_data.get("telefono", "")
        phone_info = process_client_phones_with_baileys(raw_tel, verifier=self.verifier)
        primary_phone = phone_info["primary_phone"]

        tags = ["origen-base"]
        if primary_phone:
            if phone_info["has_whatsapp"]:
                tags.append("tiene-whatsapp")
            else:
                tags.append("solo-telefono-fijo")
            if phone_info.get("has_landline") and phone_info["has_whatsapp"]:
                tags.append("tiene-fijo")
        else:
            tags.append("sin-telefono")

        additional_phones = []
        for extra in phone_info.get("additional_phones", []):
            lbl = "WhatsApp" if extra in phone_info.get("wa_numbers", []) else "Fijo"
            additional_phones.append({"phone": extra, "phoneLabel": lbl})

        calle = (client_data.get("calle") or "").strip()
        altura = (client_data.get("altura") or "").strip()
        address1 = f"{calle} {altura}".strip()

        payload = {
            "firstName": first_name[:40],
            "lastName": last_name[:40],
            "name": f"{first_name} {last_name}".strip(),
            "phone": primary_phone or None,
            "locationId": self.location_id,
            "address1": address1 or None,
            "city": client_data.get("localidad") or None,
            "state": client_data.get("provincia") or None,
            "postalCode": client_data.get("codigo_postal") or None,
            "tags": tags,
            "additionalPhones": additional_phones if additional_phones else None,
            "customFields": [{"id": self.cuit_field_id, "value": cuit}]
        }

        res = self._api_call("POST", "/contacts/", payload)
        contact = res.get("contact", {})
        return contact.get("id")

    def execute_production_sync(
        self,
        new_records: List[Dict[str, Any]],
        updates_needed: List[Dict[str, Any]],
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Dict[str, int]:
        """Ejecuta la sincronización real en Atlion CRM."""
        stats = {"created": 0, "updated": 0, "errors": 0}
        total_ops = len(new_records) + len(updates_needed)
        current_op = 0

        # 1. Procesar Actualizaciones
        for item in updates_needed:
            current_op += 1
            atlion_info = item["atlion"]
            pst_info = item["pst"]
            cid = atlion_info.get("id")
            current_phone = atlion_info.get("phone", "").strip()
            existing_tags = set(atlion_info.get("tags") or [])

            raw_tel = pst_info.get("telefono", "")
            phone_info = process_client_phones_with_baileys(raw_tel, verifier=self.verifier)
            primary = phone_info["primary_phone"]
            has_wa = phone_info["has_whatsapp"]
            wa_numbers = phone_info.get("wa_numbers", [])

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

            additional_phones = []
            for p in atlion_info.get("additional_phones", []):
                additional_phones.append({"phone": p, "phoneLabel": "Anterior"})

            for extra in item.get("brand_new_phones", []):
                if extra != target_phone and extra not in [ap["phone"] for ap in additional_phones]:
                    lbl = "WhatsApp" if extra in wa_numbers else "Fijo"
                    additional_phones.append({"phone": extra, "phoneLabel": lbl})

            ok = self.update_contact_phones_and_tags(
                contact_id=cid,
                phone=target_phone or None,
                additional_phones=additional_phones if additional_phones else None,
                tags=final_tags
            )
            if ok:
                stats["updated"] += 1
            else:
                stats["errors"] += 1

            if progress_callback:
                pct = current_op / max(1, total_ops)
                progress_callback(f"Actualizando existentes en Atlion ({current_op}/{total_ops})...", pct)

        # 2. Procesar Creaciones
        for client in new_records:
            current_op += 1
            cid = self.create_contact(client)
            if cid:
                stats["created"] += 1
            else:
                stats["errors"] += 1

            if progress_callback:
                pct = current_op / max(1, total_ops)
                progress_callback(f"Creando nuevos contactos en Atlion ({current_op}/{total_ops})...", pct)

        return stats
