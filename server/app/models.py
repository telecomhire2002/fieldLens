# app/models.py
from typing import List, Literal, Optional
from datetime import datetime

# Note: these are simple dict factories for MongoDB documents.
# They match the fields your routes/handlers expect.

JobStatus = Literal["PENDING", "IN_PROGRESS", "DONE"]
PhotoStatus = Literal["PASS", "FAIL"]

def new_job(
    worker_phone: str,
    required_types: List[str],
    siteId: str,
    sector: str,
    circle: str,
    company: str
):
    now = datetime.utcnow()
    return {
        "workerPhone": worker_phone,     # store already-normalized: "whatsapp:+<digits>"
        "requiredTypes": required_types, # e.g. your 14-type list (or per-sector template)
        "currentIndex": 0,
        "status": "PENDING",             # advanced to IN_PROGRESS on first worker message
        "siteId": siteId,                # identifier grouping multiple sectors for same worker
        "sector": sector,                # single sector per job (frontend groups by siteId)
        
        "circle": circle,
        "company": company,

        "createdAt": now,
        "updatedAt": now,
        # Optional fields your pipeline may promote onto the job:
        # "macId": None,
        # "rsnId": None,
        # "azimuthDeg": None,
    }

def new_photo(job_id: str, ptype: str, s3_key: str):
    return {
        "jobId": job_id,
        "type": ptype,                   # may be an initial hint (e.g., expected)
        "s3Key": s3_key,                 # S3 object key
        "phash": None,
        "ocrText": None,                 # keep None; webhook/pipeline will fill a string later
        "fields": {},                    # macId/rsn/azimuth extracted here
        "checks": {                      # blur/dup/skew metrics
            "blurScore": None,
            "isDuplicate": False,
            "skewDeg": None,
        },
        "status": None,                  # set to "PROCESSING" / "PASS" / "FAIL" by webhook/pipeline
        "reason": [],
        "createdAt": datetime.utcnow(),
    }