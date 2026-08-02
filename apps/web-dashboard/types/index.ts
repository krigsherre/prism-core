export interface Agent {
  id: string
  name: string
  description: string
  system_prompt: string
}

export interface AgentTask {
  id: string
  name: string
  status: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED"
  result: string
  time: string
}

export interface DocumentJob {
  document_id: string
  filename: string
  current_stage: string
  status: "PENDING" | "IN_PROGRESS" | "EXTRACTING" | "COMPLETED" | "FAILED" | "DUPLICATE"
  updated_at: string
}

export interface HitlRequest {
  id: string
  document_id: string
  status: "PENDING" | "RESOLVED" | "DISCARDED"
  error: string
  payload: any
  created_at: string
}

export interface DLQEntry {
  task_id: string
  document_id: string
  agent_name: string
  error: string
  created_at: string
}

export interface BoundingBox {
  x_min: number
  y_min: number
  x_max: number
  y_max: number
}
