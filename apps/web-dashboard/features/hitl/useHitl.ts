import { api } from "@/services/apiClient"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useToast } from "@/store/useToast"

export interface CellIssue {
  row_index: number
  column: string
  current_value?: string | null
  expected_or_issue: string
  suggested_value?: string | null
  question: string
}

export interface HitlReview {
  summary: string
  issues: CellIssue[]
  proposed_extracted_data: Record<string, unknown>
}

export interface HitlRequest {
  id: string
  document_id: string
  status: "PENDING" | "RESOLVED" | "DISCARDED"
  created_at: string
  error: string
  payload: {
    hitl_review?: HitlReview
    extracted_data?: Record<string, unknown>
    target_table?: string
    source_bbox?: number[]
    source_page?: number
    payload?: { hitl_review?: HitlReview }
    [key: string]: unknown
  }
  s3_uri?: string
}

export const useHitl = () => {
  const queryClient = useQueryClient()
  const { addToast } = useToast()

  const { data: requests = [], isLoading } = useQuery({
    queryKey: ["hitl"],
    queryFn: async () => {
      return await api.get<HitlRequest[]>("/api/hitl?tenant_id=default-tenant")
    }
  })

  const resolveMutation = useMutation({
    mutationFn: async ({ id, document_id, correctValue }: { id: string, document_id: string, correctValue: string }) => {
      return await api.post("/api/hitl/resolve", {
        id,
        document_id,
        tenant_id: "default-tenant",
        patch_type: "jsonb",
        correct_value: correctValue
      })
    },
    onSuccess: () => {
      addToast("success", "HITL Request Resolved successfully")
      queryClient.invalidateQueries({ queryKey: ["hitl"] })
    },
    onError: (err: any) => {
      addToast("error", err.message || "Failed to resolve HITL request")
    }
  })

  const discardMutation = useMutation({
    mutationFn: async ({ id, document_id }: { id: string, document_id: string }) => {
      return await api.post("/api/hitl/discard", {
        id,
        document_id,
        tenant_id: "default-tenant"
      })
    },
    onSuccess: () => {
      addToast("success", "HITL Request Discarded")
      queryClient.invalidateQueries({ queryKey: ["hitl"] })
    },
    onError: (err: any) => {
      addToast("error", err.message || "Failed to discard HITL request")
    }
  })

  const approveGenericMutation = useMutation({
    mutationFn: async ({ document_id, node_id, target_table, unmapped_rows }: { document_id: string, node_id: string, target_table: string, unmapped_rows: any[] }) => {
      return await api.post("/api/v1/hitl/approve-generic", {
        document_id,
        node_id,
        target_table,
        unmapped_rows,
        tenant_id: "default-tenant"
      })
    },
    onSuccess: () => {
      addToast("success", "Approved table as Generic JSONB payload")
      queryClient.invalidateQueries({ queryKey: ["hitl"] })
    },
    onError: (err: any) => {
      addToast("error", err.message || "Failed to approve generic table")
    }
  })

  const divertRagMutation = useMutation({
    mutationFn: async ({ document_id, node_id, markdown_content }: { document_id: string, node_id: string, markdown_content: string }) => {
      return await api.post("/api/v1/hitl/divert-rag", {
        document_id,
        node_id,
        markdown_content,
        parent_section_text: "",
        tenant_id: "default-tenant"
      })
    },
    onSuccess: () => {
      addToast("success", "Diverted unmapped table directly to RAG (Vector & Graph)")
      queryClient.invalidateQueries({ queryKey: ["hitl"] })
    },
    onError: (err: any) => {
      addToast("error", err.message || "Failed to divert table to RAG")
    }
  })

  return { 
    requests, 
    isLoading,
    resolve: resolveMutation.mutate,
    discard: discardMutation.mutate,
    approveGeneric: approveGenericMutation.mutate,
    divertRag: divertRagMutation.mutate,
    isResolving: resolveMutation.isPending,
    isDiscarding: discardMutation.isPending,
    isApprovingGeneric: approveGenericMutation.isPending,
    isDivertingRag: divertRagMutation.isPending
  }
}
