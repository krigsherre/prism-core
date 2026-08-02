"use client"

import { useToast } from "@/store/useToast"
import { X, CheckCircle, AlertCircle, Info } from "lucide-react"
import clsx from "clsx"

export const ToastContainer = () => {
  const { toasts, removeToast } = useToast()

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((toast) => {
        const isError = toast.type === "error"
        const isSuccess = toast.type === "success"

        return (
          <div
            key={toast.id}
            className={clsx(
              "flex items-center gap-3 min-w-[300px] bg-white border shadow-lg rounded-lg p-4 animate-in slide-in-from-right-8 duration-300 transition-all",
              isError
                ? "border-red-200"
                : isSuccess
                  ? "border-green-200"
                  : "border-border"
            )}
          >
            {isError && <AlertCircle size={20} className="text-red-500" />}
            {isSuccess && <CheckCircle size={20} className="text-green-500" />}
            {!isError && !isSuccess && (
              <Info size={20} className="text-brand" />
            )}

            <p className="text-sm font-medium text-foreground flex-1">
              {toast.message}
            </p>

            <button
              onClick={() => removeToast(toast.id)}
              className="text-gray-400 hover:text-gray-600 transition-colors"
            >
              <X size={16} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
