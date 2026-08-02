import React from "react"
import { CheckCircle2, CircleDashed, ArrowRight } from "lucide-react"

interface WorkflowDagProps {
  workflowDag: string[]
  currentTaskIndex: number
  workflowStatus: string
}

export const WorkflowDag = ({
  workflowDag,
  currentTaskIndex,
  workflowStatus
}: WorkflowDagProps) => {
  return (
    <div className="px-6 py-3 bg-surface">
      <p className="text-[10px] font-semibold text-muted uppercase tracking-widest mb-2.5">
        Workflow Pipeline
      </p>
      <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-hide">
        {workflowDag.map((task, idx) => {
          const isCompleted =
            idx < currentTaskIndex || workflowStatus === "COMPLETED"
          const isActive =
            idx === currentTaskIndex &&
            workflowStatus !== "IDLE" &&
            workflowStatus !== "COMPLETED"
          const isWaiting =
            idx === currentTaskIndex && workflowStatus === "WAITING_ON_HUMAN"

          return (
            <div key={task} className="flex items-center shrink-0">
              <div
                className={`
                  flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all duration-500
                  ${
                    isCompleted
                      ? "bg-green-50 text-green-700 border border-green-200"
                      : isWaiting
                        ? "bg-orange-50 text-orange-700 border border-orange-200 animate-pulse"
                        : isActive
                          ? "bg-brandLight text-brand border border-brand/30"
                          : "bg-gray-100 text-muted border border-gray-200"
                  }
                `}
              >
                {isCompleted ? (
                  <CheckCircle2 size={13} />
                ) : (
                  <CircleDashed
                    size={13}
                    className={isActive && !isWaiting ? "animate-spin" : ""}
                  />
                )}
                {task}
              </div>
              {idx < workflowDag.length - 1 && (
                <ArrowRight size={13} className="mx-1.5 text-gray-300" />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
