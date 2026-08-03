"use client"

import React, { useState } from "react"
import { Plus, Loader2, Bot, Activity, UserCog } from "lucide-react"
import { useAgents } from "../useAgents"
import { AgentCreator } from "./AgentCreator"
import { AgentCard } from "./AgentCard"
import { AgentTaskRow } from "./AgentTaskRow"
import { TaskDetailsModal } from "./TaskDetailsModal"

export const AgentList = () => {
  const { personas, agents, tasks, isLoading, deployAgent, createAgent } = useAgents()
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

  const handleDeployPersona = (p: any) => {
    createAgent({
      name: p.name,
      description: p.description,
      system_prompt: p.system_prompt
    })
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
              <p className="text-xs text-muted">Deploy specialized AI employee personas to perform complex financial workflows</p>
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
              Create Custom Agent
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
            {/* Pre-configured AI Employee Personas */}
            {personas.length > 0 && (
              <section>
                <div className="flex items-center gap-2 mb-4">
                  <h2 className="text-xs font-semibold text-muted uppercase tracking-wider">
                    Pre-Configured AI Employee Personas
                  </h2>
                  <span className="bg-purple-100 text-purple-700 text-[10px] font-bold px-2 py-0.5 rounded-full">
                    {personas.length} Presets
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
                  {personas.map((p: any) => (
                    <div key={p.id} className="bg-white border border-border rounded-xl p-5 shadow-card flex flex-col justify-between hover:border-brand/40 transition-all group">
                      <div>
                        <div className="flex items-center gap-3 mb-3">
                          <div className="w-8 h-8 rounded-lg bg-brandLight border border-brand/20 flex items-center justify-center shrink-0">
                            <UserCog size={16} className="text-brand" />
                          </div>
                          <h3 className="text-sm font-bold text-foreground">{p.name}</h3>
                        </div>
                        <p className="text-xs text-muted mb-5 leading-relaxed">{p.description}</p>
                      </div>
                      <button
                        onClick={() => handleDeployPersona(p)}
                        className="w-full bg-surface text-foreground border border-border hover:bg-brand hover:text-white hover:border-brand text-xs font-semibold py-2.5 rounded-lg transition-colors flex items-center justify-center gap-1.5"
                      >
                        <Plus size={14} /> Instantiate Persona
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Available Agents */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <h2 className="text-xs font-semibold text-muted uppercase tracking-wider">
                  Active Virtual Employees
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
                    <p className="text-sm font-medium">No active virtual employees yet</p>
                    <p className="text-xs mt-1">Instantiate a preset persona above or create a custom agent</p>
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
