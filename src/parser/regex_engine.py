import re
from typing import Optional, Dict, Any

CUIT_REGEX = re.compile(r"\b(20|23|24|27|30|33|34)[-]?(\d{8})[-]?(\d)\b")

def validate_cuit(cuit_str: str) -> bool:
    clean_cuit = re.sub(r"\D", "", cuit_str)
    if len(clean_cuit) != 11:
        return False
    multipliers = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    total = sum(int(digit) * mult for digit, mult in zip(clean_cuit[:10], multipliers))
    mod = total % 11
    verifier = 0 if (11 - mod) == 11 else (9 if (11 - mod) == 10 else (11 - mod))
    return verifier == int(clean_cuit[10])

def format_cuit(cuit_str: str) -> str:
    """Devuelve el CUIT limpio solo con números (ej: 20441769734)."""
    return re.sub(r"\D", "", cuit_str)

def _find_field(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else ""

def parse_direccion(dir_text: str) -> Dict[str, str]:
    """Separa la dirección en partes individuales."""
    parts = {
        "calle": "", "altura": "", "piso": "", "departamento": "",
        "codigo_postal": "", "localidad": "", "provincia": ""
    }
    if not dir_text:
        return parts

    patterns = {
        "calle": r"calle:\s*([^;]+)",
        "altura": r"altura:\s*([^;]+)",
        "piso": r"piso:\s*([^;]*)",
        "departamento": r"departamento:\s*([^;]*)",
        "codigo_postal": r"C\.P\.:\s*([^;]+)",
        "localidad": r"localidad:\s*([^;]+)",
        "provincia": r"provincia:\s*([^;\n\r]+)",
    }
    for field, pat in patterns.items():
        m = re.search(pat, dir_text, re.IGNORECASE)
        if m:
            parts[field] = m.group(1).strip()
    return parts

def extract_ticket_data(subject: str, body: str) -> Optional[Dict[str, Any]]:
    full_text = f"{subject}\n{body}"

    # CUIT
    cuit_match = _find_field(r"Cuit\s+Nro:\s*(\d+)", full_text)
    if not cuit_match:
        m = CUIT_REGEX.search(full_text)
        if m:
            cuit_match = f"{m.group(1)}{m.group(2)}{m.group(3)}"

    if not cuit_match or not validate_cuit(cuit_match):
        return None

    # Tier
    tier = _find_field(r"Tier:\s*\n*\s*([^\n\r]+)", body)
    if not tier and "CLIENTE VIP" in subject.upper():
        tier = "VIP"

    # Vendedor
    vendedor = _find_field(r"C[oó\ufffd]digo-nombre:\s*([^\n\r]+)", body)

    # Identificación del comercio
    razon_social = _find_field(r"Raz[oó\ufffd]n\s+Social:\s*([^\n\r]+)", body)
    nombre = _find_field(r"Destinatario:\s*\n*\s*Nombre:\s*([^\n\r]+)", body)

    # Desglose de dirección
    dir_raw = _find_field(r"Direcci[oó\ufffd]n\s+de\s+instalaci[oó\ufffd]n:\s*([^\n\r]+)", body)
    dir_parts = parse_direccion(dir_raw)

    # Contacto y Terminal
    telefono = _find_field(r"Tel[eé\ufffd]fono:\s*([^\n\r]+)", body)
    terminal = _find_field(r"Terminal\s+Posnet\s+Nro\s*[:=-]?\s*(\d+)", subject)
    mc = _find_field(r"MC\s*-->\s*(\d+)", body)
    denominacion = _find_field(r"Denominaci[oó\ufffd]n:\s*([^\n\r]+)", body)

    # Otros
    zona = _find_field(r"Zona:\s*([^\n\r]+)", body)
    observaciones = _find_field(r"Observaciones:\s*\n*\s*([^\n\r]+)", body)
    otros_parts = []
    if zona: otros_parts.append(f"Zona: {zona}")
    if observaciones: otros_parts.append(f"Obs: {observaciones}")
    otros = " | ".join(otros_parts)

    return {
        "cuit": format_cuit(cuit_match),
        "razon_social": razon_social,
        "nombre": nombre,
        "tier": tier,
        "terminal": terminal,
        "mc": mc,
        "denominacion": denominacion,
        "calle": dir_parts["calle"],
        "altura": dir_parts["altura"],
        "piso": dir_parts["piso"],
        "departamento": dir_parts["departamento"],
        "codigo_postal": dir_parts["codigo_postal"],
        "localidad": dir_parts["localidad"],
        "provincia": dir_parts["provincia"],
        "telefono": telefono,
        "vendedor": vendedor,
        "otros": otros
    }
