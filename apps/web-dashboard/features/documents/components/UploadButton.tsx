"use client"
import React, { useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { UploadCloud, Loader2 } from "lucide-react"
import { motion } from "framer-motion"

import { useToast } from "@/store/useToast"

export const UploadButton = () => {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const { addToast } = useToast()

  const handleUploadClick = () => {
    fileInputRef.current?.click()
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsUploading(true)
    setUploadProgress(0)

    try {
      const formData = new FormData()
      formData.append("file", file)
      formData.append("tenant_id", "default-tenant")

      const gatewayUrl = process.env.NEXT_PUBLIC_GATEWAY_URL || "/api/gateway"

      await new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open("POST", `${gatewayUrl}/v1/upload`)
        xhr.setRequestHeader("X-Tenant-ID", "default-tenant")

        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) {
            const percentage = Math.round((event.loaded * 100) / event.total)
            setUploadProgress(percentage)
          }
        }

        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve()
          } else {
            reject(new Error(`Upload failed with status ${xhr.status}`))
          }
        }

        xhr.onerror = () => reject(new Error("Network Error"))
        
        xhr.send(formData)
      })

      addToast("success", "Document uploaded successfully! It will now be processed.")
    } catch (error) {
      console.error("Error uploading file:", error)
      addToast("error", "Failed to upload document. Please try again.")
    } finally {
      setIsUploading(false)
      setUploadProgress(0)
      if (fileInputRef.current) {
        fileInputRef.current.value = ""
      }
    }
  }

  return (
    <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}>
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        className="hidden"
        accept="application/pdf,image/*,.txt,.md"
      />
      <Button 
        onClick={handleUploadClick} 
        disabled={isUploading}
        className="rounded-full shadow-md bg-brand hover:bg-brandHover text-surface flex items-center gap-2 px-6 py-5 border-none"
      >
        {isUploading ? (
          <Loader2 size={18} className="animate-spin" />
        ) : (
          <UploadCloud size={18} />
        )}
        <span className="font-medium">
          {isUploading ? `Uploading... ${uploadProgress}%` : "Upload Document"}
        </span>
      </Button>
    </motion.div>
  )
}
