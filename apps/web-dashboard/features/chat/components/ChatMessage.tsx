"use client"

import React, { useState } from "react"
import { Bot, User, Brain, ChevronDown, ChevronRight, CheckCircle2, Loader2, MapPin, FileText } from "lucide-react"
import { motion, AnimatePresence } from "framer-motion"
import ReactMarkdown from "react-markdown"
import { useAppStore, Message, Reference } from "@/store/useAppStore"
import { api } from "@/services/apiClient"

interface ChatMessageProps {
  message: Message
}

async function resolveDocumentUrl(href: string): Promise<string> {
  const cleanUrl = href.split("#")[0]

  if (cleanUrl.startsWith("s3://") || cleanUrl.includes("/api/documents/content")) {
    return cleanUrl
  }

  if (
    cleanUrl &&
    !cleanUrl.startsWith("http://") &&
    !cleanUrl.startsWith("https://") &&
    !cleanUrl.startsWith("/")
  ) {
    try {
      const meta = await api.get<{ s3_uri?: string }>(
        `/api/documents/${encodeURIComponent(cleanUrl)}?tenant_id=default-tenant`
      )
      if (meta?.s3_uri) return meta.s3_uri
    } catch (err) {
      console.error("Failed to resolve document for viewer", err)
    }
  }

  return cleanUrl
}

const PERSONA_NAMES: Record<string, string> = {
  forensic_auditor: "Senior Forensic Accounting Auditor",
  compliance_officer: "Regulatory Compliance Officer",
  credit_analyst: "Credit Risk Analyst",
  research_assistant: "Financial Research Analyst"
}

