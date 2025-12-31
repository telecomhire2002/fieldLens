import os
import re
import traceback
from typing import List, Optional, Dict, Any
from datetime import datetime
from io import BytesIO

import cv2
import httpx
from bson import ObjectId
from fastapi import APIRouter, Depends, Request, Response, Form, File, UploadFile, BackgroundTasks
from fastapi.responses import JSONResponse, PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse

from app.deps import get_db
from app.services.validate import run_pipeline
from app.services.imaging import load_bgr
from app.services.storage_s3 import new_image_key, put_bytes
from app.utils import (
    normalize_phone,
    type_prompt,
    type_example_url,
    is_validated_type,   # can stay
    twilio_client,       # Twilio REST client if configured
    TWILIO_WHATSAPP_FROM # whatsapp:from number
)

# NOTE:
# You already have these in your project somewhere (used in debug route).
# Keep them as-is; if they are in another module, import them there.
# from app.services.jobs import new_job

router = APIRouter()

# ---------------------------
# SIMPLIFIED HELPERS (single-sector job)
# ---------------------------

def _current_expected_type_for_job(job: Dict[str, Any]) -> Optional[str]:
    """Return the next required type for this job."""
    if not job:
        return None
    idx = int(job.get("currentIndex", 0) or 0)
    req = job.get("requiredTypes", []) or []
    if 0 <= idx < len(req):
        return req[idx]
    return None  # Job is complete

def is_job_done(job: Dict[str, Any]) -> bool:
    """Check if a single job is complete."""
    if not job:
        return True
    if job.get("status") == "DONE":
        return True
    idx = int(job.get("currentIndex", 0) or 0)
    req = job.get("requiredTypes", []) or []
    return idx >= len(req)

def _downscale_for_ocr(bgr, max_side: int = 1280):
    """Keep aspect; limit longest side to max_side for faster OCR."""
    h, w = bgr.shape[:2]
    m = max(h, w)
    if m <= max_side:
        return bgr
    scale = max_side / float(m)
    nh, nw = int(h * scale), int(w * scale)
    return cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)

# ---------------------------
# Worker selection session helpers
# ---------------------------

def get_session(db, workerPhone: str) -> Dict[str, Any]:
    return db.worker_sessions.find_one({"workerPhone": workerPhone}) or {}

def set_session(db, workerPhone: str, **updates):
    updates["workerPhone"] = workerPhone
    updates["updatedAt"] = datetime.utcnow()
    db.worker_sessions.update_one(
        {"workerPhone": workerPhone},
        {"$set": updates},
        upsert=True
    )

def clear_session(db, workerPhone: str):
    db.worker_sessions.delete_one({"workerPhone": workerPhone})

# ---------------------------
# Twilio / media utilities
# ---------------------------

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")

