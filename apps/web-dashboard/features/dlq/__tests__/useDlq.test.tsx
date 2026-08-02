import { renderHook, waitFor } from "@testing-library/react"
import { useDlq } from "../useDlq"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"
import { useToast } from "@/store/useToast"
import { api } from "@/services/apiClient"

jest.mock("@/store/useToast")
jest.mock("@/services/apiClient")

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

describe("useDlq hook", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(useToast as unknown as jest.Mock).mockReturnValue({
      addToast: jest.fn()
    })
  })

  it("fetches DLQ entries successfully", async () => {
    ;(api.get as jest.Mock).mockResolvedValue([
      {
        task_id: "1",
        document_id: "doc-1",
        error: "invalid type",
        payload: { extracted_data: { revenue: 0 } }
      }
    ])

    const { result } = renderHook(() => useDlq(), { wrapper: createWrapper() })

    expect(result.current.isLoading).toBe(true)

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.dlqItems).toEqual([
      {
        id: "1",
        docId: "doc-1",
        field: "schema-aligner",
        extracted: JSON.stringify({ revenue: 0 }, null, 2),
        error: "invalid type",
        status: "NEEDS_REVIEW"
      }
    ])
  })
})
