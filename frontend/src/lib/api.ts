// src/lib/api.ts
import axios from "axios";


/** ---------- AXIOS CLIENT ---------- */
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api",
  withCredentials: true,
});

/** ---------- TYPES (keep in sync with backend) ---------- */
export type SectorBlock = {
  sector: string;
  requiredTypes: string[];
  currentIndex: number;
  status: "PENDING" | "IN_PROGRESS" | "DONE" | "FAILED";
};

export type BackendJob = {
  id: string;
  workerPhone: string;
  siteId: string;
  sector: string;
  sectors: SectorBlock[];
  circle: string
  company: string
  status: "PENDING" | "IN_PROGRESS" | "DONE" | "FAILED";
  createdAt?: string | null;
  macId?: string | null;
  rsnId?: string | null;
  azimuthDeg?: number | string | null;
};

export type PhotoItem = {
  id: string;
  jobId: string;
  type: string;
  sector?: number | null;
  s3Key?: string | null;
  s3Url?: string | null; // presigned by backend
  status?: string;
  reason?: string[];
  fields?: Record<string, any>;
  checks?: Record<string, any>;
  phash?: string | null;
  ocrText?: string | null;
};

export type JobDetail = {
  job: BackendJob;
  photos: PhotoItem[];
};

/** ---------- HELPERS ---------- */
function downloadBlob(data: BlobPart, filename: string, mime?: string) {
  const blob = new Blob([data], { type: mime || "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function exportFinalExcel(jobId: string, sectorId: string, file: File) {
  const formData = new FormData();
  formData.append("sectorId", sectorId);
  formData.append("mainExcel", file);

  const res = await api.post(`/jobs/${jobId}/export.xlsx`, formData, {
    responseType: "blob",
  });

  let filename =
    (res.headers["x-filename"] as string) ||
    (res.headers["content-disposition"] as string) ||
    "export.xlsx";

  // If we got Content-Disposition, extract filename from it
  if (filename.includes("filename=")) {
    const m = filename.match(/filename\*?=(?:UTF-8'')?["']?([^"';\n]+)["']?/i);
    if (m?.[1]) filename = decodeURIComponent(m[1]);
  }

  // Ensure extension
  if (!filename.toLowerCase().endsWith(".xlsx")) {
    filename = `${filename}.xlsx`;
  }

  const blob = new Blob([res.data], {
    type:
      res.headers["content-type"] ||
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });

  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

/** ---------- API CALLS ---------- */
export async function fetchJobs(): Promise<BackendJob[]> {
  const { data } = await api.get("/jobs");
  return data;
}

export async function fetchJobDetail(jobId: string, opts?: { sector?: number }) {
  const { data } = await api.get(`/jobs/${encodeURIComponent(jobId)}`, {
    params: opts?.sector != null ? { sector: opts.sector } : undefined,
  });
  return data as JobDetail;
}

export async function createJob(input: {
  workerPhone: string;
  siteId: string;
  sector: string;
}): Promise<BackendJob> {
  const { data } = await api.post("/jobs", input);
  return data;
}

/** ----- SECTOR-WISE ZIP EXPORT (new) ----- */
export async function downloadJobZip(
  jobId: string,
  opts?: { sector?: number }
): Promise<void> {
  const { data, headers } = await api.get(
    `/jobs/${encodeURIComponent(jobId)}/export.zip`,
    {
      params: opts?.sector != null ? { sector: opts.sector } : undefined,
      responseType: "blob",
    }
  );

  // Try to honor backend filename
  const cd = (headers["content-disposition"] || "") as string;
  const match = cd.match(/filename="?([^"]+)"?/i);
  const filename =
    match?.[1] ||
    (opts?.sector != null
      ? `job_${jobId}_sec${opts.sector}.zip`
      : `job_${jobId}.zip`);

  downloadBlob(data, filename, "application/zip");
}

/** ----- OPTIONAL: sector workbook (one sheet per sector) ----- */
export async function downloadSectorWorkbook(
  opts?: { date_from?: string; date_to?: string }
): Promise<void> {
  const { data, headers } = await api.get("/exports/sector.xlsx", {
    params: opts,
    responseType: "blob",
  });
  const cd = (headers["content-disposition"] || "") as string;
  const match = cd.match(/filename="?([^"]+)"?/i);
  const filename = match?.[1] || "export_sector.xlsx";
  downloadBlob(
    data,
    filename,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
  );
}

/** ----- DELETE JOB (new) ----- */
export async function deleteJob(jobId: string): Promise<void> {
  await api.delete(`/jobs/${encodeURIComponent(jobId)}`);
}



export async function downloadJobXlsxHOTO(jobId: string, file: File) {
  const formData = new FormData();
  formData.append("mainExcel", file);

  const res = await api.post(`/jobs/${jobId}/export.csv`, formData, {
    responseType: "blob",
  });

  // Axios header keys are lowercase
  let filename =
    (res.headers["x-filename"] as string) ||
    (res.headers["content-disposition"] as string) ||
    "export.xlsx";

  // If we got Content-Disposition, extract filename from it
  if (filename.includes("filename=")) {
    const m = filename.match(/filename\*?=(?:UTF-8'')?["']?([^"';\n]+)["']?/i);
    if (m?.[1]) filename = decodeURIComponent(m[1]);
  }

  // Ensure extension
  if (!filename.toLowerCase().endsWith(".xlsx")) {
    filename = `${filename}.xlsx`;
  }

  const blob = new Blob([res.data], {
    type:
      res.headers["content-type"] ||
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });

  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}


export async function getSectorTemplate(sector: number) {
  const { data } = await api.get(`/jobs/templates/sector/${sector}`);
  return data as {
    requiredTypes: string[];
    labels: Record<string, string>;
    sector: number;
  };
}
