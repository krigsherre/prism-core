"use client"

import React, { useState } from "react"
import { X, Save, Bot } from "lucide-react"

interface AgentCreatorProps {
  onClose: () => void
  onCreate: (data: {
    name: string
    description: string
    system_prompt: string
  }) => void
}

export const AgentCreator = ({ onClose, onCreate }: AgentCreatorProps) => {
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [systemPrompt, setSystemPrompt] = useState("")

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name || !systemPrompt) return
    onCreate({ name, description, system_prompt: systemPrompt })
    onClose()
  }

  const fieldClass =
    "w-full border border-border rounded-xl px-4 py-2.5 text-sm text-foreground placeholder:text-muted outline-none focus:border-brand focus:ring-2 focus:ring-brand/10 transition-all bg-background"

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex justify-end">
      <div className="w-[480px] bg-surface h-full shadow-modal flex flex-col animate-in slide-in-from-right duration-300 border-l border-border">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-brandLight border border-brand/20 flex items-center justify-center">
              <Bot size={18} className="text-brand" />
            </div>
            <div>
              <h2 className="text-base font-bold text-foreground">Create Agent</h2>
              <p className="text-xs text-muted">Define a new virtual employee</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-100 text-muted hover:text-foreground transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6 space-y-5">
          <div>
            <label className="block text-xs font-semibold text-foreground mb-1.5 uppercase tracking-wide">
              Agent Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              required
              className={fieldClass}
              placeholder="e.g. Financial Auditor"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-foreground mb-1.5 uppercase tracking-wide">
              Description
              <span className="ml-1 text-muted normal-case font-normal tracking-normal">(optional)</span>
            </label>
            <textarea
              className={`${fieldClass} h-20 resize-none`}
              placeholder="What does this agent do?"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-foreground mb-1.5 uppercase tracking-wide">
              System Prompt <span className="text-red-500">*</span>
            </label>
            <p className="text-xs text-muted mb-2 leading-relaxed">
              Define strict rules, persona, and constraints. The orchestrator routes tools based on this.
            </p>
            <textarea
              required
              className={`${fieldClass} h-56 font-mono text-[13px] resize-none`}
              placeholder="You are an expert financial auditor. You must…"
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
            />
          </div>
        </form>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-border bg-background flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-muted hover:text-foreground hover:bg-gray-100 rounded-xl transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!name || !systemPrompt}
            className="px-5 py-2 bg-brand text-white text-sm font-semibold rounded-xl hover:bg-brandHover transition-colors flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
          >
            <Save size={15} />
            Create Agent
          </button>
        </div>
      </div>
    </div>
  )
}
