# app/routes/whatsapp.py
import os
import traceback
from typing import Tuple, List, Optional, Dict, Any
from datetime import datetime
import cv2
import httpx
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
    is_validated_type,   # This can stay
    twilio_client,       # Twilio REST client if configured
    TWILIO_WHATSAPP_FROM # whatsapp:from number
)

router = APIRouter()

# ---------------------------
# SIMPLIFIED HELPERS (single-sector model)
# ---------------------------

def _current_expected_type_for_job(job: Dict[str, Any]) -> Optional[str]:
    """Return the next required type for this job."""
    if not job:
        return None
    # Read from top-level fields
    idx = int(job.get("currentIndex", 0) or 0)
    req = job.get("requiredTypes", []) or []
    if 0 <= idx < len(req):
        return req[idx]
    return None # Job is complete

def is_job_done(job: Dict[str, Any]) -> bool:
    """Check if a single job is complete."""
    if not job:
        return True
    if job.get("status") == "DONE":
        return True
    # Check if index is at the end
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
# Background processor (Simplified)
# ---------------------------

def _process_and_notify(
    db,
    worker_number: str,
    job_id: str, # We only need job_id
    image_bytes: bytes
):
    """
    Runs validation, updates DB/job, and proactively
    notifies the worker with next prompt or retake.
    """
    try:
        # 1) Reload fresh job
        job = db.jobs.find_one({"_id": job_id})
        if not job:
            print("[BG] Job missing; abort.")
            return

        # 2) Expected type for this job
        expected = _current_expected_type_for_job(job)
        job_sector = job.get("sector") # Get the job's sector

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

        # Promote important fields to job-level (this logic is fine)
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
            job = db.jobs.find_one({"_id": job["_id"]}) # Reload

            # If the job finished, mark it DONE
            if is_job_done(job):
                db.jobs.update_one(
                    {"_id": job["_id"]},
                    {"$set": {"status": "DONE"}}
                )
                job = db.jobs.find_one({"_id": job["_id"]})

        # 8) Compose outbound message
        text = ""
        media = None
        if (result.get("status") or "").upper() == "PASS":
            next_expected = _current_expected_type_for_job(job)
            if next_expected is None:
                text = (
                    "✅ Received and verified. Sector complete.\n"
                    "✅ सेक्टर पूरा हो गया। धन्यवाद!\n\n"
                    "Send 'hy' to start your next sector."
                )
            else:
                prompt, example = type_prompt(next_expected), type_example_url(next_expected)
                text = f"✅ {result_type} verified.\nNext: {prompt}\nअब अगली फोटो भेजें।"
                media = example
        else:
            # Retake path
            fallback_type = expected or result_type
            prompt, example = type_prompt(fallback_type), type_example_url(fallback_type)
            reasons = "; ".join(result.get("reason") or []) or "needs retake"
            text = (
                f"❌ {result_type} failed: {reasons}.\n"
                f"Please retake and resend.\n{prompt}\n"
                f"कृपया दोबारा साफ फोटो भेजें।"
            )
            media = example

        # 9) Send proactive WhatsApp message (this logic is fine)
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
# Webhook (Revised Selection Logic)
# ---------------------------

