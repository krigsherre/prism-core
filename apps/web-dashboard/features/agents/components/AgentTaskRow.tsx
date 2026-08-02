"use client"

import React from "react"
import { CheckCircle2, Clock, AlertCircle, Loader2 } from "lucide-react"

interface AgentTaskRowProps {
  task: any
  onClick: (task: any) => void
}

const STATUS_MAP: Record<string, { label: string; cls: string; dot?: string }> = {
  COMPLETED: {
    label: "Completed",
    cls: "bg-green-50 text-green-700 border border-green-200",
    dot: "bg-green-500"
  },
  FAILED: {
    label: "Failed",
    cls: "bg-red-50 text-red-700 border border-red-200",
    dot: "bg-red-500"
  },
  RUNNING: {
    label: "Running",
    cls: "bg-brandLight text-brand border border-brand/20",
    dot: "bg-brand animate-pulse"
  },
  QUEUED: {
    label: "Queued",
    cls: "bg-amber-50 text-amber-700 border border-amber-200",
    dot: "bg-amber-400"
  }
}

export const AgentTaskRow = ({ task, onClick }: AgentTaskRowProps) => {
  const status = STATUS_MAP[task.status] ?? { label: task.status, cls: "bg-gray-100 text-muted border border-gray-200" }

  return (
    <div
      onClick={() => onClick(task)}
      className="flex items-center justify-between px-5 py-4 bg-white border border-border rounded-xl shadow-card hover:border-brand/30 hover:shadow-card-hover transition-all duration-200 cursor-pointer group"
    >
      {/* Name + ID */}
      <div className="flex items-center gap-3 w-1/4 min-w-0">
        <div className="w-8 h-8 rounded-lg bg-brandLight border border-brand/20 flex items-center justify-center shrink-0">
          {task.status === "RUNNING" ? (
            <Loader2 size={14} className="text-brand animate-spin" />
          ) : task.status === "COMPLETED" ? (
            <CheckCircle2 size={14} className="text-green-600" />
          ) : (
            <AlertCircle size={14} className="text-red-500" />
          )}
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground truncate group-hover:text-brand transition-colors">
            {task.name}
          </p>
          <p className="text-[11px] text-muted font-mono truncate">
            {task.id?.substring(0, 10)}…
          </p>
        </div>
      </div>

      {/* Result preview */}
      <div className="flex-1 px-6 min-w-0">
        <p className="text-xs text-muted bg-gray-50 border border-gray-100 rounded-lg px-3 py-2 truncate font-mono">
          {task.status === "COMPLETED" || task.status === "FAILED"
            ? task.result || "No output"
            : "Processing…"}
        </p>
      </div>

      {/* Time + Status */}
      <div className="flex items-center gap-4 shrink-0">
        <div className="text-xs text-muted flex items-center gap-1.5">
          <Clock size={12} />
          {new Date(task.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </div>
        <span className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-lg ${status.cls}`}>
          {status.dot && <span className={`w-1.5 h-1.5 rounded-full ${status.dot}`} />}
          {status.label}
        </span>
      </div>
    </div>
  )
}
