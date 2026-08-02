"use client"

import { useState } from "react"
import { useAppStore } from "@/store/useAppStore"
import { AlertCircle, Send, Loader2 } from "lucide-react"

export const HumanApprovalCard = () => {
  const { sqlError, currentSql, submitHumanCorrection } = useAppStore()
  const [inputSql, setInputSql] = useState(currentSql || "")
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (!inputSql.trim()) return
    setIsSubmitting(true)
    await submitHumanCorrection(inputSql)
    setIsSubmitting(false)
  }

  return (
    <div className="w-full bg-amber-50 border border-amber-200 rounded-xl p-5 flex flex-col gap-4 shadow-card animate-in slide-in-from-bottom-2 duration-300">
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-lg bg-amber-100 border border-amber-200 flex items-center justify-center shrink-0 mt-0.5">
          <AlertCircle className="text-amber-600" size={16} />
        </div>
        <div>
          <h4 className="text-sm font-semibold text-amber-900 mb-1.5">
            Human-In-The-Loop Breakpoint
          </h4>
          {sqlError && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              <p className="text-xs text-red-700 font-mono leading-relaxed">{sqlError}</p>
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <label className="text-xs font-semibold text-foreground uppercase tracking-wide">
          Review & Correct SQL
        </label>
        <textarea
          className="w-full bg-white border border-border rounded-xl p-3 text-sm font-mono text-foreground focus:outline-none focus:border-brand focus:ring-2 focus:ring-brand/10 transition-all resize-y min-h-[80px]"
          value={inputSql}
          onChange={(e) => setInputSql(e.target.value)}
          placeholder="SELECT * FROM …"
        />
      </div>

      <button
        onClick={handleSubmit}
        disabled={isSubmitting || !inputSql.trim()}
        className="w-full py-2.5 bg-brand hover:bg-brandHover text-white text-sm font-semibold rounded-xl transition-colors flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isSubmitting ? (
          <><Loader2 size={15} className="animate-spin" /> Submitting…</>
        ) : (
          <><Send size={15} /> Submit Correction</>
        )}
      </button>
    </div>
  )
}
