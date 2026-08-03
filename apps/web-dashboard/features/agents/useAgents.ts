import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import type { Agent, AgentTask } from "@/types"
import { api } from "@/services/apiClient"

export const useAgents = () => {
  const queryClient = useQueryClient()

  const { data: personas = [] } = useQuery({
    queryKey: ["agent_personas"],
    queryFn: async () => {
      return await api.get<any[]>("/api/agents/personas")
    }
  })

  const { data: agents = [], isLoading: agentsLoading } = useQuery({
    queryKey: ["agents"],
    queryFn: async () => {
      return await api.get<Agent[]>("/api/agents?tenant_id=default-tenant")
    }
  })

  const { data: tasks = [], isLoading: tasksLoading } = useQuery({
    queryKey: ["agent_tasks"],
    queryFn: async () => {
      return await api.get<AgentTask[]>("/api/work?tenant_id=default-tenant")
    },
    refetchInterval: 3000
  })

  const createMutation = useMutation({
    mutationFn: async (newAgent: {
      name: string
      description: string
      system_prompt: string
    }) => {
      return await api.post("/api/agents?tenant_id=default-tenant", newAgent)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] })
    }
  })

  const deployMutation = useMutation({
    mutationFn: async ({
      agentId,
      prompt
    }: {
      agentId: string
      prompt: string
    }) => {
      return await api.post("/api/work?tenant_id=default-tenant", {
        agent_id: agentId,
        prompt: prompt
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent_tasks"] })
    }
  })

  return {
    personas,
    agents,
    tasks,
    isLoading: agentsLoading || tasksLoading,
    deployAgent: (agentId: string, prompt: string) =>
      deployMutation.mutate({ agentId, prompt }),
    createAgent: (data: {
      name: string
      description: string
      system_prompt: string
    }) => createMutation.mutateAsync(data)
  }
}
