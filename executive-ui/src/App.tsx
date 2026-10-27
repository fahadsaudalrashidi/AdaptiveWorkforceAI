import { useState, Suspense, lazy } from 'react'
import { ThemeProvider } from './context/ThemeContext'
import { LanguageProvider } from './context/LanguageContext'
import { AppLayout } from './layout/AppLayout'
import { PageErrorBoundary } from './components/shared/PageErrorBoundary'
import { EnterpriseOverview } from './pages/EnterpriseOverview'
import { TrustPanel } from './pages/TrustPanel'
import { OvertimeCostIntelligence } from './pages/OvertimeCostIntelligence'
import { PayrollMovementsTracker } from './pages/PayrollMovementsTracker'
import { ExitInterviewIntelligence } from './pages/ExitInterviewIntelligence'
import { RecruitmentPipelineTracker } from './pages/RecruitmentPipelineTracker'
import { FairnessAuditTracker } from './pages/FairnessAuditTracker'
import { PayEquityTracker } from './pages/PayEquityTracker'
import { NitaqatComplianceTracker } from './pages/NitaqatComplianceTracker'
import { SuccessionReadinessTracker } from './pages/SuccessionReadinessTracker'
import { ContractExpiryTracker } from './pages/ContractExpiryTracker'
import { JobPatternGroupingTracker } from './pages/JobPatternGroupingTracker'
import { SaudiLaborLawCalculators } from './pages/SaudiLaborLawCalculators'
import { FinancialIntelligence } from './pages/FinancialIntelligence'
import { InventoryIntelligence } from './pages/InventoryIntelligence'
import { ProcurementIntelligence } from './pages/ProcurementIntelligence'
import { LogisticsIntelligence } from './pages/LogisticsIntelligence'
import { OperationsIntelligence } from './pages/OperationsIntelligence'
import { HRLetterGenerator } from './pages/HRLetterGenerator'
import { GosiCalculator } from './pages/GosiCalculator'
import { PayrollBudgetPlanner } from './pages/PayrollBudgetPlanner'
import { ZakatEstimator } from './pages/ZakatEstimator'
import type { NavPage } from './types'
import { AuthGate } from './auth/AuthGate'
import type { AuthUser } from './auth/authClient'
import { PublicDemoPage } from './public-demo/PublicDemoPage'

// These substantial analytical screens load only when opened. The existing
// Suspense/PageLoader boundary handles loading and the page boundary errors.
const AIBusinessAnalyst = lazy(() => import('./pages/AIBusinessAnalyst').then(module => ({ default: module.AIBusinessAnalyst })))
const AccountingIntelligence = lazy(() => import('./pages/AccountingIntelligence').then(module => ({ default: module.AccountingIntelligence })))
const DataHub = lazy(() => import('./pages/DataHub').then(module => ({ default: module.DataHub })))

function PageLoader() {
  return (
    <div className="flex items-center justify-center min-h-[400px]">
      <div className="flex flex-col items-center gap-3 text-gray-500 dark:text-gray-400">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        <span className="text-sm">Loading…</span>
      </div>
    </div>
  )
}

function AppContent({ user, onSignOut }: { user: AuthUser; onSignOut: () => Promise<void> }) {
  const [activePage, setActivePage] = useState<NavPage>('overview')

  const renderPage = () => {
    switch (activePage) {
      case 'overview':
        return <EnterpriseOverview onNavigate={setActivePage} />
      case 'trust':
        return <TrustPanel />
      case 'overtime':
        return <OvertimeCostIntelligence />
      case 'payroll':
        return <PayrollMovementsTracker />
      case 'exitinterview':
        return <ExitInterviewIntelligence />
      case 'recruitment':
        return <RecruitmentPipelineTracker />
      case 'fairness':
        return <FairnessAuditTracker />
      case 'payequity':
        return <PayEquityTracker />
      case 'nitaqat':
        return <NitaqatComplianceTracker />
      case 'succession':
        return <SuccessionReadinessTracker />
      case 'contractexpiry':
        return <ContractExpiryTracker />
      case 'jobpatterns':
        return <JobPatternGroupingTracker />
      case 'laborlaw':
        return <SaudiLaborLawCalculators />
      case 'hrletters':
        return <HRLetterGenerator />
      case 'gosi':
        return <GosiCalculator />
      case 'payrollbudget':
        return <PayrollBudgetPlanner />
      case 'zakat':
        return <ZakatEstimator />
      case 'financialintelligence':
        return <FinancialIntelligence />
      case 'accountingintelligence':
        return <AccountingIntelligence />
      case 'inventoryintelligence':
        return <InventoryIntelligence />
      case 'procurementintelligence':
        return <ProcurementIntelligence />
      case 'logisticsintelligence':
        return <LogisticsIntelligence />
      case 'operationsintelligence':
        return <OperationsIntelligence />
      case 'aibusinessanalyst':
        return <AIBusinessAnalyst />
      case 'datahub':
        return <DataHub />
    }
  }

  return (
    <AppLayout
      activePage={activePage}
      onNavigate={setActivePage}
      companyName="THRIVE Business Solutions"
      companyNameAr="ثرايف لحلول الأعمال"
      user={user}
      onSignOut={onSignOut}
    >
      <PageErrorBoundary onReturnToUpload={() => setActivePage('overview')} pageName={activePage}>
        <Suspense fallback={<PageLoader />}>
          {renderPage()}
        </Suspense>
      </PageErrorBoundary>
    </AppLayout>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <LanguageProvider>
        <AppRoute />
      </LanguageProvider>
    </ThemeProvider>
  )
}

function AppRoute() {
  const path = window.location.pathname.replace(/\/+$/, '') || '/'
  if (path === '/demo' || path.startsWith('/demo/')) return <PublicDemoPage />

  return (
    <AuthGate>
      {({ user, signOut }) => <AppContent user={user} onSignOut={signOut} />}
    </AuthGate>
  )
}
