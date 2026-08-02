import { create } from "zustand"

export interface Reference {
  doc_id: string
  source_page?: number
  source_bbox?: number[]
}

export interface ChatMessage {
  id: string
  role: "user" | "agent"
  content: string
  references?: Reference[]
}

interface AppState {
  activeDocumentUrl: string | null
  activeBoundingBox: number[] | null
  activePage: number | null
  chatMessages: ChatMessage[]
  setActiveDocument: (url: string | null) => void
  setProvenance: (page?: number, bbox?: number[]) => void
  addMessage: (msg: ChatMessage) => void
}

export const useStore = create<AppState>((set) => ({
  activeDocumentUrl: null,
  activeBoundingBox: null,
  activePage: null,
  chatMessages: [],

  setActiveDocument: (url) => set({ activeDocumentUrl: url }),
  setProvenance: (page, bbox) =>
    set({
      activePage: page || null,
      activeBoundingBox: bbox || null
    }),
  addMessage: (msg) =>
    set((state) => ({
      chatMessages: [...state.chatMessages, msg]
    }))
}))
