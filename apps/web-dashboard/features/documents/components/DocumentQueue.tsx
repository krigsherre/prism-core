"use client"
import React, { useEffect, useState } from "react"
import { api, API_BASE_URL } from "@/services/apiClient"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { CheckCircle2, Loader2, FileText, RefreshCw } from "lucide-react"
import { useAppStore } from "@/store/useAppStore"

type JobStatus =
  | "PENDING"
  | "IN_PROGRESS"
  | "EXTRACTING"
  | "COMPLETED"
  | "FAILED"
  | "DUPLICATE"
  | "ALIGNING"
  | "UNKNOWN"

interface DocumentJob {
  document_id: string
  filename: string
  current_stage: string
  status: JobStatus
  updated_at: string
  s3_uri?: string
  error_message?: string
}

const STATUS_CONFIG: Record<string, { label: string; cls: string; dotCls: string }> = {
  PENDING: { label: "Pending", cls: "bg-amber-50 text-amber-700 border-amber-200", dotCls: "bg-amber-400" },
  IN_PROGRESS: { label: "Processing", cls: "bg-brandLight text-brand border-brand/20", dotCls: "bg-brand animate-pulse" },
  EXTRACTING: { label: "Extracting", cls: "bg-purple-50 text-purple-700 border-purple-200", dotCls: "bg-purple-500 animate-pulse" },
  ALIGNING: { label: "Aligning", cls: "bg-indigo-50 text-indigo-700 border-indigo-200", dotCls: "bg-indigo-500 animate-pulse" },
  COMPLETED: { label: "Completed", cls: "bg-green-50 text-green-700 border-green-200", dotCls: "bg-green-500" },
  FAILED: { label: "Failed", cls: "bg-red-50 text-red-700 border-red-200", dotCls: "bg-red-500" },
  DUPLICATE: { label: "Duplicate", cls: "bg-gray-100 text-gray-500 border-gray-200", dotCls: "bg-gray-400" },
}

function mergeJob(prev: DocumentJob | undefined, incoming: DocumentJob): DocumentJob {
  const nextFilename =
    incoming.filename && incoming.filename !== "unknown"
      ? incoming.filename
      : prev?.filename && prev.filename !== "unknown"
        ? prev.filename
        : incoming.filename || prev?.filename || "unknown"

  return {
    ...prev,
    ...incoming,
    filename: nextFilename,
    s3_uri: incoming.s3_uri || prev?.s3_uri,
    updated_at: incoming.updated_at || prev?.updated_at || new Date().toISOString(),
  }
}

