"use client"

import React, { useState, useRef, useEffect } from "react"
import { useAppStore } from "@/store/useAppStore"
import { Bot, ArrowUp, Sparkles, FileText, Trash2, ShieldCheck, RefreshCw } from "lucide-react"
import { WorkflowDag } from "./WorkflowDag"
import { ChatMessage } from "./ChatMessage"
import { motion, AnimatePresence } from "framer-motion"
import { api } from "@/services/apiClient"

const SUGGESTIONS = [
  "Audit Apple Inc. (AAPL) Net Income vs Operating Cash Flow in SEC 10-K",
  "Extract Total Net Sales, Gross Margin & R&D Expense from SEC 10-K",
  "Verify Related Party Transactions & Note disclosures in SEC filing",
  "Calculate Interest Coverage Ratio & Debt Maturity schedule for Apple",
]

const PERSONAS = [
  { id: "forensic_auditor", name: "Forensic Accounting Auditor", role: "Auditor" },
  { id: "compliance_officer", name: "Regulatory Compliance Officer", role: "Compliance" },
  { id: "credit_analyst", name: "Credit Risk Analyst", role: "Credit" },
  { id: "research_assistant", name: "Financial Research Analyst", role: "Research" },
]

export const ChatPane = () => {
  const {
    workflowDag,
    currentTaskIndex,
    workflowStatus,
    startWorkflow,
    messages,
    clearMessages,
    activeDocumentId,
    setActiveDocumentId,
    activeDocumentUrl
  } = useAppStore()

  const [input, setInput] = useState("")
  const [selectedPersona, setSelectedPersona] = useState("forensic_auditor")
  const [documentList, setDocumentList] = useState<{ document_id: string; current_stage?: string }[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    async function loadDocs() {
      try {
        const jobs = await api.get<{ document_id: string; current_stage?: string }[]>(
          "/api/documents/jobs?tenant_id=default-tenant"
        )
        if (Array.isArray(jobs)) {
          setDocumentList(jobs)
        }
      } catch (err) {
        console.error("Failed to load document list", err)
      }
    }
    loadDocs()
  }, [])

  const handleSend = () => {
    if (!input.trim() || workflowStatus === "RUNNING") return
    startWorkflow([], input, selectedPersona, activeDocumentId || "")
    setInput("")
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto"
    }
  }

  const handleSuggestion = (s: string) => {
    if (workflowStatus === "RUNNING") return
    startWorkflow([], s, selectedPersona, activeDocumentId || "")
  }

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value)
    e.target.style.height = "auto"
    e.target.style.height = Math.min(e.target.scrollHeight, 200) + "px"
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, workflowStatus])

  const isRunning = workflowStatus === "RUNNING"

  return (
    <div className="h-full flex flex-col relative bg-background">
      {/* Header */}
      <header className="h-16 flex items-center justify-between px-6 shrink-0 bg-surface border-b border-border shadow-xs z-10">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-brand/10 border border-brand/20 flex items-center justify-center text-brand">
            <Bot size={18} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-foreground leading-tight">Agentic Brain</h2>
              <span className="text-[10px] font-medium bg-brandLight text-brand border border-brand/20 px-2 py-0.5 rounded-full flex items-center gap-1">
                <ShieldCheck size={10} /> Tri-Modal RAG
              </span>
            </div>
            <p className="text-[11px] text-muted leading-tight">Tri-Modal Autonomous Reasoning System</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* AI Employee Role Selector */}
          <select
            value={selectedPersona}
            onChange={(e) => setSelectedPersona(e.target.value)}
            className="text-xs bg-white border border-brand/20 text-brand font-medium rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-brand/20 cursor-pointer shadow-xs"
          >
            {PERSONAS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>

          {/* Reset / New Chat */}
          {messages.length > 0 && (
            <button
              onClick={clearMessages}
              title="Clear chat history"
              className="p-1.5 text-muted hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
            >
              <Trash2 size={15} />
            </button>
          )}

          <div className="flex items-center gap-1.5 pl-2 border-l border-border">
            <span className={`w-2 h-2 rounded-full ${isRunning ? "bg-green-500 animate-pulse" : "bg-gray-300"}`} />
            <span className="text-xs text-muted font-medium">{isRunning ? "Auditing" : "Ready"}</span>
          </div>
        </div>
      </header>

      {/* Workflow DAG Trace Bar */}
      <AnimatePresence>
        {workflowStatus !== "IDLE" && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-b border-border bg-surface shadow-xs"
          >
            <WorkflowDag
              workflowDag={workflowDag}
              currentTaskIndex={currentTaskIndex}
              workflowStatus={workflowStatus}
            />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6 flex flex-col gap-6 pb-48">
          {messages.length === 0 ? (
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col items-center justify-center text-center mt-12 space-y-6"
            >
              <div className="w-16 h-16 rounded-2xl bg-brand/10 border border-brand/20 flex items-center justify-center shadow-xs text-brand">
                <Bot size={32} />
              </div>
              <div>
                <h3 className="text-xl font-semibold text-foreground mb-2">Agentic Brain Workspace</h3>
                <p className="text-sm text-muted max-w-md mx-auto leading-relaxed">
                  Query structured PostgreSQL views, Qdrant vector embeddings, and Neo4j corporate graphs with full audit provenance.
                </p>
              </div>
              {/* Suggestion chips */}
              <div className="grid grid-cols-2 gap-2.5 w-full max-w-xl mt-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => handleSuggestion(s)}
                    className="text-left text-xs font-medium text-foreground bg-surface border border-border rounded-xl px-4 py-3 hover:border-brand/40 hover:bg-brandLight hover:text-brand transition-all duration-150 shadow-card leading-snug flex items-start gap-2"
                  >
                    <Sparkles size={13} className="text-brand shrink-0 mt-0.5" />
                    <span>{s}</span>
                  </button>
                ))}
              </div>
            </motion.div>
          ) : (
            <AnimatePresence initial={false}>
              {messages.map((msg) => (
                <ChatMessage key={msg.id} message={msg} />
              ))}
            </AnimatePresence>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input Area with Integrated Inline Document Selector */}
      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-background via-background/95 to-transparent pt-6 pb-4 px-4">
        <div className="max-w-3xl mx-auto">
          {/* Document Scope Toolbar */}
          <div className="flex items-center justify-between px-3 py-1.5 mb-2 bg-surface/90 backdrop-blur-sm border border-border rounded-xl shadow-xs">
            <div className="flex items-center gap-2">
              <FileText size={13} className="text-brand" />
              <span className="text-[11px] font-medium text-muted">Scope:</span>
              <select
                value={activeDocumentId || ""}
                onChange={(e) => setActiveDocumentId(e.target.value || null)}
                className="text-xs font-medium bg-transparent text-foreground focus:outline-none cursor-pointer max-w-[240px] truncate"
              >
                <option value="">All Uploaded Documents</option>
                {documentList.map((doc) => (
                  <option key={doc.document_id} value={doc.document_id}>
                    Document {doc.document_id.slice(0, 8)}... ({doc.current_stage || "Ready"})
                  </option>
                ))}
              </select>
            </div>
            <span className="text-[10px] text-muted font-medium bg-gray-100 px-2 py-0.5 rounded-md">
              {activeDocumentId ? "Single Doc Filter" : "Global Knowledge Base"}
            </span>
          </div>

          <div className="relative bg-surface border border-border rounded-2xl shadow-card focus-within:border-brand/50 focus-within:shadow-[0_0_0_3px_rgba(79,70,229,0.08)] transition-all duration-200">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={handleInput}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              placeholder={`Ask ${PERSONAS.find(p => p.id === selectedPersona)?.name || "Agentic Brain"}…`}
              className="w-full bg-transparent pl-5 pr-14 py-4 text-sm text-foreground placeholder:text-muted focus:outline-none resize-none leading-relaxed"
              rows={1}
              style={{ minHeight: "52px", maxHeight: "200px" }}
              disabled={isRunning}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || isRunning}
              className="absolute right-3 bottom-3 w-8 h-8 rounded-xl bg-brand flex items-center justify-center text-white disabled:opacity-40 disabled:bg-gray-200 disabled:text-gray-400 hover:bg-brandHover transition-all active:scale-95"
            >
              {isRunning ? <RefreshCw size={15} className="animate-spin" /> : <ArrowUp size={16} strokeWidth={2.5} />}
            </button>
          </div>
          <div className="flex items-center justify-between px-2 mt-2 text-[11px] text-muted">
            <span>Press <kbd className="px-1 py-0.5 bg-gray-100 border border-gray-200 rounded font-mono text-[10px]">Enter</kbd> to send, <kbd className="px-1 py-0.5 bg-gray-100 border border-gray-200 rounded font-mono text-[10px]">Shift+Enter</kbd> for line break</span>
            <span>Tri-Modal RAG (SQL + Vector + Graph)</span>
          </div>
        </div>
      </div>
    </div>
  )
}
