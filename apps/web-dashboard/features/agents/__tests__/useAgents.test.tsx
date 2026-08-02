import { renderHook, waitFor } from "@testing-library/react"
import { useAgents } from "../useAgents"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

global.fetch = jest.fn()

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false
      }
    }
  })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

describe("useAgents hook", () => {
  beforeEach(() => {
    ; (global.fetch as jest.Mock).mockClear()
  })

  it("fetches agents and tasks successfully", async () => {
    const mockAgents = [
      {
        id: "1",
        name: "Agent 1",
        description: "Desc 1",
        system_prompt: "Prompt 1"
      }
    ]
    const mockTasks = [
      {
        id: "t1",
        name: "Task 1",
        status: "COMPLETED",
        result: "Success",
        time: "2026-08-01"
      }
    ]

      ; (global.fetch as jest.Mock).mockImplementation((url: string) => {
        if (url.includes("/api/agents")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(mockAgents)
          })
        }
        if (url.includes("/api/work")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(mockTasks)
          })
        }
        return Promise.reject(new Error("not found"))
      })

    const { result } = renderHook(() => useAgents(), {
      wrapper: createWrapper()
    })
    expect(result.current.isLoading).toBe(true)

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.agents).toEqual(mockAgents)
    expect(result.current.tasks).toEqual(mockTasks)
  })
})
