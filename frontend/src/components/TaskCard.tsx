// src/components/TaskCard.tsx

import React, { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Download } from "lucide-react";
import { deleteJob, downloadJobXlsxHOTO } from "@/lib/api";

type TaskStatus = "PENDING" | "IN_PROGRESS" | "DONE" | "FAILED";

export type UITask = {
  id: string;
  title: string;
  phoneNumber: string;
  circle: string;
  company: string;
  status: TaskStatus;
  createdAt: string;
  sector: string;      // <-- MUST BE SENT FROM BACKEND
  siteId?: string;
};

export function TaskCard({ task, onPreview, onDeleted }: any) {
  const [deleting, setDeleting] = useState(false);

  const statusColors = {
    PENDING: "bg-yellow-100 text-yellow-800 border-yellow-300",
    IN_PROGRESS: "bg-blue-100 text-blue-800 border-blue-300",
    DONE: "bg-green-100 text-green-800 border-green-300",
    FAILED: "bg-red-100 text-red-800 border-red-300",
  };
  // console.log("Rendering TaskCard for task:", task);
  const prettyStatus = (s: TaskStatus) =>
    s === "PENDING" ? "Pending" :
    s === "IN_PROGRESS" ? "In Progress" :
    s === "DONE" ? "Completed" : "Failed";

  const canExport = task.status === "DONE";

  const handleDelete = async () => {
    const sure = window.confirm(`Delete job "${task.title}" ?`);
    if (!sure) return;

    try {
      setDeleting(true);
      await deleteJob(task.id);
      onDeleted?.(task.id);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Card className="flex flex-col border shadow-sm hover:shadow-lg transition rounded-xl bg-[#0F172A] text-white">

      {/* ---------- HEADER ---------- */}
      <CardHeader className="pb-3 border-b border-gray-700">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg font-semibold truncate max-w-[70%]">
            {task.title}
          </CardTitle>

          <Badge className={`${statusColors[task.status]} border`}>
            {prettyStatus(task.status)}
          </Badge>
        </div>

        {/* Sector ALWAYS visible */}
        <div className="mt-2 flex items-center gap-2 text-sm">
          <span className="font-medium">Sector:</span>
          <Badge className="bg-purple-200 text-purple-700 border border-purple-300">
            S {task.sector}
          </Badge>
        </div>
      </CardHeader>

      {/* ---------- BODY ---------- */}
      <CardContent className="mt-3 flex flex-col gap-4 text-sm">

        {/* ---------- FIRST ROW ---------- */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-y-2">
          <div><b>Circle:</b> {task.circle}</div>
          <div><b>Company:</b> {task.company}</div>
        </div>

        {/* ---------- SECOND ROW ---------- */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-y-2">
          <div className="break-all"><b>Phone:</b> {task.phoneNumber}</div>
          <div><b>Created:</b> {new Date(task.createdAt).toLocaleString()}</div>
        </div>

        {/* ---------- JOB / SITE FIXED WRAPPING ---------- */}
        <div className="flex flex-col gap-1">
          <div className="break-all">
            <b>Job ID:</b> {task.id}
          </div>

          {task.siteId && (
            <div className="break-all">
              <b>Site ID:</b> {task.siteId}
            </div>
          )}
        </div>

        {/* ---------- BUTTONS ---------- */}
        <div className="flex flex-wrap gap-3 mt-4">
          <Button size="sm" onClick={() => onPreview(task.id)}>
            Preview
          </Button>

          {canExport && (
            <>
              <Button
                size="sm"
                className="bg-indigo-600 hover:bg-indigo-700 text-white"
                onClick={() =>
                  document.getElementById(`excel-${task.id}`)?.click()
                }
              >
                <Download className="w-4 h-4 mr-2" />
                Export HOTO XLSX
              </Button>

              <input
                id={`excel-${task.id}`}
                type="file"
                accept=".xlsx"
                className="hidden"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;

                  try {
                    await downloadJobXlsxHOTO(task.id, file);
                  } catch (err) {
                    alert("Export failed");
                  } finally {
                    e.target.value = "";
                  }
                }}
              />
            </>
          )}

          <Button
            size="sm"
            variant="destructive"
            disabled={deleting}
            onClick={handleDelete}
          >
            {deleting ? "Deleting…" : "Delete"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
