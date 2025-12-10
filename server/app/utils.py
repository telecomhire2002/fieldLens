# app/utils.py
from __future__ import annotations
import os
import re
from typing import List

# ---------------------------------------------------------------------
# Robust .env loading (works from repo root OR /server working dir)
# ---------------------------------------------------------------------
try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(usecwd=True))
except Exception:
    pass  # ok if python-dotenv isn't installed

# ---------------------------------------------------------------------
# Twilio REST client (optional; won't crash if missing)
# ---------------------------------------------------------------------
try:
    from twilio.rest import Client as _TwilioClient  # type: ignore
except Exception:
    _TwilioClient = None  # dev environments without twilio are fine

TWILIO_ACCOUNT_SID   = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "")

twilio_client = None
if _TwilioClient and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    try:
        twilio_client = _TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    except Exception:
        twilio_client = None

# ---------------------------------------------------------------------
# Public/base URLs — safe defaults (no hard raise)
# ---------------------------------------------------------------------
APP_BASE_URL = os.getenv("APP_BASE_URL") or "http://localhost:8000"
EXAMPLE_URL_LABEL   = os.getenv("PUBLIC_EXAMPLE_URL_LABEL")   or f"{APP_BASE_URL}/static/examples/labelling.jpeg"
EXAMPLE_URL_AZIMUTH = os.getenv("PUBLIC_EXAMPLE_URL_AZIMUTH") or f"{APP_BASE_URL}/static/examples/azimuth.jpeg"

def _sanitize_example_url(u: str | None) -> str:
    if not u:
        return ""
    return u.replace(".jped", ".jpeg").strip()