async def _fetch_media(url: str) -> bytes:
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        raise RuntimeError("Twilio auth not configured.")
    async with httpx.AsyncClient(
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        timeout=30,
        follow_redirects=True,
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content

def build_twiml_reply(body_text: str, media_urls: Optional[List[str] | str] = None) -> Response:
    resp = MessagingResponse()
    msg = resp.message(body_text)
    if isinstance(media_urls, str):
        media_urls = [media_urls]
    if media_urls:
        for m in media_urls:
            if m and m.lower().startswith(("http://", "https://")):
                msg.media(m)
    xml = str(resp)
    print("[TWIML OUT]\n", xml)
    return Response(content=xml, media_type="application/xml")

def _safe_example_list(example_url: Optional[str]) -> Optional[List[str]]:
    if not example_url:
        return None
    s = example_url.strip()
    return [s] if s.lower().startswith(("http://", "https://")) else None

# ---------------------------
# Background processor (single job)
# ---------------------------

def _process_and_notify(
    db,
    worker_number: str,
    job_id: str,
    image_bytes: bytes
):
    """
    Runs validation, updates DB/job, and proactively
    notifies the worker with next prompt or retake.
    """
    try:
        # 1) Reload fresh job
        try:
            oid = ObjectId(job_id) if not isinstance(job_id, ObjectId) else job_id
        except Exception:
            print("[BG] Invalid job_id; abort.")
            return

        job = db.jobs.find_one({"_id": oid})
        if not job:
            print("[BG] Job missing; abort.")
            return

        # 2) Expected type for this job
        expected = _current_expected_type_for_job(job)
        job_sector = job.get("sector")

        # 3) Decode + downscale (speed)
        img = load_bgr(image_bytes)
        if img is None:
            raise ValueError("decode_failed")
        img_small = _downscale_for_ocr(img)

        # 4) Previous phashes for THIS job & THIS expected type
        prev_phashes = [
            p.get("phash")
            for p in db.photos.find(
                {
                    "jobId": str(job["_id"]),
                    "sector": job_sector,
                    "type": (expected or "").upper(),
                    "status": {"$in": ["PASS", "FAIL"]},
                },
                {"phash": 1}
            )
            if p.get("phash")
        ]

        # 5) Validate
        result = run_pipeline(
            img_small,
            job_ctx={"expectedType": expected},
            existing_phashes=prev_phashes
        )

        # Promote important fields to job-level
        fields = result.get("fields") or {}
        updates: Dict[str, Any] = {}
        if fields.get("macId"):
            updates["macId"] = fields["macId"]
        if fields.get("rsn"):
            updates["rsnId"] = fields["rsn"]
        if fields.get("azimuthDeg") is not None:
            updates["azimuthDeg"] = fields["azimuthDeg"]
        if updates:
            db.jobs.update_one({"_id": job["_id"]}, {"$set": updates})

        result_type = (result.get("type") or expected or "LABELLING").upper()

        # 6) Update last inserted photo
        last_photo = db.photos.find_one({"jobId": str(job["_id"])}, sort=[("_id", -1)])
        if last_photo:
            db.photos.update_one(
                {"_id": last_photo["_id"]},
                {"$set": {
                    "type": result_type,
                    "phash": result.get("phash"),
                    "ocrText": result.get("ocrText"),
                    "fields": result.get("fields") or {},
                    "checks": result.get("checks") or {},
                    "status": result.get("status"),
                    "reason": result.get("reason") or [],
                }}
            )

        # 7) Advance THIS job's top-level index
        status = (result.get("status") or "").upper()
        if status == "PASS" and expected and result_type == expected:
            db.jobs.update_one(
                {"_id": job["_id"]},
                {"$inc": {"currentIndex": 1}}
            )
            job = db.jobs.find_one({"_id": job["_id"]})  # Reload

            # If the job finished, mark it DONE
            if is_job_done(job):
                db.jobs.update_one(
                    {"_id": job["_id"]},
                    {"$set": {"status": "DONE"}}
                )
                job = db.jobs.find_one({"_id": job["_id"]})

        # 8) Compose outbound message
        if (result.get("status") or "").upper() == "PASS":
            next_expected = _current_expected_type_for_job(job)
            if next_expected is None:
                text = (
                    "✅ Received and verified. Sector complete.\n"
                    "✅ सेक्टर पूरा हो गया। धन्यवाद!\n\n"
                    "Send 'hy' to start your next sector."
                )
                media = None
            else:
                prompt, example = type_prompt(next_expected), type_example_url(next_expected)
                text = f"✅ {result_type} verified.\nNext: {prompt}\nअब अगली फोटो भेजें।"
                media = example
        else:
            fallback_type = expected or result_type
            prompt, example = type_prompt(fallback_type), type_example_url(fallback_type)
            reasons = "; ".join(result.get("reason") or []) or "needs retake"
            text = (
                f"❌ {result_type} failed: {reasons}.\n"
                f"Please retake and resend.\n{prompt}\n"
                f"कृपया दोबारा साफ फोटो भेजें।"
            )
            media = example

        # 9) Send proactive WhatsApp message
        if twilio_client and TWILIO_WHATSAPP_FROM:
            to_number = worker_number if worker_number.startswith("whatsapp:") else f"whatsapp:{worker_number}"
            kwargs = {"from_": TWILIO_WHATSAPP_FROM, "to": to_number, "body": text}
            if media and media.lower().startswith(("http://", "https://")):
                kwargs["media_url"] = [media]
            msg = twilio_client.messages.create(**kwargs)
            print(f"[BG] Notified worker, SID={msg.sid}")
        else:
            print("[BG] Twilio REST not configured; outbound message skipped.")
            print("[BG] Would have sent:", text)

    except Exception as e:
        print("[BG] Pipeline/notify error:", repr(e))
        traceback.print_exc()

# ---------------------------
# Webhook (SITE -> SECTOR selection)
# ---------------------------

@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, background: BackgroundTasks, db=Depends(get_db)):
    """
    WhatsApp webhook (Twilio). Handles text prompts and image uploads.
    Selection order:
    1) Ask Site ID
    2) Then ask Sector ID (within that site)
    3) Then proceed with photo flow
    """
    # Parse body (Twilio sends form-encoded)
    try:
        form = await request.form()
    except Exception:
        try:
            _ = await request.json()
            return PlainTextResponse("Unsupported content-type", status_code=415)
        except Exception:
            return PlainTextResponse("Bad Request", status_code=400)

    from_param = form.get("From") or form.get("WaId") or ""
    from_num = normalize_phone(from_param)
    media_count = int(form.get("NumMedia") or 0)
    user_message_body = (form.get("Body") or "").strip()

    print(f"[INCOMING] From: {from_num} NumMedia: {media_count} Body: '{user_message_body}'")

    # Allow reset anytime
    if user_message_body.lower() in {"reset", "restart", "clear"}:
        clear_session(db, from_num)
        return build_twiml_reply(
            "✅ Selection reset.\nNow send Site ID.\n"
            "✅ चयन रीसेट हो गया। अब Site ID भेजें।"
        )

    # 1) Find all active jobs for this worker
    active_jobs = list(db.jobs.find({
        "workerPhone": from_num,
        "status": {"$in": ["PENDING", "IN_PROGRESS"]}
    }).limit(50))

    # 2) Prefer an IN_PROGRESS job if it exists and not done
    current_job: Optional[Dict[str, Any]] = None
    for j in active_jobs:
        if j.get("status") == "IN_PROGRESS" and not is_job_done(j):
            current_job = j
            break

    # If IN_PROGRESS is done, mark done and continue selection
    if current_job and is_job_done(current_job):
        db.jobs.update_one({"_id": current_job["_id"]}, {"$set": {"status": "DONE"}})
        current_job = None

    # 3) If no selected job, do Site -> Sector selection using session
    if not current_job:
        pending_jobs = [j for j in active_jobs if j.get("status") == "PENDING" and not is_job_done(j)]

        if not pending_jobs:
            clear_session(db, from_num)
            return build_twiml_reply(
                "No active job assigned yet. Please contact your supervisor.\n"
                "कोई सक्रिय जॉब असाइन नहीं है। कृपया सुपरवाइज़र से संपर्क करें।"
            )

        # Build unique site list
        site_ids = sorted({
            str(j.get("siteId", "")).strip()
            for j in pending_jobs
            if str(j.get("siteId", "")).strip()
        })

        if not site_ids:
            clear_session(db, from_num)
            return build_twiml_reply("Error: No Site IDs found in pending jobs.")

        session = get_session(db, from_num)
        selected_site = (session.get("selectedSiteId") or "").strip()

        # ---- STEP 1: SELECT SITE ----
        if not selected_site:
            typed = user_message_body.strip()

            # If user typed a valid Site ID, accept it
            if typed and typed in site_ids:
                selected_site = typed
                set_session(db, from_num, selectedSiteId=selected_site)
            else:
                lines = [f"➡️ {s}" for s in site_ids]
                return build_twiml_reply(
                    "Reply with the Site ID you are working on:\n\n"
                    "आप जिस Site ID पर काम कर रहे हैं वो भेजें:\n\n" +
                    "\n".join(lines)
                )

        # ---- STEP 2: SELECT SECTOR WITHIN SITE ----
        site_jobs = [
            j for j in pending_jobs
            if str(j.get("siteId", "")).strip() == selected_site
        ]

        sector_map: Dict[str, Dict[str, Any]] = {}
        for j in site_jobs:
            sec = j.get("sector")
            if sec:
                sector_map[str(sec).strip().upper()] = j

        if not sector_map:
            clear_session(db, from_num)
            return build_twiml_reply(
                f"No sectors found for Site ID: {selected_site}\n"
                f"इस Site ID के लिए कोई सेक्टर नहीं मिला: {selected_site}"
            )

        # Auto-pick if only 1 sector in the selected site
        if len(sector_map) == 1:
            current_job = list(sector_map.values())[0]
        else:
            typed_sector = user_message_body.strip().upper()
            if typed_sector in sector_map:
                current_job = sector_map[typed_sector]
            else:
                lines = [f"➡️ {s}" for s in sorted(sector_map.keys())]
                return build_twiml_reply(
                    f"Site selected: {selected_site}\n"
                    f"Now reply with Sector ID:\n\n"
                    f"Site चुना गया: {selected_site}\n"
                    f"अब Sector ID भेजें:\n\n" +
                    "\n".join(lines)
                )

        # Mark chosen job IN_PROGRESS, clear session
        db.jobs.update_one({"_id": current_job["_id"]}, {"$set": {"status": "IN_PROGRESS"}})
        current_job["status"] = "IN_PROGRESS"
        clear_session(db, from_num)

    # At this point, current_job MUST be set.

    # If job is done, mark done and restart selection
    if is_job_done(current_job):
        db.jobs.update_one({"_id": current_job["_id"]}, {"$set": {"status": "DONE"}})
        clear_session(db, from_num)
        return await whatsapp_webhook(request, background, db)

    expected_photo_type = _current_expected_type_for_job(current_job)
    job_sector_id = current_job.get("sector")

    # If text-only, (re)prompt with example
    if media_count == 0:
        fallback = expected_photo_type or "LABELLING"
        prompt, example = type_prompt(fallback), type_example_url(fallback)
        return build_twiml_reply(
            f"{prompt}\nSend 1 image at a time.\nएक समय में सिर्फ 1 फोटो भेजें।",
            media_urls=_safe_example_list(example),
        )

    # Ensure image content
    media_url = form.get("MediaUrl0")
    content_type = form.get("MediaContentType0", "")
    if not media_url or not content_type.startswith("image/"):
        fallback = expected_photo_type or "LABELLING"
        prompt, example = type_prompt(fallback), type_example_url(fallback)
        return build_twiml_reply(
            f"Please send a valid image. {prompt}\nकृपया सही इमेज भेजें।",
            media_urls=_safe_example_list(example),
        )

    # Fetch image bytes from Twilio
    try:
        data = await _fetch_media(media_url)
    except Exception as e:
        print("[WHATSAPP] Media fetch error:", repr(e))
        fallback = expected_photo_type or "LABELLING"
        prompt, example = type_prompt(fallback), type_example_url(fallback)
        return build_twiml_reply(
            f"❌ Could not download the image. Please resend.\n"
            f"इमेज डाउनलोड नहीं हो सकी, दोबारा भेजें।\n{prompt}",
            media_urls=_safe_example_list(example),
        )

    # Persist original image right away
    try:
        result_hint = (expected_photo_type or "LABELLING").upper()
        key = new_image_key(str(current_job["_id"]), f"s{job_sector_id}_{result_hint.lower()}", "jpg")
        put_result = put_bytes(key, data)
        s3_url = put_result if isinstance(put_result, str) else None

        db.photos.insert_one({
            "jobId": str(current_job["_id"]),
            "sector": job_sector_id,
            "type": result_hint,          # replaced by actual detected type in BG
            "s3Key": key,
            "s3Url": s3_url,
            "phash": None,
            "ocrText": None,
            "fields": {},
            "checks": {},
            "status": "PROCESSING",
            "reason": [],
            "createdAt": datetime.utcnow(),
        })
    except Exception as e:
        print("[STORAGE/DB] initial save error:", repr(e))
        return build_twiml_reply(
            "❌ Could not save the image. Please resend later.\n"
            "इमेज सेव नहीं हो पाई, बाद में दोबारा भेजें।"
        )

    # Background validation + notify
    background.add_task(
        _process_and_notify,
        db,
        from_num,
        str(current_job["_id"]),
        data
    )

    # Immediate ACK
    return build_twiml_reply(
        "📥 Got the photo. Processing… please wait for the next instruction.\n"
        "📥 फोटो मिल गई। प्रोसेस हो रही है — अगला निर्देश जल्दी मिलेगा।"
    )

