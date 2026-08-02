"use client";

import { useStore } from "@/store/useStore";
import { FileUp, Loader2 } from "lucide-react";
import { useState } from "react";
import { Document, Page, pdfjs } from 'react-pdf';


pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.js`;

const PdfViewer = () => {
  const { activeDocumentUrl, activePage, activeBoundingBox } = useStore();
  const [isUploading, setIsUploading] = useState(false);
  const [numPages, setNumPages] = useState<number>();

  const onDocumentLoadSuccess = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
  };

  const renderBoundingBox = () => {
    if (!activeBoundingBox || activeBoundingBox.length !== 4) return null;

    const [x0, y0, x1, y1] = activeBoundingBox;

    return (
      <div
        className="absolute border-2 border-brand bg-brand/10 pointer-events-none transition-all duration-300 z-50"
        style={{
          left: `${x0 * 100}%`,
          top: `${y0 * 100}%`,
          width: `${(x1 - x0) * 100}%`,
          height: `${(y1 - y0) * 100}%`
        }}
      >
        <div className="absolute -top-6 -right-2 bg-brand text-white text-[10px] px-1.5 py-0.5 rounded shadow">
          Source Match
        </div>
      </div>
    );
  };

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setIsUploading(true);

    try {
      const formData = new FormData();
      formData.append("tenant_id", "test");
      formData.append("file", file);

      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/upload`, {
        method: "POST",
        body: formData
      });

      if (!response.ok) throw new Error("Upload failed");
      const data = await response.json();

      useStore.getState().setActiveDocument(data.url);

    } catch (err: any) {
      console.error(err);
    } finally {
      setIsUploading(false);
    }
  };

  if (!activeDocumentUrl) {
    return (
      <div className="h-full flex flex-col items-center justify-center p-8 bg-gray-50 border-l border-border">
        <div className="w-16 h-16 bg-white border border-dashed border-gray-300 rounded-2xl flex items-center justify-center mb-4 shadow-sm">
          <FileUp className="text-gray-400" size={24} />
        </div>
        <h3 className="text-sm font-semibold mb-1">No Document Selected</h3>
        <p className="text-xs text-gray-500 text-center max-w-xs mb-6">
          Upload a PDF to Agentic Brain or select an existing document to view provenance highlights here.
        </p>
        <label className="bg-white border border-border px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors shadow-sm cursor-pointer flex items-center gap-2">
          {isUploading ? <Loader2 size={16} className="animate-spin" /> : null}
          {isUploading ? "Uploading..." : "Upload Document"}
          <input
            type="file"
            accept="application/pdf"
            className="hidden"
            onChange={handleFileUpload}
            disabled={isUploading}
          />
        </label>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-gray-50 border-l border-border">
      {/* Viewer Header */}
      <div className="h-14 border-b border-border bg-surface flex items-center justify-between px-6 shrink-0">
        <span className="font-semibold text-sm truncate">Document Viewer</span>
        {activePage && (
          <span className="text-xs bg-gray-100 px-2 py-1 rounded font-medium text-gray-500">
            Page {activePage} {numPages ? `of ${numPages}` : ''}
          </span>
        )}
      </div>

      {/* Viewer Canvas Area */}
      <div className="flex-1 overflow-auto p-8 flex justify-center bg-gray-200/50">
        <div className="relative shadow-md">
          <Document
            file={activeDocumentUrl}
            onLoadSuccess={onDocumentLoadSuccess}
            loading={
              <div className="flex items-center justify-center h-[800px] w-[600px] bg-white">
                <Loader2 className="animate-spin text-gray-400" />
              </div>
            }
          >
            <Page
              pageNumber={activePage || 1}
              renderTextLayer={false}
              renderAnnotationLayer={false}
              className="bg-white"
            />
          </Document>

          {/* Overlay Bounding Box */}
          {renderBoundingBox()}
        </div>
      </div>
    </div>
  );
};

export default PdfViewer;