export const DocumentQueue = () => {
  const [jobs, setJobs] = useState<Record<string, DocumentJob>>({})
  const [isLoading, setIsLoading] = useState(true)
  const tenantId = "default-tenant"
  const activeDocumentUrl = useAppStore((state) => state.activeDocumentUrl)
  const setActiveDocumentUrl = useAppStore((state) => state.setActiveDocumentUrl)
  const setActiveBBox = useAppStore((state) => state.setActiveBBox)
  const setActivePage = useAppStore((state) => state.setActivePage)

  const openInViewer = (s3Uri: string) => {
    setActiveBBox(null)
    setActivePage(null)
    setActiveDocumentUrl(s3Uri)
  }

  useEffect(() => {
    api.get<DocumentJob[]>(`/api/documents/jobs?tenant_id=${tenantId}`)
      .then((data) => {
        if (Array.isArray(data)) {
          const initialJobs = data.reduce(
            (acc, job) => {
              acc[job.document_id] = job
              return acc
            },
            {} as Record<string, DocumentJob>
          )
          setJobs(initialJobs)
        }
      })
      .catch((err) => console.error("Failed to fetch initial jobs", err))
      .finally(() => setIsLoading(false))

    const sse = new EventSource(
      `${API_BASE_URL}/api/documents/status/stream?tenant_id=${tenantId}`
    )
    sse.onmessage = (e) => {
      try {
        const data: DocumentJob = JSON.parse(e.data)
        if (!data?.document_id) return
        setJobs((prev) => ({
          ...prev,
          [data.document_id]: mergeJob(prev[data.document_id], data),
        }))
      } catch (err) {
        console.error("Failed to parse SSE data", err)
      }
    }
    sse.onerror = (e) => console.error("SSE error", e)
    return () => sse.close()
  }, [])

  const retryJob = async (documentId: string) => {
    setJobs((prev) => ({
      ...prev,
      [documentId]: { ...prev[documentId], status: "PENDING", current_stage: "retrying" },
    }))
    try {
      await api.post(`/api/documents/retry/${documentId}?tenant_id=${tenantId}`)
    } catch (err) {
      console.error("Failed to retry job", err)
      setJobs((prev) => ({
        ...prev,
        [documentId]: { ...prev[documentId], status: "FAILED", current_stage: "Retry failed" },
      }))
    }
  }

  const jobList = Object.values(jobs).sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  )
  const activeCount = jobList.filter(
    (j) => j.status !== "COMPLETED" && j.status !== "FAILED" && j.status !== "DUPLICATE"
  ).length

  if (isLoading) {
    return (
      <div className="w-full bg-white border border-border rounded-xl shadow-card overflow-hidden">
        <div className="bg-gray-50 px-6 py-4 border-b border-border flex justify-between items-center">
          <Skeleton className="h-5 w-36" />
          <Skeleton className="h-5 w-20 rounded-full" />
        </div>
        <div className="divide-y divide-border">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="p-4 flex items-center justify-between gap-4">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-3 w-1/4" />
              <Skeleton className="h-6 w-24 rounded-lg" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (jobList.length === 0) {
    return (
      <div className="w-full py-12 text-center bg-white border border-dashed border-border rounded-xl">
        <CheckCircle2 size={28} className="mx-auto mb-3 text-green-400" />
        <p className="text-sm font-medium text-foreground">Queue is clear</p>
        <p className="text-xs text-muted mt-1">No documents currently being processed</p>
      </div>
    )
  }

  return (
    <div className="w-full bg-white border border-border rounded-xl shadow-card overflow-hidden">
      <div className="bg-gray-50 px-6 py-3.5 border-b border-border flex justify-between items-center">
        <div className="flex items-center gap-2">
          <FileText size={15} className="text-muted" />
          <h3 className="font-semibold text-sm text-foreground">Ingestion Pipeline</h3>
        </div>
        <div className="flex items-center gap-2">
          {activeCount > 0 && (
            <span className="flex items-center gap-1.5 text-xs font-semibold text-brand bg-brandLight border border-brand/20 px-2.5 py-1 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-brand animate-pulse" />
              {activeCount} active
            </span>
          )}
          <span className="text-xs text-muted">{jobList.length} total</span>
        </div>
      </div>

      <div className="divide-y divide-border">
        {jobList.map((job) => {
          const s =
            STATUS_CONFIG[job.status] ?? {
              label: job.status,
              cls: "bg-gray-100 text-muted border-gray-200",
              dotCls: "bg-gray-400",
            }
          const isActive = Boolean(job.s3_uri && job.s3_uri === activeDocumentUrl)
          const displayName =
            job.filename && job.filename !== "unknown"
              ? job.filename
              : job.s3_uri?.split("/").pop() || job.document_id
          return (
            <div
              key={job.document_id}
              className={`px-6 py-4 flex items-center justify-between transition-colors group ${
                isActive ? "bg-brandLight/40" : "hover:bg-gray-50/60"
              }`}
            >
              <div className="flex flex-col gap-0.5 min-w-0 w-2/5">
                {job.s3_uri ? (
                  <button
                    type="button"
                    onClick={() => openInViewer(job.s3_uri!)}
                    className="text-left font-medium text-sm text-foreground truncate hover:text-brand transition-colors"
                    title="Open in document viewer"
                  >
                    {displayName}
                  </button>
                ) : (
                  <span className="font-medium text-sm text-foreground truncate">{displayName}</span>
                )}
                {job.s3_uri ? (
                  <button
                    type="button"
                    onClick={() => openInViewer(job.s3_uri!)}
                    className="text-[11px] text-muted font-mono truncate hover:text-brand hover:underline text-left"
                    title="Open in document viewer"
                  >
                    {job.s3_uri.split("/").pop()}
                  </button>
                ) : (
                  <span className="text-[11px] text-muted font-mono truncate">{job.document_id}</span>
                )}
              </div>

              <div className="flex-1 px-6 text-xs text-muted flex items-center gap-2 min-w-0">
                {job.status !== "COMPLETED" &&
                  job.status !== "FAILED" &&
                  job.status !== "DUPLICATE" && (
                    <Loader2 size={12} className="shrink-0 text-brand animate-spin" />
                  )}
                <span className="truncate">
                  {job.status === "COMPLETED"
                    ? "Pipeline completed successfully"
                    : job.current_stage === "bifurcation"
                      ? "Routing to Vector and Graph stores"
                      : job.current_stage === "api-gateway"
                        ? "Uploading to secure storage"
                        : job.current_stage === "triage-worker"
                          ? "Analyzing and chunking document"
                          : job.current_stage === "gpu-extractor"
                            ? "Extracting text and tables (GPU)"
                            : job.current_stage === "schema-aligner" ||
                                job.current_stage === "schema_aligner"
                              ? "Aligning data to SQL schema"
                              : job.current_stage || "—"}
                </span>
              </div>

              <div className="flex items-center gap-3 shrink-0">
                <span
                  className={`flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-lg border ${s.cls}`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${s.dotCls}`} />
                  {s.label}
                </span>
                {job.status === "FAILED" && (
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => retryJob(job.document_id)}
                    className="text-muted hover:text-brand h-7 w-7 rounded-lg"
                    title="Retry"
                  >
                    <RefreshCw size={14} />
                  </Button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