# ---------------------------------------------------------------------
# Type registry (your 14-step flow + prompts & examples)
# validated=False here is OK; validation decision is done by is_validated_type()
# ---------------------------------------------------------------------
TYPE_REGISTRY = {
    "INSTALLATION": {
        "label": "Installation",
        "prompt": "Send the *Installation* photo (full view). 📸 *स्थापना* की पूरी फोटो भेजो (पूरा सेटअप दिखे).",
        "example_env": "PUBLIC_EXAMPLE_URL_INSTALLATION",
        "example_default": f"{APP_BASE_URL}/static/examples/installation.jpeg",
        "validated": False,
    },
    "CLUTTER": {
        "label": "Clutter",
        "prompt": "Send the *Clutter* photo (surroundings, wide). 📸 *Clutter/आस-पास* की चौड़ी फोटो भेजो (चारों तरफ दिखे).",
        "example_env": "PUBLIC_EXAMPLE_URL_CLUTTER",
        "example_default": f"{APP_BASE_URL}/static/examples/clutter.jpeg",
        "validated": False,
    },
    "AZIMUTH": {
        "label": "Azimuth Photo",
        "prompt": "Send the *Azimuth* photo. Compass reading must be CLEAR. 🧭 *Azimuth* की फोटो भेजो. कम्पास रीडिंग साफ दिखनी चाहिए.",
        "example_env": "PUBLIC_EXAMPLE_URL_AZIMUTH",
        "example_default": f"{APP_BASE_URL}/static/examples/azimuth.jpeg",
        "validated": False,
    },
    "A6_GROUNDING": {
        "label": "A6 Grounding",
        "prompt": "Send *A6 Grounding* photo (lugs & conductor visible). 🔧 *A6 ग्राउंडिंग* की फोटो भेजो (लग्स और तार साफ दिखें).",
        "example_env": "PUBLIC_EXAMPLE_URL_A6_GROUNDING",
        "example_default": f"{APP_BASE_URL}/static/examples/a6_grounding.jpeg",
        "validated": False,
    },
    "CPRI_GROUNDING": {
        "label": "CPRI Grounding",
        "prompt": "Send *CPRI Grounding* photo (bond points visible). *CPRI ग्राउंडिंग* की फोटो भेजो (बॉन्ड/जॉइंट दिखे).",
        "example_env": "PUBLIC_EXAMPLE_URL_CPRI_GROUNDING",
        "example_default": f"{APP_BASE_URL}/static/examples/cpri_grounding.jpeg",
        "validated": False,
    },
    "POWER_TERM_A6": {
        "label": "POWER Termination at A6",
        "prompt": "Send *POWER Termination at A6* close-up. *A6 पर पावर टर्मिनेशन* की नज़दीक से फोटो भेजो (ग्लेयर न हो).",
        "example_env": "PUBLIC_EXAMPLE_URL_POWER_TERM_A6",
        "example_default": f"{APP_BASE_URL}/static/examples/power_term_a6.jpeg",
        "validated": False,
    },
    "CPRI_TERM_A6": {
        "label": "CPRI Termination at A6",
        "prompt": "Send *CPRI Termination at A6* photo (connector seated). *A6 पर CPRI टर्मिनेशन* की फोटो भेजो (कनेक्टर ठीक से लगा हो).",
        "example_env": "PUBLIC_EXAMPLE_URL_CPRI_TERM_A6",
        "example_default": f"{APP_BASE_URL}/static/examples/cpri_term_a6.jpeg",
        "validated": False,
    },
    "TILT": {
        "label": "Tilt",
        "prompt": "Send *Tilt* photo (tilt value clearly visible). *Tilt* की फोटो भेजो (टिल्ट लिखावट साफ दिखे).",
        "example_env": "PUBLIC_EXAMPLE_URL_TILT",
        "example_default": f"{APP_BASE_URL}/static/examples/tilt.jpeg",
        "validated": False,
    },
    "LABELLING": {
        "label": "Labelling",
        "prompt": "Send *Labelling* photo (all labels readable). 🏷️ *लेबलिंग* की फोटो भेजो (सारे लेबल साफ पढ़े जा सकें).",
        "example_env": "PUBLIC_EXAMPLE_URL_LABELLING",
        "example_default": f"{APP_BASE_URL}/static/examples/labelling.jpeg",
        "validated": False,
    },
    "ROXTEC": {
        "label": "Roxtec",
        "prompt": "Send *Roxtec* sealing photo (modules visible). *Roxtec सीलिंग* की फोटो भेजो (मॉड्यूल साफ दिखें).",
        "example_env": "PUBLIC_EXAMPLE_URL_ROXTEC",
        "example_default": f"{APP_BASE_URL}/static/examples/roxtec.jpeg",
        "validated": False,
    },
    "A6_TOWER": {
        "label": "A6 Tower",
        "prompt": "Send *A6 Tower* overview photo. *A6 टावर* की पूरी फोटो भेजो (पूरा पैनल दिखे).",
        "example_env": "PUBLIC_EXAMPLE_URL_A6_TOWER",
        "example_default": f"{APP_BASE_URL}/static/examples/a6_tower.jpeg",
        "validated": False,
    },
    "MCB_POWER": {
        "label": "MCB Power",
        "prompt": "Send *MCB Power* photo (breaker & rating visible). *MCB पावर* की फोटो भेजो (ब्रेक़र और रेटिंग साफ दिखे).",
        "example_env": "PUBLIC_EXAMPLE_URL_MCB_POWER",
        "example_default": f"{APP_BASE_URL}/static/examples/mcb_power.jpeg",
        "validated": False,
    },
    "CPRI_TERM_SWITCH_CSS": {
        "label": "CPRI Termination at Switch-CSS",
        "prompt": "Send *CPRI Termination at Switch-CSS* photo. *Switch-CSS पर CPRI टर्मिनेशन* की फोटो भेजो.",
        "example_env": "PUBLIC_EXAMPLE_URL_CPRI_TERM_SWITCH_CSS",
        "example_default": f"{APP_BASE_URL}/static/examples/cpri_term_switch_css.jpeg",
        "validated": False,
    },
    "GROUNDING_OGB_TOWER": {
        "label": "Grounding at OGB Tower",
        "prompt": "Send *Grounding at OGB Tower* photo (bonding clear). *OGB टॉवर ग्राउंडिंग* की फोटो भेजो (बॉन्डिंग साफ दिखे).",
        "example_env": "PUBLIC_EXAMPLE_URL_GROUNDING_OGB_TOWER",
        "example_default": f"{APP_BASE_URL}/static/examples/grounding_ogb_tower.jpeg",
        "validated": False,
    },
}

