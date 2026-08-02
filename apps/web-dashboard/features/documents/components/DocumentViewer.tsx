"use client"

import { useEffect, useRef, useState } from "react"
import { useAppStore } from "@/store/useAppStore"
import { Maximize, ZoomIn, X } from "lucide-react"
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/esm/Page/AnnotationLayer.css'
import 'react-pdf/dist/esm/Page/TextLayer.css'

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.js`

export const DocumentViewer = () => {
  const { activeBBox, activeDocumentUrl, activePage, setActiveDocumentUrl } = useAppStore()
  const containerRef = useRef<HTMLDivElement>(null)
  const [numPages, setNumPages] = useState<number>()
  const [pageNumber, setPageNumber] = useState<number>(1)
  const [canvasWidth, setCanvasWidth] = useState(0)

  useEffect(() => {
    if (activePage && activePage > 0) {
      setPageNumber(activePage)
    }
  }, [activePage, activeBBox])

  useEffect(() => {
    if (!containerRef.current) return

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setCanvasWidth(entry.contentRect.width - 64)
      }
    })

    observer.observe(containerRef.current)
    return () => observer.disconnect()
  }, [])

  function onDocumentLoadSuccess({ numPages }: { numPages: number }): void {
    setNumPages(numPages)
  }

  const getHighlightStyles = () => {
    if (!activeBBox || canvasWidth === 0) return { display: "none" }

    const heightRatio = 11 / 8.5
    const canvasHeight = canvasWidth * heightRatio

    let x_min: number, y_min: number, x_max: number, y_max: number
    if (Array.isArray(activeBBox)) {
      if (activeBBox.length < 4) return { display: "none" }
      ;[x_min, y_min, x_max, y_max] = activeBBox
    } else {
      ;({ x_min, y_min, x_max, y_max } = activeBBox)
    }

    let left = x_min
    let top = y_min
    let boxWidth = x_max - x_min
    let boxHeight = y_max - y_min

    // Absolute PDF-point coords (e.g. > 1.0) → normalize to US Letter
    if (x_max > 1.0) {
      left = left / 612
      top = top / 792
      boxWidth = boxWidth / 612
      boxHeight = boxHeight / 792
    }

    return {
      left: `${left * canvasWidth}px`,
      top: `${top * canvasHeight}px`,
      width: `${boxWidth * canvasWidth}px`,
      height: `${boxHeight * canvasHeight}px`,
      display: "block"
    }
  }

  if (!activeDocumentUrl) return null;

  return (
    <div className="w-full h-full flex flex-col bg-surface border border-border rounded-2xl shadow-sm overflow-hidden transition-all duration-300">
      {/* Header */}
      <div className="h-14 border-b border-border flex items-center px-4 justify-between bg-surface">
        <h3 className="text-sm font-medium text-foreground flex items-center gap-2">
          <ZoomIn size={16} className="text-brand" />
          <span className="truncate max-w-[200px]">
            {activeDocumentUrl.split('/').pop() || "Document Viewer"}
          </span>
        </h3>
        <div className="flex items-center gap-2">
          <button className="p-2 hover:bg-gray-100 rounded-lg transition-colors text-gray-500 hover:text-brand">
            <Maximize size={16} />
          </button>
          <button
            onClick={() => setActiveDocumentUrl(null)}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors text-gray-500 hover:text-red-500"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      {/* PDF Viewer */}
      <div ref={containerRef} className="flex-1 p-8 overflow-y-auto overflow-x-hidden flex flex-col items-center bg-gray-50 relative">
        <div className="relative shadow-md rounded-sm group bg-white">
          <Document
            file={activeDocumentUrl}
            onLoadSuccess={onDocumentLoadSuccess}
            loading={
              <div className="w-full aspect-[8.5/11] bg-gray-100 animate-pulse flex items-center justify-center text-gray-400 rounded-sm">
                Loading Document...
              </div>
            }
            error={
              <div className="w-full aspect-[8.5/11] bg-gray-100 flex items-center justify-center text-red-500 text-sm rounded-sm">
                Failed to load document
              </div>
            }
          >
            <Page
              pageNumber={pageNumber}
              width={canvasWidth || undefined}
              className="rounded-sm overflow-hidden"
              renderAnnotationLayer={false}
              renderTextLayer={true}
            />
          </Document>

          {/* Glowing Highlight Rectangle */}
          <div
            className="absolute z-10 pointer-events-none transition-all duration-500 ease-out bg-brand/10 border-2 border-brand rounded-sm mix-blend-multiply"
            style={getHighlightStyles()}
          />
        </div>

        {/* Pagination controls */}
        {numPages && numPages > 1 && (
          <div className="sticky bottom-6 mt-6 bg-surface border border-border rounded-full px-4 py-2 flex items-center gap-4 shadow-sm z-20">
            <button
              disabled={pageNumber <= 1}
              onClick={() => setPageNumber(p => p - 1)}
              className="text-xs font-medium text-gray-500 hover:text-brand disabled:opacity-50 transition-colors"
            >
              Previous
            </button>
            <span className="text-xs font-mono text-gray-700">
              {pageNumber} / {numPages}
            </span>
            <button
              disabled={pageNumber >= numPages}
              onClick={() => setPageNumber(p => p + 1)}
              className="text-xs font-medium text-gray-500 hover:text-brand disabled:opacity-50 transition-colors"
            >
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
