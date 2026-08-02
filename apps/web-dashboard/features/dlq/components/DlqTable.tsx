"use client"

import React from "react"
import {
  AlertCircle,
  Clock,
  FileText,
  AlertTriangle,
  Loader2,
  CheckCircle2,
  Layers
} from "lucide-react"
import { useDlq } from "../useDlq"

export const DlqTable = () => {
  const { dlqItems, isLoading, handleResolve } = useDlq()
  const [resolveValues, setResolveValues] = React.useState<Record<string, string>>({})

  const needsReview = dlqItems.filter((i) => i.status !== "RESOLVED").length

  return (
    <div className="flex flex-col h-full w-full overflow-auto bg-background">
      {/* Header */}
      <div className="bg-surface border-b border-border px-8 py-5 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-rose-50 border border-rose-200 flex items-center justify-center">
            <Layers size={18} className="text-rose-600" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-foreground flex items-center gap-2">
              Dead Letter Queue
              {needsReview > 0 && (
                <span className="text-[11px] font-bold bg-rose-100 text-rose-700 border border-rose-200 px-2 py-0.5 rounded-full">
                  {needsReview} needs review
                </span>
              )}
            </h1>
            <p className="text-xs text-muted">
              Tasks that permanently failed ingestion or extraction after max retries
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 p-8">
        {isLoading ? (
          <div className="flex items-center justify-center p-16">
            <Loader2 className="animate-spin text-brand" size={28} />
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {dlqItems.map((item) => (
              <div
                key={item.id}
                className="bg-white border border-border rounded-xl overflow-hidden shadow-card"
              >
                {/* Card header */}
                <div className="flex items-center justify-between px-5 py-4 border-b border-border bg-gray-50/50">
                  <div className="flex items-center gap-2.5">
                    <AlertCircle className="text-rose-500 shrink-0" size={17} />
                    <span className="font-semibold text-sm text-foreground">
                      Extraction Failure
                    </span>
                  </div>
                  {item.status === "RESOLVED" ? (
                    <span className="flex items-center gap-1.5 text-xs font-semibold text-green-700 bg-green-50 border border-green-200 px-2.5 py-1 rounded-lg">
                      <CheckCircle2 size={13} />
                      Resolved
                    </span>
                  ) : (
                    <span className="flex items-center gap-1.5 text-xs font-semibold text-amber-700 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-lg">
                      <Clock size={13} />
                      Needs Review
                    </span>
                  )}
                </div>

                {/* Card body */}
                <div className="p-5 space-y-3">
                  {/* Doc metadata */}
                  <div className="flex items-center gap-2 text-xs text-muted bg-gray-50 border border-gray-100 px-3 py-2 rounded-lg w-fit">
                    <FileText size={13} />
                    <span>Doc <span className="font-mono font-medium text-foreground">{item.docId}</span></span>
                    <span className="text-gray-300">·</span>
                    <span>Field <span className="font-mono font-medium text-foreground">{item.field}</span></span>
                  </div>

                  {/* Error */}
                  <div className="bg-rose-50 border border-rose-100 rounded-xl px-4 py-3">
                    <p className="text-xs font-semibold text-rose-600 mb-1">Error</p>
                    <p className="text-xs font-mono text-rose-800 leading-relaxed">{item.error}</p>
                  </div>

                  {/* Extracted */}
                  <div className="flex items-start gap-2 text-sm text-muted">
                    <span className="text-xs font-semibold text-foreground shrink-0">Extracted value:</span>
                    <span className="font-mono text-xs text-foreground">{item.extracted}</span>
                  </div>

                  {/* Resolve form */}
                  {item.status !== "RESOLVED" && (
                    <div className="pt-2 border-t border-border flex flex-col gap-2">
                      <label className="text-xs font-semibold text-foreground uppercase tracking-wide">
                        Enter Correct Value
                      </label>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={resolveValues[item.id] || ""}
                          onChange={(e) =>
                            setResolveValues((prev) => ({
                              ...prev,
                              [item.id]: e.target.value
                            }))
                          }
                          placeholder="Correct value…"
                          className="flex-1 border border-border rounded-xl px-3 py-2.5 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/10 transition-all placeholder:text-muted"
                        />
                        <button
                          onClick={() =>
                            handleResolve(item.id, resolveValues[item.id] || "")
                          }
                          disabled={!resolveValues[item.id]}
                          className="px-4 py-2.5 text-sm font-semibold text-white bg-rose-500 hover:bg-rose-600 rounded-xl transition-colors disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
                        >
                          Resolve & Patch
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}

            {dlqItems.length === 0 && (
              <div className="py-16 text-center border border-dashed border-border rounded-xl bg-white">
                <CheckCircle2 size={32} className="mx-auto mb-3 text-green-400" />
                <p className="text-sm font-semibold text-foreground">All clear!</p>
                <p className="text-xs text-muted mt-1">No items in the Dead Letter Queue 🎉</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
