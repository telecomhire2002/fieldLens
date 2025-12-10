# app/main.py
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routes import jobs, whatsapp, auth
from app.services.ocr import _easyocr  # lazy loader you already have


# ---------------------------------------
# Storage root (local mode on HF Spaces)
# ---------------------------------------
DEFAULT_STORAGE = "/tmp/_local_uploads"  # HF allows only /tmp
LOCAL_STORAGE_DIR = os.getenv("LOCAL_STORAGE_DIR", DEFAULT_STORAGE)
os.makedirs(LOCAL_STORAGE_DIR, exist_ok=True)

# ---------------------------------------
# Public base (used for example images)
# ---------------------------------------
# set this in HF secrets: APP_BASE_URL=https://<owner>-<space>.hf.space
APP_BASE_URL = os.getenv("APP_BASE_URL", "").rstrip("/")

# ---------------------------------------
# App
# ---------------------------------------
app = FastAPI(title="Photo Verify API", version="1.0")


# ---------------------------------------
# Warm-up (preload EasyOCR)
# ---------------------------------------
@app.on_event("startup")
def _warmup_ocr():
    try:
        _ = _easyocr()  # triggers model load on process start
        print("[OCR] EasyOCR reader is warmed up.")
    except Exception as e:
        # Not fatal; the reader will lazy-load on first call
        print("[OCR] Warmup failed (will lazy-load later):", repr(e))


# ---------------------------------------
# CORS
# ---------------------------------------
# Frontend domains
PROD_DOMAIN = os.getenv("VERCEL_PROD_DOMAIN", "field-lens-sable.vercel.app")  # if you have a custom Vercel domain, put it here
CUSTOM_WEB_DOMAIN = os.getenv("WEB_APP_DOMAIN")  # e.g. app.yourco.com (optional)

# Local dev (keep for occasional local testing)
LOCAL_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]

# Build exact allowed origins set
EXACT_ORIGINS = set(LOCAL_ORIGINS + [f"https://{PROD_DOMAIN}"])
if CUSTOM_WEB_DOMAIN:
    EXACT_ORIGINS.add(f"https://{CUSTOM_WEB_DOMAIN}")
# If APP_BASE_URL is set, include that origin too
if APP_BASE_URL:
    EXACT_ORIGINS.add(APP_BASE_URL)

# Regex for Vercel previews and Hugging Face Spaces
VERCEL_REGEX = r"^https://([a-z0-9-]+\.)*vercel\.app$"
HF_REGEX = r"^https://[a-z0-9-]+-[a-z0-9-]+\.hf\.space$"
COMBINED_REGEX = f"(?:{VERCEL_REGEX})|(?:{HF_REGEX})"

app.add_middleware(
    CORSMiddleware,
    # IMPORTANT: when allow_credentials=True you must NOT use "*"
    allow_origins=list(EXACT_ORIGINS),
    allow_origin_regex=COMBINED_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    expose_headers=["Content-Disposition"],  # lets browsers read filename on downloads
)


# ---------------------------------------
# Static mounts
# ---------------------------------------
# uploads (always; LOCAL_STORAGE_DIR is created above)
app.mount("/uploads", StaticFiles(directory=LOCAL_STORAGE_DIR), name="uploads")

# /static (examples for TwiML). If missing, skip instead of crashing.
if os.path.isdir("app/static"):
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
else:
    print("[WARN] Skipping /static mount: 'app/static' not found")

# /admin is optional; skip if folder isn't present (HF Spaces often excludes it)
if os.path.isdir("admin"):
    app.mount("/admin", StaticFiles(directory="admin", html=True), name="admin")
else:
    print("[INFO] Skipping /admin mount: 'admin' not found")


# ---------------------------------------
# Routers
# ---------------------------------------
app.include_router(jobs.router,     prefix="/api", tags=["jobs"])
app.include_router(whatsapp.router, prefix="/api", tags=["whatsapp"])
app.include_router(auth.router, prefix="/api", tags=["auth"])

# ---------------------------------------
# Health & root
# ---------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"ok": True, "docs": "/docs"}


# ---------------------------------------
# Twilio Debugger / Error Webhook
# ---------------------------------------
@app.post("/whatsapp/error")
async def twilio_error_webhook(request: Request) -> dict[str, Any]:
    """
    Twilio Debugger often posts as x-www-form-urlencoded.
    Be permissive: try JSON, then form, else log raw body.
    Never raise here.
    """
    ctype = request.headers.get("content-type", "")
    payload: dict[str, Any] = {}

    try:
        if "application/json" in ctype.lower():
            payload = await request.json()
        else:
            form = await request.form()
            payload = dict(form)
    except Exception as e:
        raw = (await request.body())[:2000]
        print("[TWILIO DEBUGGER RAW]", raw)
        print("[TWILIO DEBUGGER PARSE ERROR]", e)

    print("[TWILIO DEBUGGER PAYLOAD]", payload)
    return {"status": "received"}
