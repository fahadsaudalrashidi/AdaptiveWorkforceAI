import { useEffect, useState } from 'react'
import { CheckCircle2, ChevronDown, ChevronUp, ExternalLink, Plus, Trash2 } from 'lucide-react'
import { useLanguage } from '../../context/LanguageContext'

interface ReviewRow { page: number; values: string[]; verified: boolean }
export interface ReviewedTable {
  source_id: string
  columns: string[]
  rows: ReviewRow[]
  confirmed_headers: boolean
  scope: 'reviewed_rows_only'
}
export interface ReviewDetail {
  source_id?: string
  source_filename?: string
  review_allowed?: boolean
  review_preview?: Array<{ page: number; text: string }>
  review_candidate?: { columns: string[]; rows: Array<{ page: number; values: string[] }> }
  pdf_extraction?: { requires_numeric_review: boolean; pages: Array<{ page: number }> }
}
export interface ReviewSource extends ReviewDetail {
  source_id: string
  source_filename: string
  pages: number[]
}

export function collectReviewSources(details: ReviewDetail[]): ReviewSource[] {
  const sources = new Map<string, ReviewSource>()
  for (const detail of details) {
    if (!detail.source_id || !detail.source_filename || !detail.review_allowed) continue
    const previous = sources.get(detail.source_id)
    sources.set(detail.source_id, {
      ...previous, ...detail, source_id: detail.source_id, source_filename: detail.source_filename,
      pages: detail.pdf_extraction?.pages.map((page) => page.page) ?? previous?.pages ?? [],
      review_preview: detail.review_preview ?? previous?.review_preview,
      review_candidate: detail.review_candidate ?? previous?.review_candidate,
    })
  }
  return [...sources.values()]
}

