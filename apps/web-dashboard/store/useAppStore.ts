import { create } from 'zustand';
import { API_BASE_URL } from "@/services/apiClient";
export interface BoundingBox {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

export interface Reference {
  doc_id?: string;
  source_page?: number;
  source_bbox?: number[] | BoundingBox;
}

export interface Message {
  id: string;
  role: "user" | "agent";
  content: string;
  thinking?: string;
  statusTrace?: string[];
  references?: Reference[];
  personaRole?: string;
  isStreaming?: boolean;
}

export interface AppState {
  workflowDag: string[];
  currentTaskIndex: number;
  workflowStatus: 'IDLE' | 'RUNNING' | 'WAITING_ON_HUMAN' | 'COMPLETED';
  threadId: string | null;
  sqlError: string | null;
  currentSql: string | null;
  messages: Message[];

  activeBBox: BoundingBox | number[] | null;
  activePage: number | null;
  activeDocumentUrl: string | null;
  activeDocumentId: string | null;

  startWorkflow: (dag: string[], intent: string, agentRole?: string, documentId?: string) => Promise<void>;
  submitHumanCorrection: (correctedSql: string) => Promise<void>;
  setActiveBBox: (bbox: BoundingBox | number[] | null) => void;
  setActivePage: (page: number | null) => void;
  setActiveDocumentUrl: (url: string | null) => void;
  setActiveDocumentId: (id: string | null) => void;
  addMessage: (msg: Message) => void;
  clearMessages: () => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  workflowDag: ["Extraction", "SchemaLinking", "Audit"],
  currentTaskIndex: 0,
  workflowStatus: 'IDLE',
  threadId: null,
  sqlError: null,
  currentSql: null,
  messages: [],
  activeBBox: null,
  activePage: null,
  activeDocumentUrl: null,
  activeDocumentId: null,

  setActiveBBox: (bbox) => set({ activeBBox: bbox }),
  setActivePage: (page) => set({ activePage: page }),
  setActiveDocumentUrl: (url) => set({ activeDocumentUrl: url }),
  setActiveDocumentId: (id) => set({ activeDocumentId: id }),
  addMessage: (msg) => set((state) => ({ messages: [...state.messages, msg] })),
  clearMessages: () => set({ messages: [] }),

  startWorkflow: async (dag, intent, agentRole = "forensic_auditor", documentId = "") => {
    const threadId = "thread-" + Date.now()
    const userMsg: Message = { id: Date.now().toString(), role: "user", content: intent }
    set((state) => ({
      workflowStatus: "RUNNING",
      workflowDag: dag,
      threadId,
      messages: [...state.messages, userMsg]
    }))

    try {
      const targetDocId = documentId || get().activeDocumentId || ""
      const response = await fetch(`${API_BASE_URL}/chat?tenant_id=default-tenant`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: threadId,
          message: intent,
          document_id: targetDocId,
          agent_role: agentRole
        })
      })

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}))
        throw new Error(errData.detail || errData.message || `API Error: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error("No readable stream")

      const decoder = new TextDecoder()
      const agentMsgId = "agent-" + Date.now().toString()
      let currentContent = ""
      let currentThinking = ""
      let statusTrace: string[] = []
      let references: Reference[] = []

      set((state) => ({
        messages: [
          ...state.messages,
          {
            id: agentMsgId,
            role: "agent",
            content: "",
            thinking: "",
            statusTrace: [],
            references: [],
            personaRole: agentRole,
            isStreaming: true
          }
        ]
      }))

      outer: while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split("\n\n")

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue
          const dataStr = line.slice(6).trim()
          if (dataStr === "[DONE]") { break outer }
          try {
            const data = JSON.parse(dataStr)
            if (data.type === "thinking") {
              currentThinking = data.content
              set((state) => ({
                messages: state.messages.map(m =>
                  m.id === agentMsgId ? { ...m, thinking: currentThinking } : m
                )
              }))
            } else if (data.type === "status") {
              if (data.content && !statusTrace.includes(data.content)) {
                statusTrace = [...statusTrace, data.content]
                set((state) => ({
                  messages: state.messages.map(m =>
                    m.id === agentMsgId ? { ...m, statusTrace } : m
                  )
                }))
              }
            } else if (data.type === "token") {
              if (typeof data.content === "string" && data.content.startsWith("Thinking")) {
                currentThinking = data.content.trim()
                set((state) => ({
                  messages: state.messages.map(m =>
                    m.id === agentMsgId ? { ...m, thinking: currentThinking } : m
                  )
                }))
              } else {
                currentContent += data.content
                set((state) => ({
                  messages: state.messages.map(m =>
                    m.id === agentMsgId ? { ...m, content: currentContent } : m
                  )
                }))
              }
            } else if (data.type === "message_complete" && data.content) {
              currentContent = data.content
              set((state) => ({
                messages: state.messages.map(m =>
                  m.id === agentMsgId ? { ...m, content: data.content, isStreaming: false } : m
                )
              }))
            } else if (data.type === "references" && Array.isArray(data.content)) {
              references = data.content
              set((state) => ({
                messages: state.messages.map(m =>
                  m.id === agentMsgId ? { ...m, references } : m
                )
              }))
            }
          } catch (e) {
            console.error("SSE parse error", e)
          }
        }
      }
    } catch (err) {
      console.error("Chat error:", err)
      set((state) => ({
        messages: [
          ...state.messages,
          { id: "err-" + Date.now(), role: "agent", content: `⚠️ ${(err as Error).message}` }
        ]
      }))
    } finally {
      set((state) => ({
        workflowStatus: "IDLE",
        messages: state.messages.map(m => ({ ...m, isStreaming: false }))
      }))
    }
  },

  submitHumanCorrection: async (correctedSql) => {
    set({ workflowStatus: "RUNNING", sqlError: null, currentSql: correctedSql })

    const threadId = get().threadId || ("thread-" + Date.now())
    const userMessage = `Please use this corrected SQL: ${correctedSql}`
    const msg: Message = { id: Date.now().toString(), role: "user", content: userMessage }

    set((state) => ({ messages: [...state.messages, msg] }))

    try {
      const response = await fetch(`${API_BASE_URL}/chat?tenant_id=default-tenant`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadId, message: userMessage })
      })

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}))
        throw new Error(errData.detail || errData.message || `API Error: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error("No readable stream")

      const decoder = new TextDecoder()
      const agentMsgId = "agent-" + Date.now().toString()
      let currentContent = ""

      set((state) => ({
        messages: [...state.messages, { id: agentMsgId, role: "agent", content: "" }]
      }))

      outer: while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split("\n\n")

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue
          const dataStr = line.slice(6).trim()
          if (dataStr === "[DONE]") { break outer }
          try {
            const data = JSON.parse(dataStr)
            if (data.type === "token") {
              currentContent += data.content
              set((state) => ({
                messages: state.messages.map(m =>
                  m.id === agentMsgId ? { ...m, content: currentContent } : m
                )
              }))
            } else if (data.type === "message_complete" && !currentContent && data.content) {
              currentContent = data.content
              set((state) => ({
                messages: state.messages.map(m =>
                  m.id === agentMsgId ? { ...m, content: data.content } : m
                )
              }))
            }
          } catch (e) {
            console.error("SSE parse error", e)
          }
        }
      }
    } catch (err) {
      console.error("Human correction error:", err)
      set((state) => ({
        messages: [
          ...state.messages,
          { id: "err-" + Date.now(), role: "agent", content: `⚠️ ${(err as Error).message}` }
        ]
      }))
    } finally {
      set({ workflowStatus: "IDLE" })
    }
  }
}));
