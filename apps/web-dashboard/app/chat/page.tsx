"use client"
import { ChatPane } from "@/features/chat/components/ChatPane"
import { DocumentViewer } from "@/components/DocumentViewer"
import { useAppStore } from "@/store/useAppStore"
import { motion, AnimatePresence } from "framer-motion"

export default function ChatPage() {
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
    <div className="flex h-full w-full p-4 gap-4 overflow-hidden bg-background">
      {/* Left Pane: Agentic Chat */}
      <motion.div
        layout
        className={`h-full flex flex-col ${activeDocumentUrl ? 'flex-1 min-w-[500px]' : 'flex-1 max-w-4xl mx-auto'}`}
      >
        <ChatPane />
      </motion.div>

      {/* Right Pane: Split-Screen Provenance */}
      <AnimatePresence>
        {activeDocumentUrl && (
          <motion.div
            initial={{ opacity: 0, x: 50, width: 0 }}
            animate={{ opacity: 1, x: 0, width: '50%' }}
            exit={{ opacity: 0, x: 50, width: 0 }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            className="h-full flex-shrink-0 min-w-[400px]"
          >
            <DocumentViewer closeViewer={closeViewer} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
