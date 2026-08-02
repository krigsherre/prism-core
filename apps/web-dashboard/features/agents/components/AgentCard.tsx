"use client"

import React from "react"
import { Bot, Play, ChevronRight } from "lucide-react"

interface AgentCardProps {
  agent: any
  selectedAgentId: string | null
  deployPrompt: string
  setDeployPrompt: (val: string) => void
  setSelectedAgentId: (id: string | null) => void
  handleDeploy: (id: string) => void
}

export const AgentCard = ({
  agent,
  selectedAgentId,
  deployPrompt,
  setDeployPrompt,
  setSelectedAgentId,
  handleDeploy
}: AgentCardProps) => {
  const isSelected = selectedAgentId === agent.id

  return (
    <div
      className={`bg-white border rounded-xl p-5 flex flex-col justify-between transition-all duration-200 shadow-card group
        ${isSelected ? "border-brand/40 shadow-[0_0_0_3px_rgba(79,70,229,0.08)]" : "border-border hover:border-brand/30 hover:shadow-card-hover"}`}
    >
      <div>
        <div className="flex items-center gap-3 mb-3">
          <div className="w-10 h-10 rounded-xl bg-brandLight border border-brand/20 flex items-center justify-center">
            <Bot size={18} className="text-brand" />
          </div>
          <div>
            <h3 className="font-semibold text-[14px] text-foreground">{agent.name}</h3>
            <p className="text-[11px] text-muted">Virtual Employee</p>
          </div>
        </div>
        <p className="text-xs text-muted line-clamp-2 leading-relaxed min-h-[2.5rem]">
          {agent.description || "No description provided."}
        </p>
      </div>

      {isSelected ? (
        <div className="mt-4 pt-4 border-t border-border flex flex-col gap-2">
          <input
            autoFocus
            className="w-full text-sm border border-border rounded-lg px-3 py-2.5 outline-none focus:border-brand focus:ring-2 focus:ring-brand/10 transition-all text-foreground placeholder:text-muted"
            placeholder="Describe the task…"
            value={deployPrompt}
            onChange={(e) => setDeployPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleDeploy(agent.id)
              if (e.key === "Escape") setSelectedAgentId(null)
            }}
          />
          <div className="flex gap-2 justify-end">
            <button
              onClick={() => setSelectedAgentId(null)}
              className="text-xs text-muted hover:text-foreground px-3 py-1.5 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => handleDeploy(agent.id)}
              className="bg-brand text-white text-xs px-4 py-1.5 rounded-lg font-medium flex items-center gap-1.5 hover:bg-brandHover transition-colors"
            >
              <Play size={11} fill="currentColor" />
              Run Agent
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-4 pt-4 border-t border-border flex justify-end">
          <button
            onClick={() => setSelectedAgentId(agent.id)}
            className="text-brand text-sm font-medium hover:text-brandHover flex items-center gap-1 transition-colors"
          >
            Deploy <ChevronRight size={15} />
          </button>
        </div>
      )}
    </div>
  )
}