export function OcrFigureReview({ source, file, originalQuestion, onSubmit }: {
  source: ReviewSource
  file?: File
  originalQuestion: string
  onSubmit: (table: ReviewedTable, question: string) => Promise<void>
}) {
  const { t } = useLanguage()
  const [open, setOpen] = useState(false)
  const [columns, setColumns] = useState(source.review_candidate?.columns ?? ['Metric', 'Value'])
  const [rows, setRows] = useState<ReviewRow[]>(() => source.review_candidate?.rows.map((row) => ({ ...row, verified: false })) ?? [
    { page: source.pages[0] ?? 1, values: ['', ''], verified: false },
  ])
  const [page, setPage] = useState(source.pages[0] ?? 1)
  const [confirmed, setConfirmed] = useState(false)
  const [question, setQuestion] = useState(originalQuestion)
  const [url, setUrl] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!file) return
    const objectUrl = URL.createObjectURL(file)
    setUrl(objectUrl)
    return () => URL.revokeObjectURL(objectUrl)
  }, [file])
  const invalidate = () => { setConfirmed(false); setRows((current) => current.map((row) => ({ ...row, verified: false }))) }
  const changeCell = (rowIndex: number, columnIndex: number, value: string) => {
    setRows((current) => current.map((row, index) => index !== rowIndex ? row : {
      ...row, verified: false, values: row.values.map((cell, col) => col === columnIndex ? value : cell),
    }))
    setConfirmed(false)
  }
  const valid = Boolean(file && confirmed && question.trim() && rows.length &&
    rows.every((row) => row.verified && row.values.some((value) => value.trim())) &&
    columns.every((column) => column.trim()) &&
    new Set(columns.map((column) => column.trim().toLowerCase())).size === columns.length)
  const submit = async () => {
    if (!valid) return
    setSending(true); setError('')
    try {
      await onSubmit({ source_id: source.source_id, columns, rows, confirmed_headers: true, scope: 'reviewed_rows_only' }, question)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally { setSending(false) }
  }
  const input = 'w-full min-w-[100px] rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-800 focus:ring-2 focus:ring-blue-400 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100'
  return (
    <section className="card my-3 overflow-hidden border-amber-300 p-4 dark:border-amber-700" aria-label={t('Review scanned figures', 'مراجعة الأرقام الممسوحة')}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center justify-between gap-3 text-start">
        <span className="flex items-center gap-2 font-semibold text-blue-800 dark:text-blue-200"><CheckCircle2 size={18} />{t('Review and correct scanned figures', 'مراجعة الأرقام الممسوحة وتصحيحها')}</span>
        {open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
      </button>
      <p className="mt-2 text-xs leading-relaxed text-slate-500 dark:text-slate-400">
        {source.source_filename} — {t('Check each included cell against its original page. Only the rows you confirm form a new analysis source; the original OCR is never marked verified.', 'تحقق من كل خلية مُدرجة مقابل صفحتها الأصلية. تصبح الصفوف المؤكدة فقط مصدراً جديداً للتحليل، ولا تُعتبر نتائج OCR الأصلية موثقة.')}
      </p>
      {open && (
        <div className="mt-4 space-y-4">
          {!file && <p role="alert" className="text-sm text-red-600">{t('The original file is no longer available. Attach the PDF and analyze it again before review.', 'الملف الأصلي غير متاح. أرفق PDF وحلّله مجدداً قبل المراجعة.')}</p>}
          <div className="grid gap-4 xl:grid-cols-2">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <label>{t('Original page', 'الصفحة الأصلية')} <select aria-label={t('Original page', 'الصفحة الأصلية')} className="rounded border bg-white px-2 py-1 dark:bg-slate-800" value={page} onChange={(event) => setPage(Number(event.target.value))}>{source.pages.map((number) => <option key={number}>{number}</option>)}</select></label>
                {url && <a className="flex items-center gap-1 text-blue-600 dark:text-blue-300" href={`${url}#page=${page}`} target="_blank" rel="noreferrer">{t('Open original PDF', 'فتح PDF الأصلي')}<ExternalLink size={12} /></a>}
              </div>
              {url && <iframe title={t('Original source PDF', 'ملف PDF الأصلي')} src={`${url}#page=${page}`} className="h-80 w-full rounded-lg border bg-white" />}
              <details className="rounded-lg bg-slate-50 p-3 text-xs dark:bg-slate-900">
                <summary className="cursor-pointer font-semibold">{t('Unverified extracted text', 'النص المستخرج غير الموثق')}</summary>
                <p className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap" dir="auto">{source.review_preview?.find((passage) => passage.page === page)?.text ?? t('Use the original page to enter or correct the figures.', 'استخدم الصفحة الأصلية لإدخال الأرقام أو تصحيحها.')}</p>
              </details>
            </div>
            <div className="space-y-3">
              <p className="text-xs font-semibold text-slate-600 dark:text-slate-300">{t('Reviewed table · every included row requires confirmation', 'الجدول المُراجع · يتطلب كل صف مُدرج تأكيداً')}</p>
              <div className="max-h-96 overflow-auto rounded-lg border border-slate-200 dark:border-slate-700">
                <table className="w-full text-start text-xs">
                  <thead><tr>
                    {columns.map((column, index) => <th key={index} className="p-2"><input aria-label={`${t('Column heading', 'عنوان العمود')} ${index + 1}`} className={input} maxLength={100} value={column} onChange={(event) => { setColumns((current) => current.map((name, col) => col === index ? event.target.value : name)); invalidate() }} /></th>)}
                    <th className="p-2">{t('Page', 'الصفحة')}</th><th className="p-2">{t('Checked', 'تم التحقق')}</th><th />
                  </tr></thead>
                  <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>
                    {row.values.map((value, colIndex) => <td key={colIndex} className="p-2"><input dir="auto" aria-label={`${columns[colIndex]} ${t('row', 'صف')} ${rowIndex + 1}`} className={input} value={value} maxLength={500} onChange={(event) => changeCell(rowIndex, colIndex, event.target.value)} /></td>)}
                    <td className="p-2"><select aria-label={`${t('Source page for row', 'الصفحة المصدر للصف')} ${rowIndex + 1}`} className="rounded bg-white p-1 dark:bg-slate-800" value={row.page} onChange={(event) => { setRows((current) => current.map((item, index) => index === rowIndex ? { ...item, page: Number(event.target.value), verified: false } : item)); setConfirmed(false) }}>{source.pages.map((number) => <option key={number}>{number}</option>)}</select></td>
                    <td className="p-2 text-center"><input type="checkbox" aria-label={`${t('Verified every cell in row', 'تحققت من كل خلية في الصف')} ${rowIndex + 1}`} checked={row.verified} onChange={(event) => setRows((current) => current.map((item, index) => index === rowIndex ? { ...item, verified: event.target.checked } : item))} /></td>
                    <td><button type="button" aria-label={`${t('Remove row', 'حذف صف')} ${rowIndex + 1}`} className="p-2 text-red-600" onClick={() => { setRows((current) => current.filter((_, index) => index !== rowIndex)); setConfirmed(false) }}><Trash2 size={14} /></button></td>
                  </tr>)}</tbody>
                </table>
              </div>
              <div className="flex flex-wrap gap-3 text-xs">
                <button type="button" disabled={rows.length >= 1000} className="flex items-center gap-1 text-blue-700 dark:text-blue-200" onClick={() => { setRows((current) => [...current, { page, values: columns.map(() => ''), verified: false }]); setConfirmed(false) }}><Plus size={13} />{t('Add row', 'إضافة صف')}</button>
                <button type="button" disabled={columns.length >= 30} className="flex items-center gap-1 text-blue-700 dark:text-blue-200" onClick={() => { setColumns((current) => [...current, '']); setRows((current) => current.map((row) => ({ ...row, values: [...row.values, ''], verified: false }))); setConfirmed(false) }}><Plus size={13} />{t('Add column', 'إضافة عمود')}</button>
              </div>
              <label className="flex gap-2 text-xs leading-relaxed"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />{t('I verified the headings and every included row against the original pages. This analysis covers only these rows, not the complete PDF.', 'تحققت من العناوين وكل صف مُدرج مقابل الصفحات الأصلية. يشمل هذا التحليل هذه الصفوف فقط، وليس PDF بأكمله.')}</label>
              <label className="block text-xs font-medium">{t('Calculation question', 'سؤال الحساب')}<input className={`${input} mt-1`} value={question} onChange={(event) => setQuestion(event.target.value)} /></label>
              <button type="button" disabled={!valid || sending} onClick={() => void submit()} className="rounded-lg bg-blue-700 px-4 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">{sending ? t('Submitting reviewed rows…', 'إرسال الصفوف المُراجعة…') : t('Analyze confirmed rows only', 'تحليل الصفوف المؤكدة فقط')}</button>
              {error && <p role="alert" className="text-xs text-red-600">{error}</p>}
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
