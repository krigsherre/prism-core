"use client"

import React, { useState } from "react"
import { Plus, Loader2, Bot, Activity } from "lucide-react"
import { useAgents } from "../useAgents"
import { AgentCreator } from "./AgentCreator"
import { AgentCard } from "./AgentCard"
import { AgentTaskRow } from "./AgentTaskRow"
import { TaskDetailsModal } from "./TaskDetailsModal"

export const AgentList = () => {
  const { agents, tasks, isLoading, deployAgent, createAgent } = useAgents()
  const [isCreatorOpen, setIsCreatorOpen] = useState(false)

  const [deployPrompt, setDeployPrompt] = useState("")
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null)
  const [selectedTask, setSelectedTask] = useState<any>(null)

  const handleDeploy = (agentId: string) => {
    if (!deployPrompt.trim()) return
    deployAgent(agentId, deployPrompt)
    setDeployPrompt("")
    setSelectedAgentId(null)
  }

  const activeTasks = tasks.filter((t: any) => t.status === "RUNNING").length

  return (
    <div className="flex flex-col h-full w-full overflow-auto bg-background">
      {/* Page Header */}
      <div className="bg-surface border-b border-border px-8 py-5 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-brandLight border border-brand/20 flex items-center justify-center">
              <Bot size={18} className="text-brand" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-foreground">Virtual Employees</h1>
              <p className="text-xs text-muted">Deploy specialized agents to perform complex workflows</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* Stats */}
            <div className="flex items-center gap-4 text-sm px-4 py-2 bg-background rounded-xl border border-border">
              <div className="text-center">
                <p className="font-bold text-foreground">{agents.length}</p>
                <p className="text-[10px] text-muted uppercase tracking-wide">Agents</p>
              </div>
              <div className="h-8 w-px bg-border" />
              <div className="text-center">
                <p className="font-bold text-foreground">{tasks.length}</p>
                <p className="text-[10px] text-muted uppercase tracking-wide">Tasks</p>
              </div>
              <div className="h-8 w-px bg-border" />
              <div className="text-center flex flex-col items-center">
                <div className="flex items-center gap-1">
                  <span className={`w-1.5 h-1.5 rounded-full ${activeTasks > 0 ? "bg-green-500 animate-pulse" : "bg-gray-300"}`} />
                  <p className="font-bold text-foreground">{activeTasks}</p>
                </div>
                <p className="text-[10px] text-muted uppercase tracking-wide">Active</p>
              </div>
            </div>
            <button
              onClick={() => setIsCreatorOpen(true)}
              className="bg-brand text-white px-4 py-2.5 rounded-xl text-sm font-medium flex items-center gap-2 hover:bg-brandHover transition-colors shadow-sm"
            >
              <Plus size={16} />
              Create Agent
            </button>
          </div>
        </div>
      </div>

      <div className="flex-1 p-8">
        {isLoading ? (
          <div className="flex items-center justify-center p-16">
            <Loader2 className="animate-spin text-brand" size={28} />
          </div>
        ) : (
          <div className="flex flex-col gap-10">
            {/* Available Agents */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <h2 className="text-xs font-semibold text-muted uppercase tracking-wider">
                  Available Agents
                </h2>
                <span className="bg-brandLight text-brand text-[10px] font-bold px-2 py-0.5 rounded-full">
                  {agents.length}
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {agents.map((agent: any) => (
                  <AgentCard
                    key={agent.id}
                    agent={agent}
                    selectedAgentId={selectedAgentId}
                    deployPrompt={deployPrompt}
                    setDeployPrompt={setDeployPrompt}
                    setSelectedAgentId={setSelectedAgentId}
                    handleDeploy={handleDeploy}
                  />
                ))}
                {agents.length === 0 && (
                  <div className="col-span-full py-14 text-center border border-dashed border-border rounded-xl text-muted">
                    <Bot size={28} className="mx-auto mb-3 text-gray-300" />
                    <p className="text-sm font-medium">No agents yet</p>
                    <p className="text-xs mt-1">Create your first agent to get started</p>
                  </div>
                )}
              </div>
            </section>

            {/* Task History */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <Activity size={14} className="text-muted" />
                <h2 className="text-xs font-semibold text-muted uppercase tracking-wider">
                  Task History
                </h2>
                {tasks.length > 0 && (
                  <span className="bg-gray-100 text-muted text-[10px] font-bold px-2 py-0.5 rounded-full">
                    {tasks.length}
                  </span>
                )}
              </div>
              <div className="flex flex-col gap-2">
                {tasks.map((t: any) => (
                  <AgentTaskRow key={t.id} task={t} onClick={setSelectedTask} />
                ))}
                {tasks.length === 0 && (
                  <div className="py-12 text-center border border-dashed border-border rounded-xl text-muted bg-surface">
                    <p className="text-sm">No tasks run yet. Deploy an agent above.</p>
                  </div>
                )}
              </div>
            </section>
          </div>
        )}
      </div>

      {isCreatorOpen && (
        <AgentCreator
          onClose={() => setIsCreatorOpen(false)}
          onCreate={createAgent}
        />
      )}

      {selectedTask && (
        <TaskDetailsModal
          task={selectedTask}
          onClose={() => setSelectedTask(null)}
        />
      )}
    </div>
  )
}
