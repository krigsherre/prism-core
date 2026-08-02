"use client"

import React, { useState, useRef, useEffect } from "react"
import { useAppStore } from "@/store/useAppStore"
import { Bot, ArrowUp, Sparkles } from "lucide-react"
import { WorkflowDag } from "./WorkflowDag"
import { ChatMessage } from "./ChatMessage"
import { motion, AnimatePresence } from "framer-motion"

const SUGGESTIONS = [
  "Summarize the latest financial report",
  "Extract all invoice amounts from uploaded docs",
  "What are the key risk factors mentioned?",
  "Run a data quality audit on Q3 data",
]

export const ChatPane = () => {
  const {
    workflowDag,
    currentTaskIndex,
    workflowStatus,
    startWorkflow,
    messages
  } = useAppStore()

  const [input, setInput] = useState("")
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleSend = () => {
    if (!input.trim() || workflowStatus === "RUNNING") return
    startWorkflow([], input)
    setInput("")
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto"
    }
  }

  const handleSuggestion = (s: string) => {
    if (workflowStatus === "RUNNING") return
    startWorkflow([], s)
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
      <header className="h-14 flex items-center justify-between px-6 shrink-0 bg-surface border-b border-border">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-brand/10 border border-brand/20 flex items-center justify-center">
            <Bot size={16} className="text-brand" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-foreground leading-tight">Agentic Brain</h2>
            <p className="text-[11px] text-muted leading-tight">Autonomous Workflow Executor</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${isRunning ? "bg-green-500 animate-pulse" : "bg-gray-300"}`} />
          <span className="text-xs text-muted">{isRunning ? "Running" : "Ready"}</span>
        </div>
      </header>

      {/* Workflow DAG */}
      <AnimatePresence>
        {workflowStatus !== "IDLE" && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-b border-border bg-surface"
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
        <div className="max-w-3xl mx-auto px-4 py-6 flex flex-col gap-5 pb-40">
          {messages.length === 0 ? (
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col items-center justify-center text-center mt-16 space-y-6"
            >
              <div className="w-16 h-16 rounded-2xl bg-brand/10 border border-brand/20 flex items-center justify-center shadow-sm">
                <Bot size={30} className="text-brand" />
              </div>
              <div>
                <h3 className="text-xl font-semibold text-foreground mb-2">How can I help you today?</h3>
                <p className="text-sm text-muted max-w-sm mx-auto">
                  I can analyze documents, extract data, run workflows, and answer questions about your data.
                </p>
              </div>
              {/* Suggestion chips */}
              <div className="grid grid-cols-2 gap-2 w-full max-w-lg mt-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => handleSuggestion(s)}
                    className="text-left text-sm text-foreground bg-surface border border-border rounded-xl px-4 py-3 hover:border-brand/40 hover:bg-brandLight hover:text-brand transition-all duration-150 shadow-card leading-snug"
                  >
                    <Sparkles size={12} className="inline mr-1.5 text-brand opacity-70" />
                    {s}
                  </button>
                ))}
              </div>
            </motion.div>
          ) : (
            <AnimatePresence initial={false}>
              {messages.map((msg) => (
                <ChatMessage key={msg.id} role={msg.role} content={msg.content} />
              ))}
            </AnimatePresence>
          )}

          {/* Typing indicator */}
          <AnimatePresence>
            {isRunning && messages[messages.length - 1]?.role !== "agent" && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="flex gap-3 items-center"
              >
                <div className="w-8 h-8 rounded-full bg-brand/10 border border-brand/20 flex items-center justify-center">
                  <Bot size={15} className="text-brand" />
                </div>
                <div className="bg-white border border-border rounded-2xl rounded-tl-sm px-4 py-3 shadow-card flex items-center gap-1.5">
                  {[0, 1, 2].map((i) => (
                    <motion.div
                      key={i}
                      className="w-1.5 h-1.5 bg-brand rounded-full"
                      animate={{ y: [0, -4, 0] }}
                      transition={{ repeat: Infinity, duration: 1, delay: i * 0.2 }}
                    />
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input Area */}
      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-background via-background/95 to-transparent pt-8 pb-5 px-4">
        <div className="max-w-3xl mx-auto">
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
              placeholder="Message Agentic Brain…"
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
              <ArrowUp size={16} strokeWidth={2.5} />
            </button>
          </div>
          <p className="text-center text-[11px] text-muted mt-2.5">
            Agentic Brain can make mistakes. Verify important information.
          </p>
        </div>
      </div>
    </div>
  )
}
