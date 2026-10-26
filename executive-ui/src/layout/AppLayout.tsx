import { useState } from 'react'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'
import type { NavPage } from '../types'
import type { AuthUser } from '../auth/authClient'

interface AppLayoutProps {
  activePage: NavPage
  onNavigate: (page: NavPage) => void
  children: React.ReactNode
  companyName: string
  companyNameAr: string
  user: AuthUser
  onSignOut: () => Promise<void>
}

export function AppLayout({
  activePage,
  onNavigate,
  children,
  companyName,
  companyNameAr,
  user,
  onSignOut,
}: AppLayoutProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div className="app-shell flex overflow-hidden">
      {mobileOpen && <button className="sidebar-scrim md:hidden" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
      <Sidebar
        activePage={activePage}
        onNavigate={(page) => { onNavigate(page); setMobileOpen(false) }}
        collapsed={sidebarCollapsed && !mobileOpen}
        mobileOpen={mobileOpen}
      />

      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <TopBar
          onToggleSidebar={() => {
            if (window.matchMedia('(max-width: 767px)').matches) setMobileOpen(value => !value)
            else setSidebarCollapsed(c => !c)
          }}
          companyName={companyName}
          companyNameAr={companyNameAr}
          user={user}
          onSignOut={onSignOut}
        />

        {/* Phase 11B: ambient radial-glow background — the flat navy-900
            everywhere read as "same layout, new colors," per the honest
            self-critique in PHASE_11B_VISUAL_QA_AND_POLISH_REPORT.md.
            A fixed, low-opacity gold/blue glow anchored near the top gives
            the page depth and atmosphere (the Linear/Stripe convention)
            without competing with content — it sits behind everything via
            -z-10 and never intercepts clicks. */}
        <main className="relative flex-1 min-w-0 overflow-y-auto ambient-glow">
          <div className="p-4 sm:p-6 md:p-8 max-w-screen-2xl mx-auto animate-fade-in">
            {children}
          </div>
        </main>
      </div>
    </div>
  )
}
