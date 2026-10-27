import { type FormEvent, type ReactNode, useEffect, useState } from 'react'
import { KeyRound, Languages, LogIn, ShieldCheck } from 'lucide-react'
import {
  type AuthUser,
  clearTokens,
  getAccessToken,
  saveTokens,
} from './authClient'
import { BrandLogo } from '../layout/BrandLogo'
import { useLanguage } from '../context/LanguageContext'

interface AuthGateProps {
  children: (session: { user: AuthUser; signOut: () => Promise<void> }) => ReactNode
}

interface LoginResponse {
  access_token: string
  refresh_token: string
  user: AuthUser
}

const ANALYSIS_ROLES = new Set([
  'chro',
  'hr_manager',
  'hr_analyst',
  'system_admin',
])

async function responseMessage(response: Response) {
  try {
    const body = await response.json()
    return body.detail || 'Request could not be completed.'
  } catch {
    return 'Request could not be completed.'
  }
}

export function AuthGate({ children }: AuthGateProps) {
  const { t } = useLanguage()
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let active = true
    const token = getAccessToken()
    if (!token) {
      setLoading(false)
    } else {
      fetch('/api/auth/me')
        .then(async response => {
          if (!response.ok) {
            clearTokens()
            return null
          }
          return response.json() as Promise<AuthUser>
        })
        .then(profile => {
          if (active) setUser(profile)
        })
        .catch(() => {
          clearTokens()
          if (active) setUser(null)
        })
        .finally(() => {
          if (active) setLoading(false)
        })
    }

    const onExpired = () => {
      clearTokens()
      setUser(null)
      setError('Your session ended. Sign in again to continue.')
    }
    window.addEventListener('awi:session-expired', onExpired)
    return () => {
      active = false
      window.removeEventListener('awi:session-expired', onExpired)
    }
  }, [])

  const signOut = async () => {
    try {
      if (getAccessToken()) await fetch('/api/auth/logout', { method: 'POST' })
    } finally {
      clearTokens()
      setUser(null)
      setPassword('')
      setCurrentPassword('')
      setNewPassword('')
      setError('')
    }
  }

  const handleLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (!response.ok) throw new Error(await responseMessage(response))
      const result = (await response.json()) as LoginResponse
      saveTokens(result.access_token, result.refresh_token)
      setUser(result.user)
      setPassword('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.')
    } finally {
      setBusy(false)
    }
  }

  const handlePasswordChange = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const response = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      })
      if (!response.ok) throw new Error(await responseMessage(response))
      const profileResponse = await fetch('/api/auth/me')
      if (!profileResponse.ok) throw new Error('Password changed, but the profile could not be reloaded.')
      setUser((await profileResponse.json()) as AuthUser)
      setCurrentPassword('')
      setNewPassword('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Password could not be changed.')
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950">
        <div className="text-sm text-slate-500">{t('Checking your sign-in…', 'جارٍ التحقق من تسجيل الدخول…')}</div>
      </div>
    )
  }

  if (!user) {
    return (
      <AuthPanel
        icon={<LogIn size={20} />}
        title={t('Sign in to THRIVE', 'تسجيل الدخول إلى ثرايف')}
        subtitle={t('Use your organization account to access company analytics.', 'استخدم حساب مؤسستك للوصول إلى تحليلات الشركة.')}
      >
        <form onSubmit={handleLogin} className="space-y-4">
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
            {t('Username', 'اسم المستخدم')}
            <input
              autoComplete="username"
              dir="ltr"
              required
              value={username}
              onChange={event => setUsername(event.target.value)}
              className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
            />
          </label>
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
            {t('Password', 'كلمة المرور')}
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={event => setPassword(event.target.value)}
              className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
            />
          </label>
          <ErrorMessage>{error}</ErrorMessage>
          <button disabled={busy} className="auth-primary-button">
            {busy ? t('Signing in…', 'جارٍ تسجيل الدخول…') : t('Sign in', 'تسجيل الدخول')}
          </button>
        </form>
        <div className="mt-5 border-t border-slate-200 pt-4 text-center dark:border-slate-700">
          <a href="/demo" className="text-sm font-medium text-blue-700 hover:text-blue-800 dark:text-blue-300 dark:hover:text-blue-200">
            {t('Explore the public synthetic-data demo', 'استكشف العرض العام بالبيانات الاصطناعية')}
          </a>
        </div>
      </AuthPanel>
    )
  }

  if (user.must_change_password) {
    return (
      <AuthPanel
        icon={<KeyRound size={20} />}
        title={t('Change your password', 'تغيير كلمة المرور')}
        subtitle={t('Set a new password before viewing any company information.', 'عيّن كلمة مرور جديدة قبل عرض أي معلومات عن الشركة.')}
      >
        <form onSubmit={handlePasswordChange} className="space-y-4">
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
            {t('Current password', 'كلمة المرور الحالية')}
            <input
              type="password"
              autoComplete="current-password"
              required
              value={currentPassword}
              onChange={event => setCurrentPassword(event.target.value)}
              className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
            />
          </label>
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
            {t('New password', 'كلمة المرور الجديدة')}
            <input
              type="password"
              autoComplete="new-password"
              minLength={12}
              required
              value={newPassword}
              onChange={event => setNewPassword(event.target.value)}
              className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
            />
          </label>
          <p className="text-xs text-slate-500">{t('Use at least 12 characters and include a mix of character types.', 'استخدم 12 حرفاً على الأقل مع مزيج من أنواع الأحرف.')}</p>
          <ErrorMessage>{error}</ErrorMessage>
          <button disabled={busy} className="auth-primary-button">
            {busy ? t('Saving…', 'جارٍ الحفظ…') : t('Save new password', 'حفظ كلمة المرور الجديدة')}
          </button>
          <button type="button" onClick={signOut} className="auth-secondary-button">
            {t('Sign out', 'تسجيل الخروج')}
          </button>
        </form>
      </AuthPanel>
    )
  }

  if (!ANALYSIS_ROLES.has(user.role)) {
    return (
      <AuthPanel
        icon={<ShieldCheck size={20} />}
        title={t('Analysis access is restricted', 'الوصول إلى التحليلات مقيّد')}
        subtitle={t(`Your ${user.role.replace(/_/g, ' ')} role does not include access to uploaded company data. Contact your administrator if you need analysis access.`, 'لا يشمل دورك صلاحية الوصول إلى بيانات الشركة المرفوعة. تواصل مع مسؤول النظام إذا كنت بحاجة إلى صلاحية التحليل.')}
      >
        <button onClick={signOut} className="auth-secondary-button">{t('Sign out', 'تسجيل الخروج')}</button>
      </AuthPanel>
    )
  }

  return children({ user, signOut })
}

