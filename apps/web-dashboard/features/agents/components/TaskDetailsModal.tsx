"use client"

import React from "react"
import { X, Loader2, CheckCircle2, AlertCircle } from "lucide-react"
import ReactMarkdown from "react-markdown"

interface TaskDetailsModalProps {
  task: any
  onClose: () => void
}

const STATUS_CONFIG: Record<string, { label: string; cls: string }> = {
  COMPLETED: { label: "Completed", cls: "bg-green-50 text-green-700 border border-green-200" },
  FAILED: { label: "Failed", cls: "bg-red-50 text-red-700 border border-red-200" },
  RUNNING: { label: "Running", cls: "bg-brandLight text-brand border border-brand/20" },
  QUEUED: { label: "Queued", cls: "bg-amber-50 text-amber-700 border border-amber-200" },
}

export const TaskDetailsModal = ({ task, onClose }: TaskDetailsModalProps) => {
  if (!task) return null

  const status = STATUS_CONFIG[task.status] ?? { label: task.status, cls: "bg-gray-100 text-muted" }

  return (
    <div
      className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-white rounded-2xl shadow-modal w-full max-w-2xl max-h-[85vh] flex flex-col animate-in fade-in zoom-in-95 duration-200 border border-border">
        {/* Header */}
        <div className="flex items-start justify-between p-6 border-b border-border">
          <div>
            <div className="flex items-center gap-2.5 mb-1">
              <h2 className="text-base font-bold text-foreground">{task.name}</h2>
              <span className={`text-[11px] font-semibold px-2.5 py-0.5 rounded-lg ${status.cls}`}>
                {status.label}
              </span>
            </div>
            <p className="text-[11px] text-muted font-mono">Task ID: {task.id}</p>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-100 text-muted hover:text-foreground transition-colors mt-0.5"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6">
          <p className="text-[10px] font-semibold text-muted uppercase tracking-wider mb-3">
            Result Output
          </p>
          <div className="bg-background border border-border rounded-xl p-5">
            {task.result && task.result !== "-" ? (
              <div className="prose-chat">
                <ReactMarkdown>{task.result}</ReactMarkdown>
              </div>
            ) : (
              <div className="text-muted text-sm flex items-center gap-2 italic">
                {task.status === "RUNNING" ? (
                  <>
                    <Loader2 size={15} className="animate-spin text-brand" />
                    Agent is currently working on this task…
                  </>
                ) : (
                  "No output generated yet."
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
