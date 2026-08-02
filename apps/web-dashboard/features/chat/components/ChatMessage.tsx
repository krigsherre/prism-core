"use client"

import React from "react"
import { Bot, User } from "lucide-react"
import { motion } from "framer-motion"
import ReactMarkdown from "react-markdown"
import { useAppStore } from "@/store/useAppStore"
import { api } from "@/services/apiClient"

interface ChatMessageProps {
  role: "user" | "agent"
  content: string
}

async function resolveDocumentUrl(href: string): Promise<string> {
  const cleanUrl = href.split("#")[0]

  if (cleanUrl.startsWith("s3://") || cleanUrl.includes("/api/documents/content")) {
    return cleanUrl
  }

  // Citation hrefs are often bare document_ids — resolve to s3_uri for the viewer.
  if (
    cleanUrl &&
    !cleanUrl.startsWith("http://") &&
    !cleanUrl.startsWith("https://") &&
    !cleanUrl.startsWith("/")
  ) {
    try {
      const meta = await api.get<{ s3_uri?: string }>(
        `/api/documents/${encodeURIComponent(cleanUrl)}?tenant_id=default-tenant`
      )
      if (meta?.s3_uri) return meta.s3_uri
    } catch (err) {
      console.error("Failed to resolve document for viewer", err)
    }
  }

  return cleanUrl
}

export const ChatMessage = ({ role, content }: ChatMessageProps) => {
  const isUser = role === "user"
  const setActiveDocumentUrl = useAppStore((state) => state.setActiveDocumentUrl)
  const setActiveBBox = useAppStore((state) => state.setActiveBBox)
  const setActivePage = useAppStore((state) => state.setActivePage)

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 380, damping: 28 }}
      className={`flex gap-3 w-full ${isUser ? "flex-row-reverse" : "flex-row"}`}
    >
      <div
        className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${
          isUser
            ? "bg-gray-100 border border-gray-200"
            : "bg-brand/10 border border-brand/20"
        }`}
      >
        {isUser ? (
          <User size={15} className="text-gray-500" />
        ) : (
          <Bot size={15} className="text-brand" />
        )}
      </div>

      <div
        className={`max-w-[82%] ${
          isUser
            ? "bg-brand text-white rounded-2xl rounded-tr-sm px-4 py-3 text-[14px] leading-relaxed shadow-sm"
            : "bg-white border border-border rounded-2xl rounded-tl-sm px-4 py-3 shadow-card"
        }`}
      >
        {isUser ? (
          <p className="text-[14px] leading-relaxed whitespace-pre-wrap">{content}</p>
        ) : (
          <div className="prose-chat">
            <ReactMarkdown
              components={{
                a: ({ href, children, ...props }) => {
                  return (
                    <a
                      href={href}
                      {...props}
                      className="text-brand underline underline-offset-2 cursor-pointer"
                      onClick={async (e) => {
                        if (!href) return
                        e.preventDefault()

                        const urlObj = new URL(href, window.location.origin)
                        const bboxMatch = urlObj.hash.match(
                          /bbox=([\d.]+),([\d.]+),([\d.]+),([\d.]+)/
                        )
                        const pageMatch = urlObj.hash.match(/page=(\d+)/)

                        const resolved = await resolveDocumentUrl(href)
                        setActiveDocumentUrl(resolved)

                        if (pageMatch) {
                          setActivePage(parseInt(pageMatch[1], 10))
                        } else {
                          setActivePage(null)
                        }

                        if (bboxMatch) {
                          setActiveBBox({
                            x_min: parseFloat(bboxMatch[1]),
                            y_min: parseFloat(bboxMatch[2]),
                            x_max: parseFloat(bboxMatch[3]),
                            y_max: parseFloat(bboxMatch[4]),
                          })
                        } else {
                          setActiveBBox(null)
                        }
                      }}
                    >
                      {children}
                    </a>
                  )
                },
              }}
            >
              {content}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </motion.div>
  )
}
