import { api } from "@/services/apiClient"
import { useToast } from "@/store/useToast"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"

export interface DlqItem {
  id: string
  docId: string
  field: string
  extracted: string
  error: string
  status: "NEEDS_REVIEW" | "RESOLVED"
}

export const useDlq = () => {
  const { addToast } = useToast()
  const queryClient = useQueryClient()

  const { data: dlqItems = [], isLoading } = useQuery<DlqItem[]>({
    queryKey: ["dlq"],
    queryFn: async () => {
      const data = await api.get<any[]>("/api/dlq?tenant_id=default-tenant")
      return data.map((item: any) => ({
        id: item.task_id,
        docId: item.document_id,
        field: "schema-aligner", 
        extracted: item.payload?.extracted_data ? JSON.stringify(item.payload.extracted_data, null, 2) : "{}",
        error: item.error,
        status: "NEEDS_REVIEW"
      }))
    }
  })

  const resolveMutation = useMutation({
    mutationFn: async ({
      id,
      correctValue
    }: {
      id: string
      correctValue: string
    }) => {
      const item = dlqItems.find((i: DlqItem) => i.id === id)
      if (!item) throw new Error("Item not found")

      return await api.post("/api/hitl/resolve", {
        id: item.id,
        tenant_id: "default-tenant",
        document_id: item.docId,
        patch_type: "jsonb",
        field_name: "", // We patch the entire extracted_data block
        correct_value: correctValue
      })
    },
    onMutate: async ({ id, correctValue }) => {
      await queryClient.cancelQueries({ queryKey: ["dlq"] })
      const previousDlq = queryClient.getQueryData<DlqItem[]>(["dlq"])

      queryClient.setQueryData<DlqItem[]>(["dlq"], (old) =>
        old?.map((item) =>
          item.id === id
            ? { ...item, extracted: correctValue, status: "RESOLVED" }
            : item
        )
      )

      return { previousDlq }
    },
    onError: (err: any, variables, context) => {
      addToast("error", err.message || "Failed to resolve item")
      if (context?.previousDlq) {
        queryClient.setQueryData(["dlq"], context.previousDlq)
      }
    },
    onSuccess: () => {
      addToast("success", "Item resolved and database patched successfully.")
    }
  })

  const handleResolve = (id: string, correctValue: string) => {
    resolveMutation.mutate({ id, correctValue })
  }

  return { dlqItems, isLoading, handleResolve }
}
