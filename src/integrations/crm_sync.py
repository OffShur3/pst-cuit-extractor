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

    def _api_call(self, method: str, endpoint: str, payload: Optional[Dict] = None, max_retries: int = 4) -> Dict[str, Any]:
        import urllib.request
        import urllib.error
        import time

        url = f"{self.api_url}{endpoint}"
        data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Version": self.api_ver,
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"

        # Cadencia preventiva para respetar el limite de LeadConnector (100 req / 10 seg)
        time.sleep(0.11)

        for attempt in range(max_retries):
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                # 429 = Rate limit | 500, 502, 503, 504 = Errores temporales de GoHighLevel/Cloudflare
                if e.code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                    retry_header = e.headers.get("Retry-After")
                    wait_sec = float(retry_header) if retry_header else (attempt + 1) * 1.5
                    time.sleep(wait_sec)
                    continue
                try:
                    return json.loads(e.read().decode("utf-8"))
                except Exception:
                    return {"statusCode": e.code, "message": str(e)}
            except Exception as e:
                # Timeouts, resets de conexion o caidas momentaneas de red
                if attempt < max_retries - 1:
                    time.sleep((attempt + 1) * 1.2)
                    continue
                return {"message": str(e)}

        return {}

    def get_atlion_contacts_map(
        self,
        progress_callback: Optional[Callable[[str, float], None]] = None,
        max_cache_age_hours: float = 12.0
    ) -> Dict[str, Dict[str, Any]]:
        """
        Descarga o recupera desde cache local los contactos de Atlion CRM.
        Si la cache tiene menos de 12 horas, carga en 0.01s sin esperar 15 minutos.
        """
        import time
        cache_file = BASE_DIR / "data" / "atlion_contacts_cache.json"

        # 1. Comprobar cache local existente
        if cache_file.exists():
            age_hours = (time.time() - cache_file.stat().st_mtime) / 3600.0
            if age_hours < max_cache_age_hours:
                try:
                    cached_map = json.loads(cache_file.read_text(encoding="utf-8"))
                    if cached_map and len(cached_map) > 500:
                        if progress_callback:
                            progress_callback(f"Cargados {len(cached_map):,} contactos de Atlion desde cache local (0s)...", 0.10)
                        return cached_map
                except Exception:
                    pass

        # 2. Descargar de la nube si no hay cache o expiro
        atlion_map = {}
        start_after = None
        start_after_id = None
        total_fetched = 0
        
        while True:
            endpoint = f"/contacts/?locationId={self.location_id}&limit=100"
            if start_after and start_after_id:
                endpoint += f"&startAfter={start_after}&startAfterId={start_after_id}"
            
            res = self._api_call("GET", endpoint)
            contacts = res.get("contacts", [])
            if not contacts:
                break
                
            total_fetched += len(contacts)
            if progress_callback and total_fetched % 500 == 0:
                progress_callback(f"Descargando de Atlion CRM ({total_fetched:,} contactos)...", 0.08)

            for c in contacts:
                cid = c.get("id")
                cphone = (c.get("phone") or "").strip()
                cname = c.get("contactName") or f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
                
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
                
        # Guardar en cache local para no volver a esperar 15 minutos hoy
        if atlion_map:
            try:
                cache_file.parent.mkdir(exist_ok=True)
                cache_file.write_text(json.dumps(atlion_map, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

        return atlion_map

    def get_existing_cuits(self) -> Set[str]:
        return set(self.get_atlion_contacts_map().keys())

    def update_contact_phones_and_tags(
        self,
        contact_id: str,
        phone: Optional[str],
        additional_phones: Optional[List[Any]],
        tags: List[str]
    ) -> bool:
        """Actualiza el teléfono principal, adicionales y tags con fallback escalonado."""
        payload: Dict[str, Any] = {
            "tags": tags
        }
        if phone:
            payload["phone"] = phone
        if additional_phones:
            clean_list = []
            for item in additional_phones:
                num = item.get("phone") if isinstance(item, dict) else str(item)
                if num and num != phone and num not in [x["phone"] for x in clean_list]:
                    clean_list.append({"phone": num})
            if clean_list:
                payload["additionalPhones"] = clean_list

        # Nivel 1: Actualizacion completa
        res = self._api_call("PUT", f"/contacts/{contact_id}", payload, max_retries=5)
        if res.get("contact", {}).get("id"):
            return True

        # Nivel 2: Si fallaron los adicionales, actualizar solo telefono principal y tags
        if "additionalPhones" in payload:
            fallback_payload = {"phone": phone, "tags": tags} if phone else {"tags": tags}
            res2 = self._api_call("PUT", f"/contacts/{contact_id}", fallback_payload, max_retries=3)
            if res2.get("contact", {}).get("id"):
                return True

        # Nivel 3: Si el telefono entra en conflicto, actualizar al menos los tags
        res3 = self._api_call("PUT", f"/contacts/{contact_id}", {"tags": tags}, max_retries=3)
        return bool(res3.get("contact", {}).get("id"))

    def update_contact_phone(self, contact_id: str, phone: str, tags: List[str]) -> bool:
        """Compatibilidad hacia atrás."""
        return self.update_contact_phones_and_tags(contact_id, phone=phone, additional_phones=None, tags=tags)

    def create_contact(self, client_data: Dict[str, Any]) -> Optional[str]:
        """Crea un contacto nuevo en Atlion con reintentos y tolerancia máxima a fallos."""
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

        clean_extras = []
        for extra in phone_info.get("additional_phones", []):
            num = extra.get("phone") if isinstance(extra, dict) else str(extra)
            if num and num != primary_phone and num not in [x["phone"] for x in clean_extras]:
                clean_extras.append({"phone": num})

        calle = (client_data.get("calle") or "").strip()
        altura = (client_data.get("altura") or "").strip()
        address1 = f"{calle} {altura}".strip()

        payload = {
            "firstName": first_name[:40],
            "lastName": last_name[:40],
            "name": f"{first_name} {last_name}".strip(),
            "locationId": self.location_id,
            "tags": tags,
            "customFields": [{"id": self.cuit_field_id, "value": cuit}]
        }

        if primary_phone:
            payload["phone"] = primary_phone
        if address1:
            payload["address1"] = address1
        if client_data.get("localidad"):
            payload["city"] = str(client_data.get("localidad")).strip()
        if client_data.get("provincia"):
            payload["state"] = str(client_data.get("provincia")).strip()
        if client_data.get("codigo_postal"):
            payload["postalCode"] = str(client_data.get("codigo_postal")).strip()
        if clean_extras:
            payload["additionalPhones"] = clean_extras

        # Intento 1: Payload completo (5 reintentos en caidas de red o 500)
        res = self._api_call("POST", "/contacts/", payload, max_retries=5)
        contact = res.get("contact", {})
        cid = contact.get("id")

        # Si el telefono ya existia en Atlion, GHL devuelve el contactId en meta
        if not cid and res.get("meta", {}).get("contactId"):
            cid = res["meta"]["contactId"]
            self._api_call("PUT", f"/contacts/{cid}", {
                "customFields": [{"id": self.cuit_field_id, "value": cuit}]
            })
            return cid

        # Intento 2 (Fallback sin extras): Si algun numero adicional reboto en la validacion
        if not cid and clean_extras:
            payload_no_extras = dict(payload)
            payload_no_extras.pop("additionalPhones", None)
            res2 = self._api_call("POST", "/contacts/", payload_no_extras, max_retries=3)
            cid = res2.get("contact", {}).get("id") or res2.get("meta", {}).get("contactId")
            if cid:
                if res2.get("meta", {}).get("contactId"):
                    self._api_call("PUT", f"/contacts/{cid}", {
                        "customFields": [{"id": self.cuit_field_id, "value": cuit}]
                    })
                return cid

        # Intento 3 (Fallback definitivo): Si el telefono principal reboto por duplicado o formato, registrar CUIT limpio
        if not cid and primary_phone:
            payload_safe = dict(payload)
            payload_safe.pop("phone", None)
            payload_safe.pop("additionalPhones", None)
            payload_safe["tags"] = [t for t in payload_safe["tags"] if t not in ("tiene-whatsapp", "solo-telefono-fijo", "tiene-fijo")] + ["telefono-en-conflicto"]
            res3 = self._api_call("POST", "/contacts/", payload_safe, max_retries=3)
            cid = res3.get("contact", {}).get("id") or res3.get("meta", {}).get("contactId")
            if cid and res3.get("meta", {}).get("contactId"):
                self._api_call("PUT", f"/contacts/{cid}", {
                    "customFields": [{"id": self.cuit_field_id, "value": cuit}]
                })

        return cid

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

        # Bloquear invocaciones a Node.js durante la subida masiva: lectura pura desde SQLite
        self.verifier.cache_only = True

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
