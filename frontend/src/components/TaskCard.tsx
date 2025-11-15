// src/components/TaskCard.tsx
import React, { useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { downloadJobZip, deleteJob } from "@/lib/api";

type TaskStatus = "PENDING" | "IN_PROGRESS" | "DONE" | "FAILED";

export type UITask = {
  id: string;
  title: string;
  phoneNumber: string;
  status: TaskStatus;
  circle:string;
  company:string;
  createdAt: string;
  siteId?: string;
  sectors?: Array<{ sector: string; status?: TaskStatus } | number>;
};

export function TaskCard({
  task,
  onPreview,
  onDeleted,
}: {
  task: UITask;
  onPreview: (taskId: string) => void;
  onDeleted?: (taskId: string) => void;
}) {
  const [exporting, setExporting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [selectedSector, setSelectedSector] = useState<string>("");

  const statusColors: Record<TaskStatus, string> = {
    PENDING: "bg-yellow-100 text-yellow-800 border-yellow-300",
    IN_PROGRESS: "bg-blue-100 text-blue-800 border-blue-300",
    DONE: "bg-green-100 text-green-800 border-green-300",
    FAILED: "bg-red-100 text-red-800 border-red-300",
  };

  const prettyStatus = (s: TaskStatus) =>
    s === "PENDING" ? "Pending" :
    s === "IN_PROGRESS" ? "In Progress" :
    s === "DONE" ? "Completed" : "Failed";

  const sortedSectors = useMemo(() => {
    const sectors = Array.isArray(task.sectors)
      ? task.sectors.map((s: any) =>
          typeof s === "object" && s !== null
            ? { sector: (s.sector), status: (s.status || "PENDING") as TaskStatus }
            : { sector: (s), status: "PENDING" as TaskStatus }
        )
      : [];
    return sectors.sort((a, b) => a.sector - b.sector);
  }, [task.sectors]);

  const handleExport = async () => {
    try {
      setExporting(true);
      const sector = selectedSector === "" ? undefined : Number(selectedSector);
      await downloadJobZip(task.id, { sector });
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : "Export failed.");
    } finally {
      setExporting(false);
    }
  };

  const handleDelete = async () => {
    const sure = window.confirm(
      `Delete job "${task.title || task.id}"?\nThis will remove the job and all its photos from the database.`
    );
    if (!sure) return;
    try {
      setDeleting(true);
      await deleteJob(task.id);
      if (onDeleted) onDeleted(task.id);
      else window.location.reload();
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : "Delete failed.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-start gap-3">
          <CardTitle className="text-base font-semibold min-w-0 truncate">
            {task.title}
          </CardTitle>
          <Badge className={`${statusColors[task.status]} ml-auto font-medium border`}>
            {prettyStatus(task.status)}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="flex-1 flex flex-col gap-3 text-sm text-muted-foreground">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <div className="break-all">
            <span className="font-medium text-foreground">Circle:</span> {task.circle}
          </div>
          <div className="break-all">
            <span className="font-medium text-foreground">Company:</span> {task.company}
          </div>
          <div className="break-all">
            <span className="font-medium text-foreground">Job Id:</span> {task.id}
          </div>
          <div className="break-all">
            <span className="font-medium text-foreground">Phone:</span> {task.phoneNumber}
          </div>
          <div>
            <span className="font-medium text-foreground">Created:</span>{" "}
            {task.createdAt ? new Date(task.createdAt).toLocaleString() : "—"}
          </div>
          {task.siteId && (
            <div className="break-all">
              <span className="font-medium text-foreground">Site ID:</span> {task.siteId}
            </div>
          )}
        </div>

        {sortedSectors.length > 0 && (
          <div className="mt-3">
            <div className="mb-1 text-foreground font-medium">Sectors</div>
            <div className="flex flex-wrap gap-2">
              {sortedSectors.map((s) => (
                <Badge key={s.sector} className={`${statusColors[s.status]} border`}>
                  S{s.sector} • {prettyStatus(s.status)}
                </Badge>
              ))}
            </div>
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => onPreview(task.id)}>
            Preview
          </Button>

          {task.status === "DONE" && (
            <>
              {sortedSectors.length > 0 && (
                <select
                  className="border rounded-md px-2 py-1 text-background"
                  value={selectedSector}
                  onChange={(e) => setSelectedSector(e.target.value)}
                  disabled={exporting || deleting}
                >
                  <option value="">All sectors</option>
                  {sortedSectors.map((s) => (
                    <option key={s.sector} value={s.sector}>
                      Sector {s.sector}
                    </option>
                  ))}
                </select>
              )}

              <Button
                size="sm"
                variant="outline"
                onClick={handleExport}
                disabled={exporting || deleting}
              >
                {exporting
                  ? "Exporting..."
                  : selectedSector === ""
                    ? "Export ZIP"
                    : `Export ZIP (S${selectedSector})`}
              </Button>
            </>
          )}

          <Button
            size="sm"
            variant="destructive"
            onClick={handleDelete}
            disabled={deleting || exporting}
          >
            {deleting ? "Deleting..." : "Delete"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
