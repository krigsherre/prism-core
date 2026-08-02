"use client"

import { useEffect } from "react"
import { Button } from "@/components/ui/button"

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error("Global Error Boundary caught:", error)
  }, [error])

  return (
    <div className="flex flex-col items-center justify-center h-full w-full p-8 bg-surface space-y-4">
      <div className="bg-red-50 border border-red-100 rounded-xl p-8 max-w-md w-full text-center space-y-4">
        <h2 className="text-xl font-bold text-red-800">Something went wrong!</h2>
        <p className="text-sm text-red-600 font-mono overflow-auto text-left bg-red-100/50 p-3 rounded-lg max-h-32">
          {error.message || "An unexpected error occurred."}
        </p>
        <Button
          onClick={() => reset()}
          className="bg-red-600 hover:bg-red-700 text-white rounded-full w-full shadow-sm"
        >
          Try again
        </Button>
      </div>
    </div>
  )
}
