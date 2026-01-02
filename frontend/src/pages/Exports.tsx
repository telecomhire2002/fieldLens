import { useState, useEffect, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, Download, Archive, Calendar, FileText } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { BackendJob, fetchJobs, downloadJobBundleZip } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";

type TaskStatus = "DONE";

export default function Exports() {
  const navigate = useNavigate();

  const [jobs, setJobs] = useState<BackendJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // NEW: main excel file for bundle export
  const [mainExcelFile, setMainExcelFile] = useState<File | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setErr(null);
      try {
        const data = await fetchJobs();
        setJobs(data);
      } catch (e: any) {
        setErr(e?.message ?? "Failed to load jobs");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const uiTasks = useMemo(() => {
    const toIsoCreated = (j: BackendJob) => {
      if (j.createdAt) return j.createdAt;
      // fallback from Mongo ObjectId
      try {
        const secs = parseInt(j.id.slice(0, 8), 16);
        return new Date(secs * 1000).toISOString();
      } catch {
        return new Date().toISOString();
      }
    };

    const toUpper = (s: string) => (s ? s.toUpperCase() : s);

    // ---------- helpers to decide "final export ready" ----------
    const alphaMap: Record<string, number> = { alpha: 1, beta: 2, gamma: 3 };

    const normalizeSector = (raw: string) => {
      const s = String(raw || "").trim();
      const low = s.toLowerCase();

      if (alphaMap[low]) return `Sec${alphaMap[low]}`;
      if (low.startsWith("sec") && /^\d+$/.test(s.slice(3)))
        return `Sec${parseInt(s.slice(3), 10)}`;
      if (s.startsWith("-") && /^\d+$/.test(s.slice(1)))
        return `Sec${parseInt(s.slice(1), 10)}`;
      if (/^\d+$/.test(s)) return `Sec${parseInt(s, 10)}`;
      return s; // fallback
    };

    const isDone = (j: BackendJob) => {
      const top = String(j.status || "").toUpperCase();
      const block = String(j.sectors?.[0]?.status || "").toUpperCase();
      return top === "DONE" || block === "DONE";
    };

    // group jobs by siteId
    const groups = new Map<string, BackendJob[]>();
    for (const j of jobs) {
      const sid = String(j.siteId || "").trim();
      if (!sid) continue;
      if (!groups.has(sid)) groups.set(sid, []);
      groups.get(sid)!.push(j);
    }

    // build ONLY those "site" entries where Sec1+Sec2+Sec3 exist and are DONE
    const finalExportReadyCards: Array<{
      id: string;
      title: string;
      circle: string;
      company: string;
      siteId: string;
      sector: any[];
      status: TaskStatus;
      createdAt: string;
    }> = [];

    const required = ["Sec1", "Sec2", "Sec3"];

    for (const [siteId, list] of groups.entries()) {
      // map sector -> job (pick latest if duplicates)
      const sectorToJob = new Map<string, BackendJob>();

      for (const j of list) {
        const sec = normalizeSector(j.sector);
        if (!sec) continue;

        const prev = sectorToJob.get(sec);
        if (!prev) {
          sectorToJob.set(sec, j);
          continue;
        }

        const prevT = new Date(toIsoCreated(prev)).getTime();
        const curT = new Date(toIsoCreated(j)).getTime();
        if (curT >= prevT) sectorToJob.set(sec, j);
      }

      // must have all 3 sectors
      const hasAll = required.every((s) => sectorToJob.has(s));
      if (!hasAll) continue;

      // all 3 must be DONE
      const allDone = required.every((s) => isDone(sectorToJob.get(s)!));
      if (!allDone) continue;

      // pick one job as "export id" (use Sec1 if available)
      const pick =
        sectorToJob.get("Sec1") || sectorToJob.get("Sec2") || sectorToJob.get("Sec3")!;
      const exportJobId = pick.id;

      // latest createdAt among 3
      const latestCreatedAt = new Date(
        Math.max(
          ...required.map((s) => new Date(toIsoCreated(sectorToJob.get(s)!)).getTime())
        )
      ).toISOString();

      // Build sector blocks to keep UI unchanged (exportItem.sector.map(e=>e.sector))
      const sectorsForUi = required.map((sec) => {
        const jj = sectorToJob.get(sec)!;
        return {
          sector: sec,
          requiredTypes: jj.sectors?.[0]?.requiredTypes || [],
          currentIndex: jj.sectors?.[0]?.currentIndex ?? 0,
          status: (jj.sectors?.[0]?.status || jj.status || "DONE") as any,
        };
      });

      finalExportReadyCards.push({
        id: exportJobId, // UI shows "JOB ID" - keep field, but it represents the exportable site bundle
        title: `Job • ${pick.workerPhone}`,
        circle: pick.circle,
        company: pick.company,
        siteId: siteId,
        sector: sectorsForUi,
        status: "DONE",
        createdAt: latestCreatedAt,
      });
    }

    // sort newest first
    finalExportReadyCards.sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
    );

    return finalExportReadyCards.map((j) => ({
      ...j,
      status: toUpper(j.status) as TaskStatus,
    }));
  }, [jobs]);

  const filteredTasks = useMemo(() => {
    // uiTasks already contains ONLY "final export ready" sites
    return uiTasks.filter((t) => t.status === "DONE");
  }, [uiTasks]);

  const [downloads] = useState<Record<string, boolean>>({});

  const { toast } = useToast();
  const [downloading, setDownloading] = useState(false);

  const handleExport = async (taskId: string) => {
    if (!mainExcelFile) {
      toast({
        title: "Main Excel required",
        description: "Please select the main Excel file first (top of the page).",
        variant: "destructive",
      });
      return;
    }

    setDownloading(true);
    toast({ title: "Export started", description: `Preparing Bundle ZIP for ${taskId}...` });

    try {
      await downloadJobBundleZip(taskId, mainExcelFile);
      toast({ title: "Export complete", description: "Bundle ZIP downloaded." });
    } catch (e: any) {
      toast({
        title: "Export failed",
        description: e?.message ?? "Unknown error",
        variant: "destructive",
      });
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" onClick={() => navigate("/")} className="gap-2">
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </Button>
        <div>
          <h1 className="text-2xl font-semibold text-foreground">Export Files</h1>
          <p className="text-muted-foreground">Download and manage exported task files</p>
        </div>
      </div>

      {/* NEW: main excel picker (minimal, doesn't change your cards UI) */}
      <Card>
        <CardHeader>
          <CardTitle>Main Excel (Required for Final Bundle Export)</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center gap-3">
          <input
            type="file"
            accept=".xlsx,.xls"
            onChange={(e) => setMainExcelFile(e.target.files?.[0] ?? null)}
          />
          {mainExcelFile ? (
            <Badge className="bg-success text-success-foreground">{mainExcelFile.name}</Badge>
          ) : (
            <Badge variant="secondary">No file selected</Badge>
          )}
        </CardContent>
      </Card>

      {/* Errors / Loading (optional simple states) */}
      {err && (
        <Card>
          <CardContent className="py-4 text-destructive">{err}</CardContent>
        </Card>
      )}
      {loading && (
        <Card>
          <CardContent className="py-4 text-muted-foreground">Loading exports…</CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Available Exports</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {filteredTasks.map((exportItem) => (
              <div
                key={exportItem.id}
                className="border rounded-lg p-4 hover:bg-accent/50 transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div className="space-y-2">
                    <div className="flex items-center gap-3">
                      <h3 className="font-medium text-foreground">{exportItem.title}</h3>
                      <Badge className="bg-success text-success-foreground">Completed</Badge>
                    </div>

                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm text-muted-foreground">
                      <div>
                        <span className="font-medium">JOB ID:</span> {exportItem.id}
                      </div>
                      <div>
                        <span className="font-medium">Circle:</span> {exportItem.circle}
                      </div>
                      <div>
                        <span className="font-medium">Company:</span> {exportItem.company}
                      </div>
                      <div>
                        <span className="font-medium">SiteId:</span> {exportItem.siteId}
                      </div>
                      <div>
                        <span className="font-medium">Sector:</span>{" "}
                        {exportItem.sector.map((e: any) => e.sector)}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Calendar className="w-4 h-4" />
                      <span>
                        Created: {new Date(exportItem.createdAt).toLocaleDateString()}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {exportItem.status === "DONE" && (
                      <Button
                        onClick={() => handleExport(exportItem.id)}
                        className="gap-2"
                        disabled={downloading || downloads[exportItem.id]}
                      >
                        <Download className="w-4 h-4" />
                        {downloading ? "Downloading..." : "Download ZIP"}
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            ))}

            {filteredTasks.length === 0 && !loading && (
              <div className="text-center py-12">
                <Archive className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
                <p className="text-muted-foreground">No exports available yet.</p>
                <p className="text-sm text-muted-foreground mt-1">
                  Completed tasks will appear here for download.
                </p>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