# ---------------------------------------------------------------------
# Canonical type helpers used across app (LABEL / AZIMUTH, etc.)
# ---------------------------------------------------------------------
_TYPE_ALIASES = {
    "label": "LABEL",
    "labelling": "LABEL",
    "labeling": "LABEL",
    "angle": "AZIMUTH",
    "azimuth": "AZIMUTH",
    "azi": "AZIMUTH",
}

def canonical_type(ptype: str | None) -> str:
    if not ptype:
        return "PHOTO"
    k = str(ptype).strip().upper()
    return _TYPE_ALIASES.get(k.lower(), k)

# def type_label(ptype: str | None) -> str:
#     c = canonical_type(ptype)
#     # Prefer registry label if we have it
#     if c in TYPE_REGISTRY and TYPE_REGISTRY[c].get("label"):
#         return TYPE_REGISTRY[c]["label"]
#     if c == "LABEL":
#         return "Label Photo"
#     if c == "AZIMUTH":
#         return "Azimuth Photo"
#     return (c or "Photo").replace("_", " ").title()

# (keep your existing type_label() helper as-is, or ensure it handles these names)
def type_label(t: str) -> str:
    """Human labels used in UI (extend as needed)."""
    T = (t or "").upper()
    return {
        "INSTALLATION": "Installation Overview",
        "CLUTTER": "Clutter",
        "AZIMUTH": "Azimuth / Compass",
        "A6_GROUNDING": "A6 Grounding",
        "CPRI_GROUNDING": "CPRI Grounding",
        "POWER_TERM_A6": "Power Termination (A6)",
        "CPRI_TERM_A6": "CPRI Termination (A6)",
        "TILT": "Antenna Tilt",
        "LABELLING": "Device Label (MAC/RSN)",
        "ROXTEC": "Roxtec Seal",
        "A6_TOWER": "A6 Tower",
        "MCB_POWER": "MCB Power",
        "CPRI_TERM_SWITCH_CSS": "CPRI Termination (Switch/CSS)",
        "GROUNDING_OGB_TOWER": "Grounding OGB / Tower",
    }.get(T, T.title())

def is_validated_type(ptype: str | None) -> bool:
    """
    Which types should go through OCR/validation. Registry 'validated' is ignored here;
    we explicitly validate only LABEL and AZIMUTH (per your pipeline).
    """
    return canonical_type(ptype) in {"LABEL", "AZIMUTH"}

def type_example_url(ptype: str | None) -> str:
    c = canonical_type(ptype)
    # First prefer registry env key if provided
    if c in TYPE_REGISTRY:
        env_key = TYPE_REGISTRY[c].get("example_env")
        if env_key and os.getenv(env_key):
            return _sanitize_example_url(os.getenv(env_key))
        if TYPE_REGISTRY[c].get("example_default"):
            return _sanitize_example_url(TYPE_REGISTRY[c]["example_default"])
    # Fallback to canonical examples
    return EXAMPLE_URL_AZIMUTH if c == "AZIMUTH" else EXAMPLE_URL_LABEL

def type_prompt(ptype: str | None) -> str:
    c = canonical_type(ptype)
    if c in TYPE_REGISTRY and TYPE_REGISTRY[c].get("prompt"):
        return TYPE_REGISTRY[c]["prompt"]
    if c == "AZIMUTH":
        return "Please send the **Azimuth Photo** showing a clear compass reading (e.g., 123° NE)."
    return "Please send the **Label Photo** with MAC & RSN clearly visible (flat, sharp, no glare)."

# ---------------------------------------------------------------------
# Sector → required types
# ---------------------------------------------------------------------
DEFAULT_14_TYPES = [
    "INSTALLATION",
    "CLUTTER",
    "AZIMUTH",
    "A6_GROUNDING",
    "CPRI_GROUNDING",
    "POWER_TERM_A6",
    "CPRI_TERM_A6",
    "TILT",
    "LABELLING",
    "ROXTEC",
    "A6_TOWER",
    "MCB_POWER",
    "CPRI_TERM_SWITCH_CSS",
    "GROUNDING_OGB_TOWER",
]

