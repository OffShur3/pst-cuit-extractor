import re
from typing import List, Dict, Optional, Tuple

DUMMY_PATTERNS = [
    r"^1+$", r"^0+$", r"^2+$", r"^3+$", r"^4+$", r"^5+$",
    r"^6+$", r"^7+$", r"^8+$", r"^9+$",
    r"^1234", r"^2323", r"^1121", r"^4545"
]

KNOWN_AREAS = [
    "2966", "2902", "2962", "2901", "2974", "297", "296",
    "341", "3462", "3464", "3465", "3467", "3468", "3469", "3460",
    "3400", "3401", "3402", "3471", "3476", "3382", "336",
    "2473", "2477", "351", "381", "11"
]

def clean_digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")

def is_dummy_number(digits: str) -> bool:
    if len(digits) < 7:
        return True
    if len(set(digits)) <= 1:
        return True
    for pat in DUMMY_PATTERNS:
        if re.search(pat, digits):
            return True
    return False

def clean_raw_string(raw_str: str) -> str:
    s = raw_str or ""
    s = re.sub(r"\$sr\.[a-zA-Z0-9_.]+", " ", s)
    s = re.sub(r"\b(celular|cel|fijo|telefono|te|terminal|fany|florenci)\b", " ", s, flags=re.IGNORECASE)
    return s

def split_raw_phones(raw_str: str) -> List[str]:
    cleaned = clean_raw_string(raw_str)
    parts = re.split(r"[/|;,oOyY\n\r]+", cleaned)
    return [p.strip() for p in parts if p.strip()]

def fix_duplicated_area_code(digits: str) -> str:
    if digits.startswith("0034104"):
        digits = "3414" + digits[7:]
    elif digits.startswith("003410"):
        digits = "341" + digits[6:]
    elif digits.startswith("00341"):
        digits = "341" + digits[5:]
    elif digits.startswith("034104"):
        digits = "3414" + digits[6:]

    if digits.startswith("0966") or digits.startswith("966"):
        digits = "2966" + (digits[4:] if digits.startswith("0966") else digits[3:])

    if digits.startswith("0"):
        digits = digits[1:]

    for area in KNOWN_AREAS:
        double_area = f"{area}{area}"
        if digits.startswith(double_area):
            digits = area + digits[len(double_area):]
            break
        double_area_with_zero = f"{area}0{area}"
        if digits.startswith(double_area_with_zero):
            digits = area + digits[len(double_area_with_zero):]
            break

    return digits

def normalize_to_arg_international(phone_candidate: str) -> Optional[Tuple[str, str]]:
    digits = clean_digits(phone_candidate)
    digits = fix_duplicated_area_code(digits)

    if is_dummy_number(digits):
        return None

    if digits.startswith("549"):
        digits = digits[3:]
    elif digits.startswith("54"):
        digits = digits[2:]

    if digits.startswith("0"):
        digits = digits[1:]

    for area in KNOWN_AREAS:
        if digits.startswith(area):
            rest = digits[len(area):]
            if rest.startswith("15"):
                digits = area + rest[2:]
            break

    if len(digits) == 10:
        return (f"+549{digits}", f"549{digits}")

    if len(digits) == 8:
        if digits.startswith("15"):
            return (f"+549341{digits[2:]}", f"549341{digits[2:]}")
        elif not is_dummy_number(digits):
            return (f"+549341{digits}", f"549341{digits}")

    if len(digits) == 11 and digits.startswith("9"):
        return (f"+54{digits}", f"54{digits}")

    return None

def process_client_phones_with_baileys(raw_phones_str: str, verifier=None) -> Dict[str, any]:
    candidates = split_raw_phones(raw_phones_str)
    normalized_pairs = []

    for c in candidates:
        norm = normalize_to_arg_international(c)
        if norm and norm not in normalized_pairs:
            normalized_pairs.append(norm)

    if not normalized_pairs:
        return {
            "primary_phone": "",
            "has_whatsapp": False,
            "has_landline": False,
            "wa_numbers": [],
            "landline_numbers": [],
            "additional_phones": [],
            "all_details": []
        }

    wa_confirmed = []
    landlines = []
    all_details = []

    to_check = [clean for e164, clean in normalized_pairs]
    verification_results = verifier.verify_phones_batch(to_check) if verifier else {}

    for e164, clean in normalized_pairs:
        has_wa = verification_results.get(clean, False)
        if has_wa:
            wa_confirmed.append(e164)
            all_details.append({"phone": e164, "is_wa": True, "label": "🟢 WhatsApp"})
        else:
            landlines.append(e164)
            all_details.append({"phone": e164, "is_wa": False, "label": "🔴 Fijo / Sin WhatsApp"})

    # Selección inteligente:
    # 1. Si hay WhatsApp, el primer WhatsApp es el primario.
    # 2. Los demás quedan en adicionales.
    if wa_confirmed:
        primary = wa_confirmed[0]
        has_wa = True
        others = wa_confirmed[1:] + landlines
    else:
        primary = landlines[0]
        has_wa = False
        others = landlines[1:]

    return {
        "primary_phone": primary,
        "has_whatsapp": has_wa,
        "has_landline": len(landlines) > 0,
        "wa_numbers": wa_confirmed,
        "landline_numbers": landlines,
        "additional_phones": others,
        "all_details": all_details
    }

process_client_phones = process_client_phones_with_baileys