@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, background: BackgroundTasks, db=Depends(get_db)):
    """
    WhatsApp webhook (Twilio). Handles text prompts and image uploads.
    - Selects job based on unique sector ID.
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

    # --- REVISED JOB & SECTOR SELECTION LOGIC ---

    # 1. Find ALL active jobs (PENDING or IN_PROGRESS) for this worker
    all_active_jobs_for_worker = list(db.jobs.find({
        "workerPhone": from_num,
        "status": {"$in": ["PENDING", "IN_PROGRESS"]}
    }).limit(10))
    
    # 2. Try to find the *currently selected* job (status: IN_PROGRESS)
    current_job: Optional[Dict[str, Any]] = None
    for j in all_active_jobs_for_worker:
        if j.get("status") == "IN_PROGRESS":
            # If it's IN_PROGRESS but actually done, ignore it
            if not is_job_done(j):
                current_job = j
                break

    # If no 'IN_PROGRESS' job was found, we need to select one.
    if not current_job:
        # Filter out any jobs that might be IN_PROGRESS but are factually done
        pending_jobs = [j for j in all_active_jobs_for_worker if j.get("status") == "PENDING" and not is_job_done(j)]
        num_jobs_found = len(pending_jobs)

        if num_jobs_found == 0:
            # Case A: No PENDING jobs.
            # (We already know there are no *active* IN_PROGRESS jobs)
            return build_twiml_reply(
                "No active job assigned yet. Please contact your supervisor.\n"
                "कोई सक्रिय जॉब असाइन नहीं है। कृपया सुपरवाइज़र से संपर्क करें।"
            )
        
        elif num_jobs_found == 1:
            # Case B: Only one PENDING job, auto-select it.
            current_job = pending_jobs[0]
            db.jobs.update_one({"_id": current_job["_id"]}, {"$set": {"status": "IN_PROGRESS"}})
            current_job["status"] = "IN_PROGRESS" # Update in-memory doc
        
        else:
            # Case C: Multiple PENDING jobs. User needs to select a SECTOR ID.
            
            # Build list of available sector IDs
            available_sectors = {} # Map "SECTOR_ID_UPPER" -> job
            for j in pending_jobs:
                sector_id = j.get("sector")
                if sector_id:
                    available_sectors[sector_id.upper()] = j
            
            if not available_sectors:
                return build_twiml_reply("Error: No sectors found in pending jobs.")

            # Check if user's text matches one of the sector IDs
            matched_job = available_sectors.get(user_message_body.upper())

            if matched_job:
                # User provided a valid sector ID
                current_job = matched_job
                # Set the *chosen* JOB to IN_PROGRESS
                db.jobs.update_one(
                    {"_id": current_job["_id"]}, 
                    {"$set": {"status": "IN_PROGRESS"}}
                )
                current_job["status"] = "IN_PROGRESS"
                
            else:
                # User has multiple jobs but hasn't selected one, or just said "Hi".
                # Prompt them to select.
                prompt_lines = [f"➡️ {sector_id}" for sector_id in sorted(available_sectors.keys())]
                reply_text = (
                    "You have multiple active sectors. Reply with the Sector ID you are working on:\n\n"
                    "आपके पास एक से ज़्यादा सक्रिय सेक्टर हैं। आप जिस सेक्टर पर काम कर रहे हैं उसकी ID भेजें:\n\n"
                ) + "\n".join(prompt_lines)
                
                return build_twiml_reply(reply_text)
    
    # --- END: REVISED JOB & SECTOR SELECTION LOGIC ---
    
    # At this point, 'current_job' MUST be set.
    
    # Check again if it's done (e.g., an IN_PROGRESS job that just finished)
    if is_job_done(current_job):
        db.jobs.update_one({"_id": current_job["_id"]}, {"$set": {"status": "DONE"}})
        # Recurse to re-trigger selection for the *next* job
        return await whatsapp_webhook(request, background, db)

    expected_photo_type = _current_expected_type_for_job(current_job)
    job_sector_id = current_job.get("sector") # Get the sector ID for this job
    
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

    # Persist original image right away (S3/local) for reliability
    try:
        result_hint = (expected_photo_type or "LABELLING").upper()
        # Use the job's sector ID in the S3 key
        key = new_image_key(str(current_job["_id"]), f"s{job_sector_id}_{result_hint.lower()}", "jpg")
        put_result = put_bytes(key, data)
        s3_url = put_result if isinstance(put_result, str) else None

        db.photos.insert_one({
            "jobId": str(current_job["_id"]),
            "sector": job_sector_id, # Store the job's sector ID on the photo
            "type": result_hint,          # will be replaced by actual detected type in BG
            "s3Key": key,
            "s3Url": s3_url,              # optional if your storage returns URL
            "phash": None,
            "ocrText": None,
            "fields": {},
            "checks": {},
            "status": "PROCESSING",
            "reason": [],
            "createdAt": datetime.utcnow(), # Added createdAt
        })
    except Exception as e:
        print("[STORAGE/DB] initial save error:", repr(e))
        return build_twiml_reply(
            "❌ Could not save the image. Please resend later.\n"
            "इमेज सेव नहीं हो पाई, बाद में दोबारा भेजें।"
        )

    # Kick background validation → sector-aware update → proactive notify
    background.add_task(
        _process_and_notify,
        db,
        from_num,
        current_job["_id"], # Just pass the job_id
        data
    )

    # Immediate ACK (stay under 15s)
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
        # Create a minimal job for testing
        req_types = build_required_types_for_sector(sector)
        job_doc = new_job(
            worker_phone=workerPhone,
            required_types=req_types,
            siteId=siteId,
            sector=sector
        )
        job_doc["status"] = "IN_PROGRESS" # Start it right away for debug
        
        try:
            ins = db.jobs.insert_one(job_doc)
            job_doc["_id"] = ins.inserted_id
            job = job_doc
        except Exception:
             # It might already exist (race condition or old DONE job)
             job = db.jobs.find_one({
                 "workerPhone": workerPhone,
                 "siteId": siteId,
                 "sector": sector,
             })
             if not job:
                 return JSONResponse({"error": "Failed to create or find job"}, status_code=500)

    # Get expected type
    expected = _current_expected_type_for_job(job)

    data = await file.read()
    try:
        img = load_bgr(data)
        if img is None:
            raise ValueError("Could not decode image.")
    except Exception as e:
        return JSONResponse({"error": f"decode_failed: {repr(e)}"}, status_code=400)

    # Prior phashes (same job + expected type)
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

    # Run pipeline
    try:
        result = run_pipeline(
            img,
            job_ctx={"expectedType": expected},
            existing_phashes=prev_phashes
        )

        # Optional: promote fields to job
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

    # Save to storage
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

    # Advance this job on exact PASS
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