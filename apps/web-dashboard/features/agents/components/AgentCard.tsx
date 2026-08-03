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
        <div className="mt-4 pt-4 border-t border-border flex flex-col gap-2.5">
          {/* Predefined Rich Task Templates */}
          <div className="flex flex-wrap gap-1.5">
            {[
              {
                title: "Forensic Revenue Audit",
                template: "Perform a comprehensive Forensic Accounting Audit:\n1. Extract Net Income from P&L and compare against Operating Cash Flow.\n2. Cross-check Related Party Transactions (Note disclosures) and flag ungrounded transactions.\n3. Verify if Assets = Liabilities + Equity identity holds mathematically."
              },
              {
                title: "Financial Statement Extraction",
                template: "Perform a Financial Statement Analysis:\n1. Extract Revenue from Operations, PBT, and PAT.\n2. Calculate YoY revenue growth and EBITDA margins.\n3. Verify Capital Work-in-Progress (CWIP) and Trade Payables disclosures."
              },
              {
                title: "Credit & Debt Evaluation",
                template: "Perform a Credit Risk & Liquidity Evaluation:\n1. Calculate Interest Coverage Ratio (EBIT / Interest Expense).\n2. Extract short-term borrowings vs Cash & Cash Equivalents.\n3. Outline the 12-month debt maturity repayment schedule."
              }
            ].map((item) => (
              <button
                key={item.title}
                type="button"
                onClick={() => setDeployPrompt(item.template)}
                className="text-[11px] bg-brandLight/80 text-brand hover:bg-brand hover:text-white border border-brand/20 px-2.5 py-1 rounded-lg transition-all font-medium"
              >
                {item.title}
              </button>
            ))}
          </div>
          <textarea
            autoFocus
            rows={3}
            className="w-full text-sm border border-border rounded-xl px-3.5 py-2.5 outline-none focus:border-brand focus:ring-2 focus:ring-brand/10 transition-all text-foreground placeholder:text-muted resize-y min-h-[80px] max-h-[220px] leading-relaxed font-normal"
            placeholder="Describe the task in detail with any specific instructions, requirements, or explanations…"
            value={deployPrompt}
            onChange={(e) => setDeployPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && e.metaKey) handleDeploy(agent.id)
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
