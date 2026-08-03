"use client"
import React from "react"
import { UserCheck, Clock, FileText, CheckCircle, XCircle } from "lucide-react"
import { useHitl, HitlRequest, CellIssue } from "@/features/hitl/useHitl"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useAppStore } from "@/store/useAppStore"
import { DocumentViewer } from "@/components/DocumentViewer"

function getHitlReview(req: HitlRequest) {
  return req.payload?.hitl_review || req.payload?.payload?.hitl_review || null
}

function defaultEditablePayload(req: HitlRequest): string {
  const review = getHitlReview(req)
  const proposed = review?.proposed_extracted_data
  if (proposed && Object.keys(proposed).length > 0) {
    return JSON.stringify(proposed, null, 2)
  }
  return JSON.stringify(req.payload?.extracted_data || req.payload, null, 2)
}

export default function HITLPage() {
  const { requests, isLoading, resolve, discard, approveGeneric, divertRag, isResolving, isDiscarding, isApprovingGeneric, isDivertingRag } = useHitl()
  const [editedPayloads, setEditedPayloads] = React.useState<Record<string, string>>({})
  const [selectedReqId, setSelectedReqId] = React.useState<string | null>(null)
  const setActiveBBox = useAppStore((state: any) => state.setActiveBBox)
  const setActivePage = useAppStore((state: any) => state.setActivePage)
  const setActiveDocumentUrl = useAppStore((state: any) => state.setActiveDocumentUrl)

  const handleEdit = (id: string, val: string) => {
    setEditedPayloads(prev => ({ ...prev, [id]: val }))
  }

  const handleSelectReq = (req: any) => {
    setSelectedReqId(req.id)
    if (req.s3_uri) {
      setActiveDocumentUrl(req.s3_uri)
    } else {
      setActiveDocumentUrl(null)
    }
    if (req.payload?.source_bbox) {
      setActiveBBox(req.payload.source_bbox)
    } else {
      setActiveBBox(null)
    }
    const page = req.payload?.source_page
    setActivePage(typeof page === "number" && page > 0 ? page : null)
  }

  const closeViewer = () => {
    setSelectedReqId(null)
    setActiveDocumentUrl(null)
    setActiveBBox(null)
    setActivePage(null)
  }

  return (
    <div className="flex flex-col h-full w-full p-8 overflow-auto bg-surface relative">
      <div className="mb-8 shrink-0">
        <h1 className="text-2xl font-bold mb-1 flex items-center gap-2 text-brand">
          <UserCheck /> Human In The Loop
        </h1>
        <p className="text-sm text-gray-500">
          Row- and column-level mapping issues awaiting approve or reject.
        </p>
      </div>

      <div className="grid gap-4 pb-8">
        {isLoading ? (
          Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="bg-white border border-brand/20 rounded-xl p-5 shadow-sm space-y-4">
              <div className="flex justify-between items-start">
                <Skeleton className="h-5 w-20 rounded-md" />
                <Skeleton className="h-4 w-32" />
              </div>
              <Skeleton className="h-8 w-48 rounded-md" />
              <Skeleton className="h-12 w-full rounded-lg" />
              <Skeleton className="h-24 w-full rounded-lg" />
              <div className="flex justify-end gap-3 pt-4">
                <Skeleton className="h-9 w-24 rounded-full" />
                <Skeleton className="h-9 w-40 rounded-full" />
              </div>
            </div>
          ))
        ) : (
          requests.map((req) => {
            const review = getHitlReview(req)
            const currentPayloadStr = editedPayloads[req.id] ?? defaultEditablePayload(req)
            const issues: CellIssue[] = review?.issues || []

            return (
              <div
                key={req.id}
                className={`bg-white border rounded-xl p-5 shadow-sm transition-all ${selectedReqId === req.id ? "border-brand ring-2 ring-brand/20" : "border-brand/20"
                  }`}
              >
                <div className="flex justify-between items-start mb-3">
                  <div className="flex items-center gap-3">
                    <span
                      className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-md font-bold ${req.status === "PENDING"
                          ? "bg-amber-100 text-amber-700"
                          : "bg-gray-100 text-gray-700"
                        }`}
                    >
                      {req.status}
                    </span>
                    {req.payload?.target_table && (
                      <span className="text-xs text-gray-500 font-mono">
                        {req.payload.target_table}
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-gray-400 flex items-center gap-1">
                    <Clock size={14} /> {new Date(req.created_at).toLocaleString()}
                  </span>
                </div>

                <div 
                  className="flex items-center gap-2 text-sm text-gray-600 mb-4 bg-gray-50 px-3 py-1.5 rounded-md w-fit border border-gray-100 cursor-pointer hover:bg-gray-100 transition-colors"
                  onClick={() => handleSelectReq(req)}
                >
                  <FileText size={14} />
                  Doc ID: {req.document_id}
                </div>

                <div className="bg-amber-50 border border-amber-100 p-3 rounded-lg text-sm text-amber-900 mb-4">
                  <strong className="block mb-1">Review summary</strong>
                  <p className="leading-relaxed">{review?.summary || req.error}</p>
                </div>

                {issues.length > 0 ? (
                  <div className="mb-4 border border-gray-100 rounded-lg overflow-hidden">
                    <div className="bg-gray-50 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Cell-level issues ({issues.length})
                    </div>
                    <ul className="divide-y divide-gray-100 max-h-64 overflow-auto">
                      {issues.map((iss, idx) => (
                        <li key={idx} className="px-3 py-3 text-sm">
                          <div className="flex flex-wrap gap-2 items-baseline mb-1">
                            <span className="text-[10px] font-bold uppercase tracking-wider bg-brand/10 text-brand px-1.5 py-0.5 rounded">
                              Row {iss.row_index}
                            </span>
                            <span className="font-mono text-xs text-gray-700">{iss.column}</span>
                          </div>
                          <p className="text-gray-800 mb-1">{iss.question}</p>
                          <div className="text-xs text-gray-500 font-mono space-y-0.5">
                            {iss.current_value != null && (
                              <div>Current: {String(iss.current_value)}</div>
                            )}
                            <div>Issue: {iss.expected_or_issue}</div>
                            {iss.suggested_value != null && (
                              <div className="text-emerald-700">Suggested: {String(iss.suggested_value)}</div>
                            )}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <div className="bg-amber-50 border border-amber-100 p-3 rounded-lg text-sm font-mono text-amber-800 mb-4">
                    <strong>Critic Reason:</strong> {req.error}
                  </div>
                )}

                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1 block">
                  Proposed extracted data (edit then approve)
                </label>
                <textarea
                  className="w-full bg-gray-900 text-gray-100 p-3 rounded-lg text-xs font-mono mb-4 min-h-[150px] focus:outline-none focus:ring-2 focus:ring-brand"
                  value={currentPayloadStr}
                  onChange={(e) => handleEdit(req.id, e.target.value)}
                />

                <div className="mt-4 flex justify-end gap-3 border-t border-gray-100 pt-4">
                  <Button
                    variant="ghost"
                    className="rounded-full flex items-center gap-2"
                    onClick={() => discard({ id: req.id, document_id: req.document_id })}
                    disabled={isDiscarding}
                  >
                    <XCircle size={16} /> Reject
                  </Button>
                  <Button
                    variant="outline"
                    className="rounded-full shadow-sm flex items-center gap-2 border-brand/40 text-brand hover:bg-brand/5"
                    onClick={() => {
                      let unmapped_rows: Record<string, unknown>[] = []
                      try {
                        const parsed = JSON.parse(currentPayloadStr || "[]")
                        if (Array.isArray(parsed)) {
                          unmapped_rows = parsed
                        } else if (parsed && typeof parsed === "object") {
                          // extracted_data is an object — wrap it as a single row
                          unmapped_rows = [parsed]
                        }
                      } catch {
                        unmapped_rows = []
                      }
                      approveGeneric({
                        document_id: req.document_id,
                        node_id: req.id,
                        target_table: req.payload?.target_table || "generic_table",
                        unmapped_rows,
                      })
                    }}
                    disabled={isApprovingGeneric}
                  >
                    Approve as Generic Table
                  </Button>
                  <Button
                    variant="outline"
                    className="rounded-full shadow-sm flex items-center gap-2 border-purple-500/40 text-purple-700 hover:bg-purple-50"
                    onClick={() => divertRag({
                      document_id: req.document_id,
                      node_id: req.id,
                      markdown_content: currentPayloadStr
                    })}
                    disabled={isDivertingRag}
                  >
                    Divert to RAG
                  </Button>
                  <Button
                    className="rounded-full shadow-sm flex items-center gap-2"
                    onClick={() => resolve({ id: req.id, document_id: req.document_id, correctValue: currentPayloadStr })}
                    disabled={isResolving}
                  >
                    <CheckCircle size={16} /> Approve & Inject
                  </Button>
                </div>
              </div>
            )
          })
        )}
        {!isLoading && requests.length === 0 && (
          <div className="p-8 text-center text-gray-400 border border-dashed border-gray-200 rounded-xl bg-gray-50">
            No pending HITL requests
          </div>
        )}
      </div>

      {selectedReqId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-8 backdrop-blur-sm">
          <div className="relative w-full max-w-5xl h-full bg-card rounded-xl shadow-2xl flex flex-col overflow-hidden">
            <div className="flex-1 overflow-hidden">
              <DocumentViewer closeViewer={closeViewer} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
