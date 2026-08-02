import type { Metadata } from "next"
import { Inter, Outfit } from "next/font/google"
import "./globals.css"
import { Sidebar } from "@/components/layout/Sidebar"
import { ToastContainer } from "@/components/ui/ToastContainer"
import { QueryProvider } from "@/components/providers/QueryProvider"
import { cn } from "@/lib/utils"

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" })
const outfit = Outfit({ subsets: ["latin"], variable: "--font-outfit", weight: ["400", "500", "600", "700"] })

export const metadata: Metadata = {
  title: "Prism — Agentic Intelligence Platform",
  description: "Enterprise Tri-Modal RAG Orchestrator"
}

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className={cn("font-sans", inter.variable, outfit.variable)}>
      <body className="flex h-screen w-full bg-background overflow-hidden text-foreground">
        <QueryProvider>
          <Sidebar />
          <main className="flex-1 flex flex-col h-full overflow-hidden bg-background">
            {children}
          </main>
          <ToastContainer />
        </QueryProvider>
      </body>
    </html>
  )
}
