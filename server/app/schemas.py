from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any

PhotoType = str

class SectorProgress(BaseModel):
    sector: str
    requiredTypes: List[PhotoType]
    currentIndex: int = 0
    status: Literal["PENDING", "IN_PROGRESS", "DONE"] = "PENDING"

class CreateJob(BaseModel):
    workerPhone: str
    siteId: str
    sector: str
    circle: str
    company: str

class JobOut(BaseModel):
    id: str
    workerPhone: str
    siteId: str
    sector: str
    # NOTE: plural here – matches _job_to_out
    sectors: List[SectorProgress]

    # top-level progress for WhatsApp single-sector flow
    requiredTypes: List[PhotoType] = Field(default_factory=list)
    currentIndex: int = 0

    status: Literal["PENDING", "IN_PROGRESS", "DONE"]

    circle: str
    company: str

    createdAt: Optional[str] = None
    macId: Optional[str] = None
    rsnId: Optional[str] = None
    azimuthDeg: Optional[float] = None

class PhotoOut(BaseModel):
    id: str
    jobId: str
    sector: str
    type: PhotoType
    s3Url: str
    fields: Dict[str, Any]
    checks: Dict[str, Any]
    status: str
    reason: List[str]
