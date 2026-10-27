import { useState, Suspense, lazy } from 'react'
import { Languages } from 'lucide-react'
import { ThemeProvider } from './context/ThemeContext'
import { LanguageProvider, useLanguage } from './context/LanguageContext'
import { AppLayout } from './layout/AppLayout'
import { BrandLogo } from './layout/BrandLogo'
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
import { DemoMode } from './pages/DemoMode'

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
  if (path === '/demo') return <PublicDemo />

  return (
    <AuthGate>
      {({ user, signOut }) => <AppContent user={user} onSignOut={signOut} />}
    </AuthGate>
  )
}

function PublicDemo() {
  const { t, lang, toggleLang } = useLanguage()

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <header className="border-b border-slate-200 bg-white/90 dark:border-slate-800 dark:bg-slate-900/90">
        <div className="mx-auto flex max-w-screen-2xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <BrandLogo className="h-9 w-[165px] sm:w-[190px]" />
          <div className="flex items-center gap-2">
            <span className="hidden rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800 dark:bg-amber-950/40 dark:text-amber-300 sm:inline-flex">
              {t('Synthetic-data demo', 'عرض ببيانات اصطناعية')}
            </span>
            <button
              type="button"
              onClick={toggleLang}
              aria-label={t('Switch language', 'تغيير اللغة')}
              className="flex items-center gap-1 rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <Languages size={16} />
              {lang === 'en' ? 'عربي' : 'EN'}
            </button>
            <a href="/" className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800">
              {t('Sign in', 'تسجيل الدخول')}
            </a>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-screen-2xl px-4 py-6 sm:px-6 md:py-8">
        <div role="note" className="mb-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200">
          {t(
            'Preview only: this guided experience uses fixed synthetic figures. It does not accept real uploads or access company datasets.',
            'معاينة فقط: يستخدم هذا العرض أرقاماً اصطناعية ثابتة. لا يقبل ملفات حقيقية ولا يصل إلى بيانات الشركة.'
          )}
        </div>
        <DemoMode />
      </main>
    </div>
  )
}
