"use client"

import { DocumentQueue } from "@/features/documents/components/DocumentQueue"
import { UploadButton } from "@/features/documents/components/UploadButton"
import { DocumentViewer } from "@/components/DocumentViewer"
import { useAppStore } from "@/store/useAppStore"
import { motion, AnimatePresence } from "framer-motion"

export default function DocumentsPage() {
  const activeDocumentUrl = useAppStore((state) => state.activeDocumentUrl)
  const setActiveDocumentUrl = useAppStore((state) => state.setActiveDocumentUrl)
  const setActiveBBox = useAppStore((state) => state.setActiveBBox)
  const setActivePage = useAppStore((state) => state.setActivePage)

  const closeViewer = () => {
    setActiveDocumentUrl(null)
    setActiveBBox(null)
    setActivePage(null)
  }

  return (
    <div className="flex h-full w-full p-8 gap-4 overflow-hidden bg-surface">
      <div
        className={`flex flex-col min-h-0 overflow-auto ${
          activeDocumentUrl ? "flex-1 min-w-[420px]" : "flex-1 max-w-4xl"
        }`}
      >
        <div className="mb-8 flex justify-between items-start shrink-0">
          <div>
            <h1 className="text-2xl font-bold mb-1">Documents & Ingestion</h1>
            <p className="text-sm text-gray-500">
              Upload documents and track their real-time ingestion status. Click a
              document to preview it in the viewer.
            </p>
          </div>
          <UploadButton />
        </div>

        <div className="w-full pb-8">
          <DocumentQueue />
        </div>
      </div>

      <AnimatePresence>
        {activeDocumentUrl && (
          <motion.div
            initial={{ opacity: 0, x: 40, width: 0 }}
            animate={{ opacity: 1, x: 0, width: "48%" }}
            exit={{ opacity: 0, x: 40, width: 0 }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            className="h-full flex-shrink-0 min-w-[380px]"
          >
            <DocumentViewer closeViewer={closeViewer} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