export const ChatMessage = ({ message }: ChatMessageProps) => {
  const isUser = message.role === "user"
  const [showThinking, setShowThinking] = useState(true)

  const setActiveDocumentUrl = useAppStore((state) => state.setActiveDocumentUrl)
  const setActiveBBox = useAppStore((state) => state.setActiveBBox)
  const setActivePage = useAppStore((state) => state.setActivePage)

  const personaTitle = message.personaRole ? (PERSONA_NAMES[message.personaRole] || message.personaRole) : "Agentic Brain"

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 380, damping: 28 }}
      className={`flex gap-3 w-full ${isUser ? "flex-row-reverse" : "flex-row"}`}
    >
      {/* Avatar */}
      <div
        className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 mt-0.5 shadow-sm ${
          isUser
            ? "bg-gray-100 border border-gray-200"
            : "bg-brand/10 border border-brand/20 text-brand"
        }`}
      >
        {isUser ? (
          <User size={16} className="text-gray-600" />
        ) : (
          <Bot size={18} className="text-brand" />
        )}
      </div>

      {/* Message Bubble Container */}
      <div className={`max-w-[85%] space-y-2 ${isUser ? "text-right" : "text-left"}`}>
        {/* Agent Role Badge */}
        {!isUser && (
          <div className="flex items-center gap-2 px-1">
            <span className="text-xs font-semibold text-foreground">{personaTitle}</span>
            {message.isStreaming && (
              <span className="inline-flex items-center gap-1 text-[11px] text-brand bg-brandLight border border-brand/20 px-2 py-0.5 rounded-full font-medium">
                <Loader2 size={10} className="animate-spin" /> Live Reasoning
              </span>
            )}
          </div>
        )}

        <div
          className={`${
            isUser
              ? "bg-brand text-white rounded-2xl rounded-tr-sm px-4 py-3 text-[14px] leading-relaxed shadow-sm inline-block"
              : "bg-surface border border-border rounded-2xl rounded-tl-sm p-4 shadow-card text-foreground"
          }`}
        >
          {isUser ? (
            <p className="text-[14px] leading-relaxed whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="space-y-3">
              {/* Chain of Thought / Agent Execution Accordion */}
              {(message.thinking || (message.statusTrace && message.statusTrace.length > 0)) && (
                <div className="border border-brand/20 bg-brandLight/30 rounded-xl overflow-hidden text-xs">
                  <button
                    onClick={() => setShowThinking(!showThinking)}
                    className="w-full flex items-center justify-between px-3 py-2 bg-brand/5 hover:bg-brand/10 transition-colors text-brand font-medium"
                  >
                    <div className="flex items-center gap-2">
                      <Brain size={14} className="text-brand" />
                      <span>Agent Reasoning & Workflow Trace</span>
                      {message.isStreaming ? (
                        <Loader2 size={12} className="animate-spin text-brand" />
                      ) : (
                        <CheckCircle2 size={12} className="text-green-600" />
                      )}
                    </div>
                    {showThinking ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </button>

                  <AnimatePresence>
                    {showThinking && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="p-3 space-y-2 border-t border-brand/10 bg-white/80 font-mono text-[11px] text-muted leading-relaxed"
                      >
                        {message.thinking && (
                          <div className="text-foreground/90 bg-gray-50 border border-gray-100 rounded-lg p-2 font-sans">
                            <span className="font-semibold text-brand">Intent Analysis: </span>
                            {message.thinking}
                          </div>
                        )}

                        {message.statusTrace && message.statusTrace.length > 0 && (
                          <div className="space-y-1">
                            <span className="font-semibold text-gray-500 uppercase tracking-wider text-[10px]">
                              Execution DAG Steps:
                            </span>
                            {message.statusTrace.map((step, idx) => (
                              <div key={idx} className="flex items-center gap-1.5 text-gray-700">
                                <span className="text-brand">⚡</span> {step}
                              </div>
                            ))}
                          </div>
                        )}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              )}

              {/* Main Synthesized Output */}
              {message.content ? (
                <div className="prose-chat text-[14px] leading-relaxed">
                  <ReactMarkdown
                    components={{
                      a: ({ href, children, ...props }) => (
                        <a
                          href={href}
                          {...props}
                          className="text-brand font-medium underline underline-offset-2 hover:text-brandHover cursor-pointer"
                          onClick={async (e) => {
                            if (!href) return
                            e.preventDefault()
                            const urlObj = new URL(href, window.location.origin)
                            const bboxMatch = urlObj.hash.match(
                              /bbox=([\d.]+),([\d.]+),([\d.]+),([\d.]+)/
                            )
                            const pageMatch = urlObj.hash.match(/page=(\d+)/)

                            const resolved = await resolveDocumentUrl(href)
                            setActiveDocumentUrl(resolved)

                            if (pageMatch) {
                              setActivePage(parseInt(pageMatch[1], 10))
                            } else {
                              setActivePage(null)
                            }

                            if (bboxMatch) {
                              setActiveBBox({
                                x_min: parseFloat(bboxMatch[1]),
                                y_min: parseFloat(bboxMatch[2]),
                                x_max: parseFloat(bboxMatch[3]),
                                y_max: parseFloat(bboxMatch[4]),
                              })
                            } else {
                              setActiveBBox(null)
                            }
                          }}
                        >
                          {children}
                        </a>
                      ),
                      table: ({ children }) => (
                        <div className="overflow-x-auto my-3 border border-border rounded-xl shadow-sm">
                          <table className="min-w-full divide-y divide-border text-xs">
                            {children}
                          </table>
                        </div>
                      ),
                      thead: ({ children }) => (
                        <thead className="bg-gray-50 text-foreground font-semibold">
                          {children}
                        </thead>
                      ),
                      th: ({ children }) => (
                        <th className="px-3 py-2 text-left font-semibold text-gray-700 border-b border-border">
                          {children}
                        </th>
                      ),
                      td: ({ children }) => (
                        <td className="px-3 py-2 border-b border-border/50 text-gray-800">
                          {children}
                        </td>
                      ),
                    }}
                  >
                    {message.content}
                  </ReactMarkdown>
                </div>
              ) : message.isStreaming ? (
                <div className="flex items-center gap-2 text-xs text-muted italic py-1">
                  <Loader2 size={14} className="animate-spin text-brand" />
                  Synthesizing audit response from SQL, Vector, and Graph RAG...
                </div>
              ) : null}

              {/* Source Provenance Badges */}
              {message.references && message.references.length > 0 && (
                <div className="pt-3 border-t border-border/60 mt-3">
                  <div className="text-[11px] font-semibold text-muted uppercase tracking-wider mb-2 flex items-center gap-1">
                    <FileText size={12} className="text-brand" /> Source Provenance ({message.references.length})
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {message.references.map((ref: Reference, i: number) => (
                      <button
                        key={i}
                        onClick={async () => {
                          if (ref.doc_id) {
                            const resolved = await resolveDocumentUrl(ref.doc_id)
                            setActiveDocumentUrl(resolved)
                          }
                          if (ref.source_page) {
                            setActivePage(ref.source_page)
                          }
                          if (ref.source_bbox) {
                            if (Array.isArray(ref.source_bbox) && ref.source_bbox.length === 4) {
                              setActiveBBox({
                                x_min: ref.source_bbox[0],
                                y_min: ref.source_bbox[1],
                                x_max: ref.source_bbox[2],
                                y_max: ref.source_bbox[3],
                              })
                            } else if (typeof ref.source_bbox === "object") {
                              setActiveBBox(ref.source_bbox)
                            }
                          }
                        }}
                        className="inline-flex items-center gap-1 text-[11px] bg-surface hover:bg-brandLight border border-border hover:border-brand/40 text-foreground hover:text-brand px-2.5 py-1 rounded-lg transition-all duration-150 shadow-sm"
                      >
                        <MapPin size={10} className="text-brand" />
                        Page {ref.source_page || 1}
                        {ref.doc_id && <span className="opacity-50 text-[10px]">({ref.doc_id.slice(0, 8)})</span>}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </motion.div>
  )
}
