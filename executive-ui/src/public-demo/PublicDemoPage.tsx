import { ArrowLeft, ArrowRight, ArrowUpRight, Languages, LockKeyhole, ScanEye, ShieldCheck } from 'lucide-react'
import { DemoMode } from '../pages/DemoMode'
import { useLanguage } from '../context/LanguageContext'

export function PublicDemoPage() {
  const { t, isAr, toggleLang } = useLanguage()
  const BackArrow = isAr ? ArrowRight : ArrowLeft

  return (
    <main
      dir={isAr ? 'rtl' : 'ltr'}
      className="min-h-[100dvh] overflow-hidden bg-[#111722] text-[#edf2f5]"
    >
      <div className="pointer-events-none fixed inset-0" aria-hidden="true">
        <div className="absolute -top-48 left-[12%] h-[34rem] w-[34rem] rounded-full bg-[#83d1b1]/[0.055] blur-3xl" />
        <div className="absolute right-[-10rem] top-[28rem] h-[28rem] w-[28rem] rounded-full bg-[#7c9fc3]/[0.06] blur-3xl" />
        <div className="absolute inset-0 opacity-[0.035] [background-image:linear-gradient(rgba(237,242,245,.5)_1px,transparent_1px),linear-gradient(90deg,rgba(237,242,245,.5)_1px,transparent_1px)] [background-size:48px_48px]" />
      </div>

      <div className="relative mx-auto max-w-[1440px] px-4 pb-12 sm:px-8 lg:px-12">
        <header className="flex min-h-[76px] items-center justify-between border-b border-white/10">
          <div className="flex items-center gap-3" aria-label="THRIVE">
            <span className="relative flex h-9 w-9 items-center justify-center rounded-xl border border-[#83d1b1]/25 bg-[#83d1b1]/10">
              <span className="h-3 w-3 rotate-45 border-2 border-[#83d1b1]" />
              <span className="absolute bottom-[8px] left-[8px] h-1.5 w-1.5 rounded-full bg-[#83d1b1]" />
            </span>
            <span className="text-sm font-bold tracking-[0.2em] text-[#edf2f5]">THRIVE</span>
            <span className="hidden border-l border-white/15 pl-3 text-[11px] tracking-wide text-[#9ba9b5] sm:block">
              {t('WORKFORCE INTELLIGENCE', 'ذكاء القوى العاملة')}
            </span>
          </div>

          <div className="flex items-center gap-2 sm:gap-4">
            <button
              type="button"
              onClick={toggleLang}
              className="inline-flex min-h-10 items-center gap-2 rounded-lg px-3 text-xs font-semibold text-[#b4c1cb] transition-colors hover:bg-white/[0.06] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#83d1b1]"
              aria-label={t('Switch language to Arabic', 'التبديل إلى اللغة الإنجليزية')}
            >
              <Languages size={15} />
              {t('العربية', 'English')}
            </button>
            <a
              href="/"
              className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-white/15 px-3.5 text-xs font-semibold text-[#dce5e9] transition-colors hover:border-[#83d1b1]/50 hover:bg-[#83d1b1]/[0.07] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#83d1b1] sm:px-4"
            >
              <BackArrow size={14} />
              <span>{t('Return to sign in', 'العودة إلى تسجيل الدخول')}</span>
            </a>
          </div>
        </header>

        <section className="grid gap-8 pb-8 pt-9 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end lg:gap-12 lg:pb-10 lg:pt-14">
          <div className={isAr ? 'text-right' : ''}>
            <div className={`mb-5 inline-flex items-center gap-2 rounded-full border border-[#83d1b1]/20 bg-[#83d1b1]/[0.07] px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-[#9bddc2] ${isAr ? 'tracking-normal' : ''}`}>
              <span className="h-1.5 w-1.5 rounded-full bg-[#83d1b1]" />
              {t('Public guided preview', 'عرض توضيحي عام وموجّه')}
            </div>
            <h1 className="max-w-3xl text-3xl font-bold leading-[1.15] tracking-[-0.035em] text-[#f0f4f4] sm:text-4xl lg:text-[3.35rem]">
              {t('See the workforce intelligence experience.', 'تعرّف على تجربة ذكاء القوى العاملة.')}
            </h1>
            <p className="mt-4 max-w-2xl text-sm leading-7 text-[#a6b3be] sm:text-base">
              {t(
                'A guided walkthrough of THRIVE using only its built-in synthetic sample. Explore the scripted journey without connecting a file or organization.',
                'جولة إرشادية في THRIVE باستخدام العينة الاصطناعية المضمّنة فقط. استكشف المسار التوضيحي دون ربط أي ملف أو مؤسسة.'
              )}
            </p>
          </div>

          <div className="hidden min-w-[220px] border-s border-white/10 ps-6 lg:block">
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#788894]">
              {t('Preview access', 'الوصول إلى المعاينة')}
            </p>
            <div className="mt-3 flex items-center gap-2 text-sm font-semibold text-[#d8e2e5]">
              <LockKeyhole size={15} className="text-[#83d1b1]" />
              {t('Read-only · no account', 'للقراءة فقط · دون حساب')}
            </div>
            <p className="mt-2 text-xs leading-5 text-[#84939f]">
              {t('No upload, analysis, or saved changes.', 'لا تحميل أو تحليل أو تغييرات محفوظة.')}
            </p>
          </div>
        </section>

        <section
          aria-labelledby="synthetic-notice-title"
          className="relative mb-8 overflow-hidden rounded-2xl border border-[#d7b66c]/25 bg-[#d7b66c]/[0.07] p-4 sm:p-5"
        >
          <div className="absolute inset-y-0 start-0 w-1 bg-[#d7b66c]" />
          <div className="flex items-start gap-3 sm:gap-4">
            <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-[#d7b66c]/20 bg-[#d7b66c]/10 text-[#e4c984]">
              <ScanEye size={17} />
            </div>
            <div className={isAr ? 'text-right' : ''}>
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <h2 id="synthetic-notice-title" className="text-sm font-bold text-[#f0dfb0]">
                  {t('Scripted synthetic sample — not real-world evidence', 'عينة اصطناعية مكتوبة مسبقاً — ليست دليلاً من الواقع')}
                </h2>
                <span className="rounded-full border border-[#d7b66c]/25 px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.13em] text-[#d7b66c]">
                  {t('Sample only', 'عينة فقط')}
                </span>
              </div>
              <p className="mt-1.5 max-w-5xl text-xs leading-6 text-[#c2b99f] sm:text-[13px]">
                {t(
                  'Every company, sector reference, number, score, finding, and report shown below is scripted synthetic sample content from local demo fixtures. Nothing here is observed sector data, a benchmark, a live result, or analysis of an uploaded file. This preview is read-only and does not accept uploads or save changes.',
                  'كل شركة أو إشارة إلى قطاع أو رقم أو درجة أو نتيجة أو تقرير معروض أدناه هو محتوى عينة اصطناعية مكتوب مسبقاً من بيانات العرض المحلية. لا شيء هنا بيانات قطاع مرصودة أو معيار مقارنة أو نتيجة مباشرة أو تحليل لملف مرفوع. هذه المعاينة للقراءة فقط ولا تقبل تحميل الملفات أو حفظ التغييرات.'
                )}
              </p>
            </div>
          </div>
        </section>

        <section aria-label={t('Guided synthetic demonstration', 'عرض اصطناعي إرشادي')} className="relative">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2 px-1">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#91a0aa]">
              <ShieldCheck size={14} className="text-[#83d1b1]" />
              {t('Guided demo · local fixtures only', 'عرض إرشادي · بيانات محلية فقط')}
            </div>
            <span className="text-[10px] text-[#788894]">
              {t('No live data connected', 'لا توجد بيانات مباشرة متصلة')}
            </span>
          </div>

          <div className="rounded-2xl border border-white/10 bg-[#18222e]/90 p-3 shadow-[0_24px_80px_rgba(0,0,0,0.22)] sm:p-6 lg:p-8">
            <DemoMode />
          </div>
        </section>

        <footer className="mt-8 flex flex-col gap-3 border-t border-white/10 pt-5 text-[11px] leading-5 text-[#7f8f9a] sm:flex-row sm:items-center sm:justify-between">
          <p className={isAr ? 'text-right' : ''}>
            {t(
              'Illustrative walkthrough only. Do not use these sample outputs for decisions.',
              'جولة توضيحية فقط. لا تستخدم مخرجات العينة هذه لاتخاذ القرارات.'
            )}
          </p>
          <a
            href="/"
            className="inline-flex w-fit items-center gap-1.5 font-semibold text-[#a9d8c5] transition-colors hover:text-[#d1efdf] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#83d1b1]"
          >
            {t('Return to sign in', 'العودة إلى تسجيل الدخول')}
            <ArrowUpRight size={13} className={isAr ? '-rotate-90' : ''} />
          </a>
        </footer>
      </div>
    </main>
  )
}

export default PublicDemoPage
