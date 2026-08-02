"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  MessageSquare,
  LayoutDashboard,
  AlertCircle,
  HardDrive,
  Layers,
  Cpu
} from "lucide-react"
import clsx from "clsx"

const navItems = [
  { href: "/chat",      icon: MessageSquare,    label: "Chat & Q&A" },
  { href: "/agents",    icon: Cpu,              label: "Work Agents" },
  { href: "/documents", icon: HardDrive,        label: "Documents" },
  { href: "/hitl",      icon: AlertCircle,      label: "Human Loop" },
  { href: "/dlq",       icon: Layers,           label: "Dead Letter" },
]

export const Sidebar = () => {
  const pathname = usePathname()

  return (
    <aside className="w-56 h-full flex flex-col bg-surface border-r border-border shrink-0">
      {/* Brand */}
      <div className="h-16 flex items-center gap-3 px-5 border-b border-border shrink-0">
        <div className="w-8 h-8 rounded-lg bg-brand flex items-center justify-center shrink-0">
          <span className="text-white font-bold text-sm tracking-tight">PR</span>
        </div>
        <div className="leading-tight">
          <p className="text-[13px] font-bold text-foreground tracking-tight">Prism</p>
          <p className="text-[10px] text-muted">Agentic Platform</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 flex flex-col gap-1 px-3 py-4 overflow-y-auto">
        <p className="text-[10px] font-semibold text-muted uppercase tracking-widest px-2 mb-2">
          Workspace
        </p>
        {navItems.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(item.href + "/")
          return (
            <Link
              key={item.href}
              href={item.href}
              className={clsx(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 group relative",
                isActive
                  ? "bg-brandLight text-brand shadow-sm"
                  : "text-muted hover:bg-gray-50 hover:text-foreground"
              )}
            >
              {isActive && (
                <span className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 bg-brand rounded-r-full" />
              )}
              <item.icon
                size={17}
                strokeWidth={isActive ? 2.5 : 2}
                className={isActive ? "text-brand" : "text-muted group-hover:text-foreground transition-colors"}
              />
              <span className={isActive ? "text-brand" : ""}>{item.label}</span>
            </Link>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="px-4 py-4 border-t border-border">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-full bg-brand/10 flex items-center justify-center">
            <LayoutDashboard size={12} className="text-brand" />
          </div>
          <span className="text-[11px] text-muted">v1.0 · All systems nominal</span>
        </div>
      </div>
    </aside>
  )
}