# Per-sector overrides if you need to vary order or omit a type.
# If a sector is not present here, we fall back to ALL_REQUIRED_14.
SECTOR_TEMPLATES: dict[str, List[str]] = {
    '1': DEFAULT_14_TYPES,        # same set for now (you can reorder if you like)
    '2': DEFAULT_14_TYPES,
    '3': DEFAULT_14_TYPES,
    # add more sectors here…
}

def build_required_types_for_sector(sector: str | None) -> List[str]:
    """
    Return the required photo-type codes for a given sector.
    If the sector is unknown/None, return the full 14-type list.
    """
    try:
        if sector is None:
            return DEFAULT_14_TYPES
        return SECTOR_TEMPLATES.get(sector, DEFAULT_14_TYPES)
    except Exception:
        # Never return the tiny two-item default again
        return DEFAULT_14_TYPES

# ---------------------------------------------------------------------
# Phone formatting + WhatsApp sender
# ---------------------------------------------------------------------
# def normalize_phone(p: str) -> str:
#     """
#     Normalize incoming phone; keep + if user sent it; strip other non-digits.
#     (We do NOT add 'whatsapp:' here—sending helpers will.)
#     """
#     if not p:
#         return ""
#     p = p.strip()
#     if p.startswith("+"):
#         return "+" + re.sub(r"\D", "", p)[91:]
#     return re.sub(r"\D", "", p)

def normalize_phone(p: str) -> str: 
    """Normalize incoming Twilio phone params to canonical 'whatsapp:+<E.164>'.""" 
    if not p: 
        return "" 
    digits = re.sub(r'\D', '', p) 
    return f"whatsapp:+{digits}" if digits else ""

def send_whatsapp_image(to_number: str, image_url: str, text: str = ""):
    """
    Sends an image via Twilio REST API, if configured.
    Safe no-op if twilio isn’t present or env is missing.
    """
    if not all([twilio_client, TWILIO_WHATSAPP_FROM, to_number, image_url]):
        print("[INFO] Twilio REST not fully configured; skipping send.")
        return None

    if not to_number.startswith("whatsapp:"):
        to_number = f"whatsapp:{to_number}"

    try:
        msg = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=to_number,
            body=text or None,
            media_url=[image_url],
        )
        print(f"[INFO] Sent example image to {to_number}, SID={msg.sid}")
        return msg.sid
    except Exception as e:
        print(f"[ERROR] Twilio send failed: {e}")
        return None

# ---------------------------------------------------------------------
# (Legacy) regex used elsewhere in the app (safe to keep)
# ---------------------------------------------------------------------
DEGREE_RE = re.compile(r"(?<!\d)([0-3]?\d{1,2})(?:\s*(?:°|deg|degrees)?)\b", re.IGNORECASE)
MAC_RE    = re.compile(r"\b([0-9A-F]{12})\b", re.IGNORECASE)
RSN_RE    = re.compile(r"\b(RSN|SR|SN)[:\s\-]*([A-Z0-9\-]{4,})\b", re.IGNORECASE)


def choose_active_sector(sectors: list[dict]) -> str | None:
    """
    Returns the next sector to work on:
    - Prefer the first sector with status IN_PROGRESS
    - Else first with PENDING
    - Else None if all DONE
    """
    if not sectors:
        return None
    for s in sectors:
        if (s.get("status") or "").upper() == "IN_PROGRESS":
            return str(s["sector"])
    for s in sectors:
        if (s.get("status") or "").upper() == "PENDING":
            return str(s["sector"])
    return None

# app/utils.py

def sector_by_id(sectors, sector_id):
    """
    Return the sector-block from a job's sectors list that matches sector_id.
    Your sectors are stored as strings (e.g. "1", "2"), so we compare as str.
    """
    if not sectors:
        return None

    target = str(sector_id)
    for s in sectors:
        if str(s.get("sector")) == target:
            return s
    return None


def all_sectors_done(sectors: list[dict]) -> bool:
    return all((s.get("status") or "").upper() == "DONE" for s in sectors or [])