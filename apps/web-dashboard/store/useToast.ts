import { create } from "zustand"

export type ToastType = "success" | "error" | "info"

export interface ToastMessage {
  id: string
  type: ToastType
  message: string
}

interface ToastState {
  toasts: ToastMessage[]
  addToast: (type: ToastType, message: string) => void
  removeToast: (id: string) => void
}

export const useToast = create<ToastState>((set) => ({
  toasts: [],
  addToast: (type, message) => {
    const id = Date.now().toString()
    set((state) => ({
      toasts: [...state.toasts, { id, type, message }]
    }))
    setTimeout(() => {
      set((state) => ({
        toasts: state.toasts.filter((t) => t.id !== id)
      }))
    }, 5000)
  },
  removeToast: (id) =>
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id)
    }))
}))