# ---------------------------
# Debug: direct upload (no WhatsApp)
# ---------------------------

@router.post("/debug/upload")
async def debug_upload(
    workerPhone: str = Form(...),
    siteId: str = Form(...),
    sector: str = Form(...),
    file: UploadFile = File(...),
    db=Depends(get_db),
):
    """
    Convenience route for testing the validation pipeline without WhatsApp.
    Ensures a minimal job exists;
    runs pipeline; saves photo; advances currentIndex for that job on PASS.
    """
    # Find or create a job
    job = db.jobs.find_one({
        "workerPhone": workerPhone,
        "siteId": siteId,
        "sector": sector,
        "status": {"$in": ["PENDING", "IN_PROGRESS"]}
    })

    if not job:
        # These must exist in your codebase as before
        req_types = build_required_types_for_sector(sector)
        job_doc = new_job(
            worker_phone=workerPhone,
            required_types=req_types,
            siteId=siteId,
            sector=sector
        )
        job_doc["status"] = "IN_PROGRESS"

        try:
            ins = db.jobs.insert_one(job_doc)
            job_doc["_id"] = ins.inserted_id
            job = job_doc
        except Exception:
            job = db.jobs.find_one({
                "workerPhone": workerPhone,
                "siteId": siteId,
                "sector": sector,
            })
            if not job:
                return JSONResponse({"error": "Failed to create or find job"}, status_code=500)

    expected = _current_expected_type_for_job(job)

    data = await file.read()
    try:
        img = load_bgr(data)
        if img is None:
            raise ValueError("Could not decode image.")
    except Exception as e:
        return JSONResponse({"error": f"decode_failed: {repr(e)}"}, status_code=400)

    prev_phashes = [
        p.get("phash")
        for p in db.photos.find(
            {
                "jobId": str(job["_id"]),
                "sector": sector,
                "type": (expected or "").upper(),
                "status": {"$in": ["PASS", "FAIL"]},
            },
            {"phash": 1}
        )
        if p.get("phash")
    ]

    try:
        result = run_pipeline(
            img,
            job_ctx={"expectedType": expected},
            existing_phashes=prev_phashes
        )

        fields = result.get("fields") or {}
        updates: Dict[str, Any] = {}
        if fields.get("macId"):
            updates["macId"] = fields["macId"]
        if fields.get("rsn"):
            updates["rsnId"] = fields["rsn"]
        if fields.get("azimuthDeg") is not None:
            updates["azimuthDeg"] = fields["azimuthDeg"]
        if updates:
            db.jobs.update_one({"_id": job["_id"]}, {"$set": updates})

    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": f"pipeline_crashed: {repr(e)}"}, status_code=500)

    result_type = (result.get("type") or expected or "LABELLING").upper()
    try:
        key = new_image_key(str(job["_id"]), f"s{sector}_{result_type.lower()}", "jpg")
        put_result = put_bytes(key, data)
        s3_url = put_result if isinstance(put_result, str) else None

        db.photos.insert_one({
            "jobId": str(job["_id"]),
            "sector": sector,
            "type": result_type,
            "s3Key": key,
            "s3Url": s3_url,
            "phash": result.get("phash"),
            "ocrText": result.get("ocrText"),
            "fields": result.get("fields") or {},
            "checks": result.get("checks") or {},
            "status": result.get("status"),
            "reason": result.get("reason") or [],
            "createdAt": datetime.utcnow(),
        })
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": f"save_failed: {repr(e)}"}, status_code=500)

    if (result.get("status") or "").upper() == "PASS" and expected and result_type == expected:
        db.jobs.update_one(
            {"_id": job["_id"]},
            {"$inc": {"currentIndex": 1}}
        )
        job = db.jobs.find_one({"_id": job["_id"]})
        if is_job_done(job):
            db.jobs.update_one(
                {"_id": job["_id"]},
                {"$set": {"status": "DONE"}}
            )

    return JSONResponse({
        "jobId": str(job["_id"]),
        "sector": sector,
        "type": result_type,
        "status": result.get("status"),
        "reason": result.get("reason") or [],
        "fields": result.get("fields") or {},
    })
