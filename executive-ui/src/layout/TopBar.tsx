import { Sun, Moon, Languages, Menu, ShieldCheck, Bell, LogOut } from 'lucide-react'
import { useTheme } from '../context/ThemeContext'
import { useLanguage } from '../context/LanguageContext'
import type { AuthUser } from '../auth/authClient'
import { BrandLogo } from './BrandLogo'

interface TopBarProps {
  onToggleSidebar: () => void
  companyName: string
  companyNameAr: string
  user: AuthUser
  onSignOut: () => Promise<void>
}

export function TopBar({ onToggleSidebar, companyName, companyNameAr, user, onSignOut }: TopBarProps) {
  const { theme, toggleTheme } = useTheme()
  const { lang, toggleLang, t, isAr } = useLanguage()

  return (
    <header className="h-16 flex items-center justify-between gap-2 px-3 sm:px-5 bg-white dark:bg-[#202447] border-b border-slate-200 dark:border-[#3b4264] flex-shrink-0">
      {/* Left: menu toggle + breadcrumb */}
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleSidebar}
          className="btn-ghost p-2 rounded-lg"
          aria-label={t('Toggle sidebar', 'فتح القائمة الجانبية')}
        >
          <Menu size={18} />
        </button>

        <BrandLogo className="h-8 w-[108px] sm:w-[128px]" />
        <div className="hidden lg:flex items-center gap-2">
          <span className="text-slate-400 dark:text-slate-500 text-sm">
            {isAr ? companyNameAr : companyName}
          </span>
          <span className="text-slate-300 dark:text-slate-700">/</span>
          <span className="text-slate-700 dark:text-slate-300 text-sm font-medium">
            {t('THRIVE Business Solutions', 'ثرايف لحلول الأعمال')}
          </span>
        </div>
      </div>

      {/* Center: governance status pill */}
        <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800/50 rounded-full">
        <ShieldCheck size={14} className="text-emerald-500" />
        <span className="text-xs font-medium text-emerald-700 dark:text-emerald-400">
          {t('Governance Active', 'الحوكمة نشطة')}
        </span>
        <span className="text-xs text-emerald-500 dark:text-emerald-500/70">•</span>
        <span className="text-xs text-emerald-600 dark:text-emerald-500/70">
          {t('PDPL Compliant', 'متوافق مع لوائح البيانات')}
        </span>
      </div>

      {/* Right: controls */}
      <div className="flex items-center gap-2">
        {/* Language toggle */}
        <button
          onClick={toggleLang}
          className="btn-ghost flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium"
          title={t('Switch to Arabic', 'التبديل إلى الإنجليزية')}
        >
          <Languages size={15} />
          <span>{lang === 'en' ? 'عربي' : 'EN'}</span>
        </button>

        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          className="btn-ghost p-2 rounded-lg"
          aria-label={theme === 'dark' ? t('Switch to light mode', 'التبديل إلى الوضع الفاتح') : t('Switch to dark mode', 'التبديل إلى الوضع الداكن')}
        >
          {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
        </button>

        <div className="hidden sm:block max-w-36 truncate text-xs text-slate-500 dark:text-slate-400" title={`${user.display_name} · ${user.role}`}>
          {user.display_name}
        </div>
        <button
          onClick={() => void onSignOut()}
          className="btn-ghost flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium"
          aria-label={t('Sign out', 'تسجيل الخروج')}
        >
          <LogOut size={15} />
          <span className="hidden md:inline">{t('Sign out', 'تسجيل الخروج')}</span>
        </button>

        {/* Notifications (placeholder) */}
        <button className="btn-ghost p-2 rounded-lg relative" aria-label={t('Notifications', 'الإشعارات')}>
          <Bell size={17} />
          <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-amber-400 rounded-full" />
        </button>

        {/* Tenant badge */}
        <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-slate-100 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
          <div className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse-slow" />
          <span className="text-xs text-slate-600 dark:text-slate-400 font-medium">
            {t('THRIVE Platform', 'منصة ثرايف')}
          </span>
        </div>
      </div>
    </header>
  )
}