function ErrorMessage({ children }: { children: string }) {
  const { t } = useLanguage()
  if (!children) return null
  const messages: Record<string, string> = {
    'Your session ended. Sign in again to continue.': 'انتهت جلستك. سجّل الدخول مجدداً للمتابعة.',
    'Request could not be completed.': 'تعذر إكمال الطلب.',
    'Sign-in failed.': 'تعذر تسجيل الدخول.',
    'Password could not be changed.': 'تعذر تغيير كلمة المرور.',
    'Password changed, but the profile could not be reloaded.': 'تغيّرت كلمة المرور، لكن تعذر إعادة تحميل الملف الشخصي.',
  }
  return (
    <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
      {t(children, messages[children] ?? children)}
    </p>
  )
}

function AuthPanel({
  icon,
  title,
  subtitle,
  children,
}: {
  icon: ReactNode
  title: string
  subtitle: string
  children: ReactNode
}) {
  const { lang, toggleLang, t } = useLanguage()
  return (
    <main className="min-h-[100dvh] flex items-center justify-center bg-[#f4f6f8] px-4 py-10 dark:bg-[#171a34]">
      <section className="auth-panel w-full max-w-md rounded-2xl p-6 sm:p-8">
        <div className="mb-8 border-b border-slate-200 dark:border-slate-700 pb-6">
          <div className="flex items-center justify-between gap-3">
            <BrandLogo className="h-12 w-[190px] sm:w-[218px]" />
            <button type="button" onClick={toggleLang} title={t('Switch to Arabic', 'التبديل إلى الإنجليزية')} className="flex shrink-0 items-center gap-1 rounded-lg px-2 py-2 text-xs text-blue-700 hover:bg-blue-50 dark:text-blue-200 dark:hover:bg-slate-800"><Languages size={15} />{lang === 'en' ? 'عربي' : 'EN'}</button>
          </div>
          <p className="mt-3 text-xs tracking-[.18em] text-slate-500 dark:text-slate-400">{t('BUSINESS SOLUTIONS', 'حلول الأعمال')}</p>
        </div>
        <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl bg-[#2e3070] text-white">
          {icon}
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">{title}</h1>
        <p className="mt-2 mb-6 text-sm leading-6 text-slate-600 dark:text-slate-400">{subtitle}</p>
        {children}
      </section>
    </main>
  )
}
