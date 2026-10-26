import { useMemo, useRef, useState, type ChangeEvent, type DragEvent, type FormEvent } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  AlertCircle, ArrowDownToLine, ArrowUpRight, BarChart3, Check, CheckCircle2,
  CircleHelp, Database, FileSpreadsheet, FileText, Fingerprint, LoaderCircle, LockKeyhole,
  MessageSquareText, Plus, Search, ShieldCheck, Sparkles, Trash2, UploadCloud, X,
} from 'lucide-react'
import {
  Area, AreaChart, CartesianGrid, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { useLanguage } from '../context/LanguageContext'
import { requestLocalAnalysis, type ExtractionProgress } from '../components/analytics/analysisStream'
import { WorkforceScenarioStudio } from '../components/dataHub/WorkforceScenarioStudio'

type CleaningId = 'trim_text' | 'remove_blank_rows' | 'remove_blank_columns' | 'remove_exact_duplicates'
interface ColumnProfile {
  name: string; dtype: string; type: string; missing_count: number; missing_percent: number
  unique_count: number; sensitive: boolean; sensitive_reason: string | null
  numeric_summary?: { non_null: number; mean: number | null; median: number | null; min: number | null; max: number | null; std: number | null } | null
  outlier_count?: number | null
}
interface Anomaly {
  id: string; kind: string; column: string; count: number; evaluated: number; percentage: number
  severity: string; method: string; method_ar?: string; lower_fence?: number; upper_fence?: number; expired?: boolean; due_30_days?: boolean
  periods?: string[]
}
interface DatasetProfile {
  id: string; filename: string; sheet: string; source_type: string; source_rows: number; analyzed_rows: number
  source_columns: number; analyzed_columns: number; column_count: number; missing_cells: number
  missing_percent: number; duplicate_rows: number; quality_score: number; columns: ColumnProfile[]
  numeric_columns: string[]; date_columns: string[]; anomalies: Anomaly[]
  cleaning_suggestions: { id: CleaningId; eligible: number | boolean; reason: string }[]
  applied_cleaning: { id: CleaningId; changed: number }[]; warnings: string[]; ingestion_transformations: string[]
}
interface InspectResponse {
  datasets: DatasetProfile[]; errors: { filename: string; detail: string }[]; files_processed: number
  privacy: { mode: string; persisted: boolean; source_rows_returned: boolean; sensitive_column_values_returned: boolean }
}
interface ForecastResponse {
  filename: string; sheet: string; date_column: string; metric_column: string; aggregation: string
  period_grain: string; method: string; observation_count: number
  selected_model: string; backtest_mae: number | null; validation_periods: number
  observed: { period: string; value: number }[]; forecast: { period: string; estimate: number; lower: number; upper: number }[]
  limitations: string[]
}
interface LocalAnswer {
  answer?: { answer_text?: string; key_evidence?: { label?: string; value?: unknown }[]; limitations?: string[] }
  files_ingested?: string[]; file_details?: { filename: string; rows?: number; columns?: string[]; error?: string }[]
}
interface ChatTurn { question: string; result?: LocalAnswer; error?: string; loading: boolean }

const MAX_FILE = 25 * 1024 * 1024
const MAX_TOTAL = 50 * 1024 * 1024
const MAX_FILES = 10
const ACCEPTED = /\.(csv|xls|xlsx|json|jsonl)$/i
const CLEANING: { id: CleaningId; en: string; ar: string; noteEn: string; noteAr: string }[] = [
  { id: 'trim_text', en: 'Trim surrounding text spaces', ar: 'إزالة المسافات من أطراف النص', noteEn: 'Text values only', noteAr: 'للقيم النصية فقط' },
  { id: 'remove_blank_rows', en: 'Remove fully blank rows', ar: 'إزالة الصفوف الفارغة بالكامل', noteEn: 'No populated cells', noteAr: 'من دون خلايا معبأة' },
  { id: 'remove_blank_columns', en: 'Remove fully blank columns', ar: 'إزالة الأعمدة الفارغة بالكامل', noteEn: 'No populated cells', noteAr: 'من دون خلايا معبأة' },
  { id: 'remove_exact_duplicates', en: 'Remove exact duplicate rows', ar: 'إزالة الصفوف المتطابقة تماماً', noteEn: 'Exact matches only', noteAr: 'التطابق التام فقط' },
]

function bytes(size: number, isAr: boolean) {
  return size < 1024 * 1024 ? `${(size / 1024).toFixed(0)} ${isAr ? 'ك.ب' : 'KB'}` : `${(size / (1024 * 1024)).toFixed(1)} ${isAr ? 'م.ب' : 'MB'}`
}
function number(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('en-US', { maximumFractionDigits: 2 })
}
function cleaningLabel(id: CleaningId, translate: (en: string, ar: string) => string) {
  const option = CLEANING.find((item) => item.id === id)
  return option ? translate(option.en, option.ar) : id
}
function errorMessage(response: Response, body: unknown) {
  const detail = body && typeof body === 'object' && 'detail' in body ? (body as { detail?: unknown }).detail : null
  return typeof detail === 'string' ? detail : `Request failed (${response.status})`
}

export function DataHub() {
  const { t, isAr } = useLanguage()
  const [files, setFiles] = useState<File[]>([])
  const [cleaning, setCleaning] = useState<CleaningId[]>([])
  const [inspection, setInspection] = useState<InspectResponse | null>(null)
  const [busy, setBusy] = useState<'inspect' | 'export-xlsx' | 'export-pdf' | null>(null)
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [search, setSearch] = useState('')
  const [schemaFilter, setSchemaFilter] = useState<'all' | 'numeric' | 'date' | 'sensitive' | 'missing'>('all')
  const [forecastDataset, setForecastDataset] = useState('')
  const [forecastDate, setForecastDate] = useState('')
  const [forecastMetric, setForecastMetric] = useState('')
  const [aggregation, setAggregation] = useState<'sum' | 'mean' | 'count'>('sum')
  const [horizon, setHorizon] = useState(3)
  const [forecast, setForecast] = useState<ForecastResponse | null>(null)
  const [forecastBusy, setForecastBusy] = useState(false)
  const [scenarioBusy, setScenarioBusy] = useState(false)
  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [chatBusy, setChatBusy] = useState(false)
  const [extractionProgress, setExtractionProgress] = useState<ExtractionProgress | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const ready = !!inspection?.datasets.length && inspection.files_processed > 0
  const selectedBytes = files.reduce((sum, file) => sum + file.size, 0)
  const activeForecastDataset = inspection?.datasets.find((item) => item.id === forecastDataset)
    ?? inspection?.datasets.find((item) => item.date_columns?.length)
    ?? inspection?.datasets[0]
  const permittedMeasures = useMemo(() => {
    if (!activeForecastDataset) return []
    return activeForecastDataset.columns.filter((column) => !column.sensitive && !!column.numeric_summary).map((column) => column.name)
  }, [activeForecastDataset])
  const schemaRows = useMemo(() => (inspection?.datasets ?? []).flatMap((dataset) =>
    dataset.columns.map((column) => ({ dataset, column })),
  ).filter(({ dataset, column }) => {
    const query = search.trim().toLowerCase()
    const matchesText = !query || `${dataset.filename} ${dataset.sheet} ${column.name} ${column.type}`.toLowerCase().includes(query)
    const matchesFilter = schemaFilter === 'all'
      || (schemaFilter === 'numeric' && !!column.numeric_summary)
      || (schemaFilter === 'date' && (column.type.toLowerCase().includes('date') || (dataset.date_columns ?? []).includes(column.name)))
      || (schemaFilter === 'sensitive' && column.sensitive)
      || (schemaFilter === 'missing' && column.missing_count > 0)
    return matchesText && matchesFilter
  }), [inspection, search, schemaFilter])
  const forecastChartData = useMemo(() => {
    if (!forecast) return []
    return [
      ...forecast.observed.map((point, index) => ({
        period: point.period,
        observed: point.value,
        estimate: index === forecast.observed.length - 1 ? point.value : null,
        lower: null as number | null,
        interval: null as number | null,
      })),
      ...forecast.forecast.map((point) => ({
        period: point.period,
        observed: null as number | null,
        estimate: point.estimate,
        lower: point.lower,
        interval: Math.max(0, point.upper - point.lower),
      })),
    ]
  }, [forecast])

  const addFiles = (incoming: File[]) => {
    if (busy || forecastBusy || scenarioBusy || chatBusy) return
    const issues: string[] = []
    const next = [...files]
    const accepted = incoming.filter((file) => ACCEPTED.test(file.name))
    if (accepted.length !== incoming.length) issues.push(t('Some files were skipped. Choose CSV, XLS, XLSX, JSON or JSON Lines files only.', 'تم تخطي بعض الملفات. اختر ملفات CSV أو XLS أو XLSX أو JSON أو JSON Lines فقط.'))
    for (const file of accepted) {
      if (next.some((item) => item.name === file.name)) { issues.push(t(`${file.name} is already selected or has a duplicate filename.`, `الملف ${file.name} محدد مسبقاً أو يحمل اسماً مكرراً.`)); continue }
      if (file.size > MAX_FILE) { issues.push(t(`${file.name} exceeds the 25 MB per-file limit.`, `يتجاوز الملف ${file.name} الحد الأقصى البالغ 25 م.ب.`)); continue }
      if (next.length >= MAX_FILES) { issues.push(t('The limit is 10 files per analysis.', 'الحد الأقصى 10 ملفات لكل تحليل.')); break }
      if (next.reduce((sum, item) => sum + item.size, 0) + file.size > MAX_TOTAL) { issues.push(t('The combined file size exceeds 50 MB.', 'يتجاوز الحجم الإجمالي للملفات 50 م.ب.')); break }
      next.push(file)
    }
    setFiles(next)
    setError(issues.join(' '))
    if (next.length !== files.length) {
      setInspection(null)
      setForecast(null)
      setTurns([])
    }
  }
  const onFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    addFiles(Array.from(event.target.files ?? []))
    event.target.value = ''
  }
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault(); setDragging(false)
    if (!busy && !forecastBusy && !scenarioBusy && !chatBusy) addFiles(Array.from(event.dataTransfer.files))
  }
  const removeFile = (index: number) => {
    if (busy || forecastBusy || scenarioBusy || chatBusy) return
    setFiles((current) => current.filter((_, i) => i !== index)); setInspection(null); setForecast(null); setTurns([])
  }
  const toggleCleaning = (id: CleaningId) => {
    setCleaning((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])
    setInspection(null)
    setForecast(null)
  }
  const buildInspectForm = () => {
    const form = new FormData()
    files.forEach((file) => form.append('files', file))
    form.append('cleaning_options', JSON.stringify(cleaning))
    return form
  }
  const inspect = async () => {
    if (!files.length || busy || forecastBusy || scenarioBusy || chatBusy) return
    setBusy('inspect'); setError(''); setInspection(null); setForecast(null)
    try {
      const response = await fetch('/api/local/data-hub/inspect', { method: 'POST', body: buildInspectForm() })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(errorMessage(response, payload))
      const result = payload as InspectResponse
      if (!Array.isArray(result.datasets)) throw new Error(t('The inspection response was not in the expected format.', 'تنسيق استجابة الفحص غير متوقع.'))
      setInspection(result)
       const first = result.datasets.find((dataset) => dataset.date_columns?.length) ?? result.datasets[0]
      if (first) {
        setForecastDataset(first.id)
        setForecastDate(first.date_columns?.[0] ?? '')
        setForecastMetric(first.columns.find((column) => !column.sensitive && !!column.numeric_summary)?.name ?? '__rows__')
      }
      if (result.errors?.length) setError(result.errors.map((item) => `${item.filename}: ${item.detail}`).join(' · '))
    } catch (err) {
      setError(err instanceof Error ? err.message : t('Inspection failed. Please retry.', 'تعذر الفحص. يرجى إعادة المحاولة.'))
    } finally { setBusy(null) }
  }
  const download = async (kind: 'xlsx' | 'pdf') => {
    if (!files.length || busy || forecastBusy || scenarioBusy || chatBusy) return
    setBusy(kind === 'xlsx' ? 'export-xlsx' : 'export-pdf'); setError('')
    try {
      const form = buildInspectForm()
      form.append('language', isAr ? 'ar' : 'en')
      const response = await fetch(`/api/local/data-hub/export.${kind}`, { method: 'POST', body: form })
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(errorMessage(response, payload))
      }
      const blob = await response.blob()
      const disposition = response.headers.get('content-disposition') ?? ''
      const match = disposition.match(/filename\*?=(?:UTF-8''|")?([^";]+)/i)
      const filename = match?.[1] ? decodeURIComponent(match[1].replace(/"/g, '')) : `thrive-data-hub-summary.${kind}`
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url; anchor.download = filename
      document.body.append(anchor); anchor.click(); anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) { setError(err instanceof Error ? err.message : t('Export failed. Please retry.', 'تعذر التصدير. يرجى إعادة المحاولة.')) }
    finally { setBusy(null) }
  }
  const runForecast = async (event: FormEvent) => {
    event.preventDefault()
    if (!activeForecastDataset || !forecastDate || !forecastMetric || busy || forecastBusy || scenarioBusy || chatBusy) return
    setForecastBusy(true); setError(''); setForecast(null)
    try {
      const form = new FormData()
      const selectedFile = files.find((file) => file.name === activeForecastDataset.filename)
      if (!selectedFile) throw new Error(t('The source file is no longer selected. Inspect it again.', 'لم يعد الملف المصدر محدداً. أعد فحصه.'))
      form.append('file', selectedFile); form.append('sheet', activeForecastDataset.sheet)
      form.append('date_column', forecastDate); form.append('metric_column', forecastMetric)
      form.append('aggregation', forecastMetric === '__rows__' ? 'count' : aggregation)
       form.append('horizon', String(horizon)); form.append('language', isAr ? 'ar' : 'en')
      const response = await fetch('/api/local/data-hub/forecast', { method: 'POST', body: form })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(errorMessage(response, payload))
      setForecast(payload as ForecastResponse)
    } catch (err) { setError(err instanceof Error ? err.message : t('Forecast could not be calculated.', 'تعذر حساب التوقع.')) }
    finally { setForecastBusy(false) }
  }
  const askLocal = async (event: FormEvent) => {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || !files.length || busy || forecastBusy || chatBusy || scenarioBusy) return
    setQuestion(''); setChatBusy(true); setExtractionProgress({ stage: 'starting' })
    const turnIndex = turns.length
    setTurns((current) => [...current, { question: trimmed, loading: true }])
    try {
      const form = new FormData()
      form.append('question', trimmed); form.append('use_llm', 'false'); form.append('use_cloud', 'false')
      files.forEach((file) => form.append('files', file))
      const result = await requestLocalAnalysis<LocalAnswer>(form, {
        streaming: true,
        onProgress: setExtractionProgress,
      })
      setTurns((current) => current.map((turn, index) => index === turnIndex ? { ...turn, result, loading: false } : turn))
    } catch (err) {
      setTurns((current) => current.map((turn, index) => index === turnIndex ? { ...turn, error: err instanceof Error ? err.message : t('Local analysis failed.', 'تعذر التحليل المحلي.'), loading: false } : turn))
    } finally { setChatBusy(false); setExtractionProgress(null) }
  }

  const progressText = (progress: ExtractionProgress) => {
    const stages: Record<string, [string, string]> = {
      starting: ['Preparing local analysis…', 'جارٍ إعداد التحليل المحلي…'],
      compatibility: ['Switching to the compatible response mode…', 'جارٍ التحويل إلى وضع الاستجابة المتوافق…'],
      parsing: ['Reading the selected file…', 'جارٍ قراءة الملف المحدد…'],
      ocr: ['Extracting text from the document…', 'جارٍ استخراج النص من المستند…'],
      scanning: ['Reviewing data privacy…', 'جارٍ فحص خصوصية البيانات…'],
      analyzing: ['Analyzing the uploaded data…', 'جارٍ تحليل البيانات المرفوعة…'],
      standard: ['Analyzing locally…', 'جارٍ التحليل محلياً…'],
    }
    const [english, arabic] = stages[progress.stage.toLowerCase()] ?? ['Processing locally…', 'جارٍ المعالجة محلياً…']
    const page = progress.page && progress.total_pages
      ? t(`Page ${progress.page} of ${progress.total_pages}`, `الصفحة ${progress.page} من ${progress.total_pages}`)
      : ''
    const source = progress.filename ? ` · ${progress.filename}` : ''
    return `${t(english, arabic)}${page ? ` · ${page}` : ''}${source}`
  }

  const card = 'rounded-2xl border border-slate-700/70 bg-[#202447]/85 shadow-[0_14px_36px_rgba(8,12,34,.18)]'
  const inputClass = 'w-full rounded-xl border border-slate-700 bg-[#171a34] px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-[#72c6a3] focus:outline-none focus:ring-2 focus:ring-[#72c6a3]/20'
  const primaryButton = 'inline-flex min-h-10 items-center justify-center gap-2 rounded-xl bg-[#72c6a3] px-4 py-2 text-sm font-semibold text-[#171a34] transition hover:bg-[#8bd6b6] disabled:cursor-not-allowed disabled:opacity-50'
  const filterLabels = [
    ['all', t('All columns', 'كل الأعمدة')], ['numeric', t('Numeric', 'رقمية')], ['date', t('Dates', 'تواريخ')],
    ['sensitive', t('Sensitive flagged', 'موسومة كحساسة')], ['missing', t('Has missing values', 'تحتوي على قيم مفقودة')],
  ] as const

  return (
    <main dir={isAr ? 'rtl' : 'ltr'} className="data-hub-page min-h-[100dvh] space-y-6 pb-10 text-slate-100">
      <motion.header initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="relative overflow-hidden rounded-3xl border border-[#5378ac]/35 bg-[linear-gradient(115deg,#202447_0%,#252b55_64%,#283856_100%)] p-5 sm:p-7">
        <div className="pointer-events-none absolute -right-8 -top-20 h-64 w-64 rounded-full border border-[#72c6a3]/10" />
        <div className="pointer-events-none absolute -right-1 -top-12 h-48 w-48 rounded-full border border-[#72c6a3]/10" />
        <div className="relative flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
          <div className="max-w-3xl">
            <div className="mb-3 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[.22em] text-[#9bdac0]">
              <span className="h-px w-7 bg-[#72c6a3]" /> THRIVE <span className="text-slate-500">/</span> {t('EXECUTIVE WORKSPACE', 'مساحة العمل التنفيذية')}
            </div>
            <h1 className="text-3xl font-semibold tracking-tight text-white sm:text-[2.55rem]">{t('Interactive Data Hub', 'مركز البيانات التفاعلي')}</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">{t('Inspect local files with clear provenance. Review schema, quality and aggregate signals—without exposing source records.', 'افحص الملفات محلياً مع توثيق واضح للمصدر. راجع المخطط والجودة والمؤشرات المجمّعة دون كشف سجلات المصدر.')}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2 self-start rounded-full border border-[#72c6a3]/25 bg-[#72c6a3]/10 px-3 py-2 text-xs font-semibold text-[#b4ebd4] lg:self-auto">
            <ShieldCheck size={15} /> {t('LOCAL PROCESSING', 'معالجة محلية')}
          </div>
        </div>
        <div className="relative mt-6 grid grid-cols-2 gap-2 border-t border-white/10 pt-4 sm:grid-cols-4">
          {[
            [t('FILES IN SESSION', 'الملفات في الجلسة'), `${files.length} / ${MAX_FILES}`],
            [t('SESSION SIZE', 'حجم الجلسة'), `${bytes(selectedBytes, isAr)} / 50 MB`],
            [t('INSPECTION', 'الفحص'), ready ? t('Complete', 'مكتمل') : t('Not run', 'لم يبدأ')],
            [t('DATA POLICY', 'سياسة البيانات'), t('No source rows shown', 'لا تُعرض سجلات المصدر')],
          ].map(([label, value]) => <div key={label}><div className="text-[9px] font-bold tracking-[.15em] text-slate-400">{label}</div><div className="mt-1 text-xs font-semibold text-slate-100">{value}</div></div>)}
        </div>
      </motion.header>

      <section className={`${card} p-4 sm:p-5`} aria-labelledby="upload-heading">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div><h2 id="upload-heading" className="flex items-center gap-2 text-base font-semibold"><Database size={17} className="text-[#72c6a3]" />{t('Source files', 'ملفات المصدر')}</h2>
            <p className="mt-1 text-xs text-slate-400">{t('CSV, XLS, XLSX or JSON · 25 MB each · 50 MB total · up to 10 files', 'CSV أو XLS أو XLSX أو JSON · 25 م.ب لكل ملف · 50 م.ب إجمالاً · حتى 10 ملفات')}</p></div>
          <button type="button" onClick={() => inputRef.current?.click()} disabled={busy !== null || forecastBusy || scenarioBusy || chatBusy} className="btn-ghost min-h-9 border border-slate-700/80"><Plus size={15} />{t('Choose files', 'اختيار الملفات')}</button>
        </div>
        <input ref={inputRef} className="sr-only" type="file" multiple accept=".csv,.xls,.xlsx,.json,.jsonl" aria-label={t('Choose data files', 'اختيار ملفات البيانات')} onChange={onFileChange} disabled={busy !== null || forecastBusy || scenarioBusy || chatBusy} />
        <div
          role="button" tabIndex={0} aria-label={t('Drop files here or press Enter to choose files', 'أسقط الملفات هنا أو اضغط إدخال لاختيار الملفات')}
          onClick={() => inputRef.current?.click()} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); inputRef.current?.click() } }}
          onDragEnter={(event) => { event.preventDefault(); setDragging(true) }} onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false) }} onDrop={onDrop}
          className={`cursor-pointer rounded-2xl border border-dashed p-5 text-center transition-colors sm:p-7 ${dragging ? 'border-[#72c6a3] bg-[#72c6a3]/10' : 'border-slate-600 bg-[#171a34]/55 hover:border-slate-400'}`}
        >
          <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl border border-slate-600 bg-[#252b55] text-[#9bdac0]"><UploadCloud size={21} /></div>
          <p className="mt-3 text-sm font-semibold text-slate-200">{t('Drop files to inspect', 'أسقط الملفات لبدء الفحص')}</p>
          <p className="mt-1 text-xs text-slate-500">{t('or browse from this device · files are not displayed as records', 'أو استعرض ملفات هذا الجهاز · لا تُعرض الملفات كسجلات')}</p>
        </div>
        {files.length > 0 && <div className="mt-3 space-y-2">{files.map((file, index) => <div key={`${file.name}-${file.lastModified}-${index}`} className="flex items-center gap-3 rounded-xl border border-slate-700/70 bg-[#171a34]/60 px-3 py-2.5">
          <FileSpreadsheet size={16} className="shrink-0 text-[#72c6a3]" /><span className="min-w-0 flex-1 truncate text-sm text-slate-200">{file.name}</span><span className="text-xs tabular-nums text-slate-500">{bytes(file.size, isAr)}</span>
          <button type="button" onClick={() => removeFile(index)} disabled={busy !== null || forecastBusy || scenarioBusy || chatBusy} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-700 hover:text-white disabled:opacity-40" aria-label={t(`Remove ${file.name}`, `إزالة ${file.name}`)}><X size={15} /></button>
        </div>)}</div>}
        <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_auto] lg:items-end">
          <div>
            <div className="mb-2 text-[10px] font-bold uppercase tracking-[.16em] text-slate-400">{t('Optional in-memory cleaning', 'تنظيف اختياري في الذاكرة')}</div>
            <div className="flex flex-wrap gap-x-4 gap-y-2">{CLEANING.map((option) => <label key={option.id} className="inline-flex cursor-pointer items-center gap-2 text-xs text-slate-300">
              <input type="checkbox" className="h-3.5 w-3.5 accent-[#72c6a3]" checked={cleaning.includes(option.id)} onChange={() => toggleCleaning(option.id)} disabled={busy !== null || forecastBusy || scenarioBusy || chatBusy} />
              <span>{t(option.en, option.ar)} <span className="text-slate-500">· {t(option.noteEn, option.noteAr)}</span></span>
            </label>)}</div>
            <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-5 text-slate-500"><CircleHelp size={13} className="mt-0.5 shrink-0" />{t('Selected transformations apply only to a re-analyzed in-memory copy. Original files are unchanged.', 'تُطبّق التحويلات المحددة على نسخة داخل الذاكرة يعاد تحليلها فقط. لا تتغير الملفات الأصلية.')}</p>
          </div>
          <button type="button" onClick={() => void inspect()} disabled={!files.length || busy !== null || forecastBusy || scenarioBusy || chatBusy} className={`${primaryButton} w-full lg:w-auto`}>
            {busy === 'inspect' ? <LoaderCircle size={16} className="animate-spin" /> : <Sparkles size={16} />}
            {busy === 'inspect' ? t('Inspecting…', 'جارٍ الفحص…') : t('Inspect files', 'فحص الملفات')}
          </button>
        </div>
      </section>

      <AnimatePresence>{error && <motion.div initial={{ opacity: 0, y: -5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} role="alert" className="flex items-start gap-2 rounded-xl border border-rose-400/25 bg-rose-950/25 px-4 py-3 text-sm text-rose-200"><AlertCircle size={17} className="mt-0.5 shrink-0" /><span className="flex-1">{error}</span><button type="button" onClick={() => setError('')} aria-label={t('Dismiss error', 'إغلاق رسالة الخطأ')}><X size={15} /></button></motion.div>}</AnimatePresence>

      {busy === 'inspect' && <section aria-label={t('Inspection loading', 'جارٍ تحميل الفحص')} className={`${card} space-y-3 p-5`}><div className="skeleton h-4 w-40" /><div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{[1, 2, 3, 4].map((item) => <div key={item} className="skeleton h-16" />)}<div className="skeleton col-span-full h-32" /></div></section>}

      {!inspection && busy !== 'inspect' && <section className={`${card} flex flex-col items-center px-6 py-10 text-center`}>
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-[#5378ac]/30 bg-[#5378ac]/10 text-[#9db8df]"><FileText size={23} /></div>
        <h2 className="mt-4 text-base font-semibold text-slate-200">{t('A clear view of the files you choose', 'رؤية واضحة للملفات التي تختارها')}</h2>
        <p className="mt-2 max-w-lg text-sm leading-6 text-slate-400">{t('Add local files, then inspect their structure and quality. Only schema and aggregate findings are presented here.', 'أضف ملفات محلية ثم افحص بنيتها وجودتها. تُعرض هنا معلومات المخطط والنتائج المجمّعة فقط.')}</p>
        <div className="mt-4 flex flex-wrap justify-center gap-2 text-[11px] text-slate-500"><span className="rounded-full border border-slate-700 px-2.5 py-1">{t('No record previews', 'لا معاينة للسجلات')}</span><span className="rounded-full border border-slate-700 px-2.5 py-1">{t('Sensitive values hidden', 'القيم الحساسة مخفية')}</span><span className="rounded-full border border-slate-700 px-2.5 py-1">{t('Source rows stay local', 'تبقى سجلات المصدر محلية')}</span></div>
      </section>}

      {inspection && busy !== 'inspect' && <div className="space-y-5">
        {inspection.datasets.length === 0 && <section className={`${card} p-5`}><div className="flex items-center gap-2 font-semibold text-amber-200"><AlertCircle size={17} />{t('No files were ready for inspection', 'لم تكن أي ملفات جاهزة للفحص')}</div><p className="mt-2 text-sm text-slate-400">{t('Review the file-specific errors above, then select valid files and inspect again.', 'راجع أخطاء الملفات أعلاه، ثم اختر ملفات صالحة وأعد الفحص.')}</p></section>}
        {inspection.datasets.length > 0 && <>
          <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[
              { label: t('DATASETS ANALYZED', 'مجموعات البيانات المحللة'), value: inspection.datasets.length, icon: Database },
              { label: t('ANALYZED ROWS', 'الصفوف المحللة'), value: inspection.datasets.reduce((sum, item) => sum + item.analyzed_rows, 0), icon: BarChart3 },
              { label: t('SCHEMA FIELDS', 'حقول المخطط'), value: inspection.datasets.reduce((sum, item) => sum + item.column_count, 0), icon: FileSpreadsheet },
              { label: t('QUALITY INDEX', 'مؤشر الجودة'), value: `${(inspection.datasets.reduce((sum, item) => sum + item.quality_score, 0) / inspection.datasets.length).toFixed(1)}`, icon: CheckCircle2 },
            ].map((metric, index) => <motion.div key={metric.label} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * .04 }} className={`${card} p-4`}>
              <div className="flex items-center justify-between text-[9px] font-bold tracking-[.15em] text-slate-400"><span>{metric.label}</span><metric.icon size={15} className="text-[#72c6a3]" /></div>
              <div className="mt-3 text-2xl font-semibold tabular-nums text-white">{typeof metric.value === 'number' ? metric.value.toLocaleString('en-US') : metric.value}</div>
            </motion.div>)}
          </section>

          <section className={`${card} overflow-hidden`}>
            <div className="flex flex-col justify-between gap-3 border-b border-slate-700/70 p-4 sm:flex-row sm:items-center sm:px-5">
              <div><h2 className="flex items-center gap-2 text-base font-semibold"><Database size={17} className="text-[#72c6a3]" />{t('Schema & quality', 'المخطط والجودة')}</h2><p className="mt-1 text-xs text-slate-400">{t('Column-level metadata only. Cell contents are never shown.', 'بيانات وصفية على مستوى الأعمدة فقط. لا تُعرض محتويات الخلايا.')}</p></div>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => void download('xlsx')} disabled={!files.length || busy !== null || forecastBusy || scenarioBusy || chatBusy} className="btn-ghost min-h-9 border border-slate-700"><ArrowDownToLine size={14} />{busy === 'export-xlsx' ? t('Preparing…', 'جارٍ التجهيز…') : t('Excel summary', 'ملخص Excel')}</button>
                <button type="button" onClick={() => void download('pdf')} disabled={!files.length || busy !== null || forecastBusy || scenarioBusy || chatBusy} className="btn-ghost min-h-9 border border-slate-700"><ArrowDownToLine size={14} />{busy === 'export-pdf' ? t('Preparing…', 'جارٍ التجهيز…') : t('PDF summary', 'ملخص PDF')}</button>
              </div>
            </div>
            <div className="grid gap-3 border-b border-slate-700/70 bg-[#171a34]/35 p-4 sm:grid-cols-2 xl:grid-cols-4">
              {inspection.datasets.map((dataset) => <div key={dataset.id} className="rounded-xl border border-slate-700/70 bg-[#202447] p-3">
                <div className="flex items-start justify-between gap-2"><div className="min-w-0"><div className="truncate text-sm font-semibold text-slate-100" title={dataset.filename}>{dataset.filename}</div><div className="mt-1 truncate text-[11px] text-slate-500">{dataset.sheet || dataset.source_type}</div></div><span className="shrink-0 rounded-full border border-[#72c6a3]/20 bg-[#72c6a3]/10 px-2 py-1 text-[10px] font-semibold text-[#a8e2c7]">{number(dataset.quality_score)} / 100</span></div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-[10px]"><div><span className="block text-slate-500">{t('Rows', 'صفوف')}</span><b className="mt-1 block text-slate-200 tabular-nums">{number(dataset.analyzed_rows)}</b></div><div><span className="block text-slate-500">{t('Fields', 'حقول')}</span><b className="mt-1 block text-slate-200 tabular-nums">{number(dataset.column_count)}</b></div><div><span className="block text-slate-500">{t('Missing', 'مفقود')}</span><b className="mt-1 block text-slate-200 tabular-nums">{number(dataset.missing_percent)}%</b></div></div>
                 {(dataset.warnings.length > 0 || dataset.ingestion_transformations.length > 0 || dataset.applied_cleaning.length > 0 || dataset.cleaning_suggestions.length > 0) && <div className="mt-3 space-y-1 border-t border-slate-700/70 pt-2 text-[10px] text-amber-200/80">
                  {dataset.warnings.map((warning, index) => <p key={`warn-${index}`}>• {warning}</p>)}
                  {dataset.ingestion_transformations.map((item, index) => <p key={`transform-${index}`}>· {item}</p>)}
                   {dataset.applied_cleaning.map((item, index) => <p key={`clean-${index}`} className="text-[#9bdac0]">✓ {cleaningLabel(item.id, t)} · {number(item.changed)} {t('changes', 'تغييرات')}</p>)}
                   {!!dataset.cleaning_suggestions.filter((item) => item.eligible === true || (typeof item.eligible === 'number' && item.eligible > 0)).length && <p className="text-slate-400">{t('Suggested review:', 'مراجعة مقترحة:')} {dataset.cleaning_suggestions.filter((item) => item.eligible === true || (typeof item.eligible === 'number' && item.eligible > 0)).map((item) => `${cleaningLabel(item.id, t)}${typeof item.eligible === 'number' ? ` (${number(item.eligible)})` : ''}`).join(' · ')}</p>}
                </div>}
              </div>)}
            </div>
            <div className="flex flex-col gap-3 border-b border-slate-700/70 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="relative min-w-0 flex-1 sm:max-w-sm"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 rtl:left-auto rtl:right-3" /><input value={search} onChange={(event) => setSearch(event.target.value)} className={`${inputClass} pl-9 rtl:pl-3 rtl:pr-9`} aria-label={t('Search schema', 'البحث في المخطط')} placeholder={t('Search columns or file…', 'ابحث عن عمود أو ملف…')} /></div>
              <div className="flex items-center gap-2"><label htmlFor="schema-filter" className="sr-only">{t('Filter schema columns', 'تصفية أعمدة المخطط')}</label><select id="schema-filter" className={`${inputClass} min-w-[190px] py-2`} value={schemaFilter} onChange={(event) => setSchemaFilter(event.target.value as typeof schemaFilter)}>{filterLabels.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><span className="whitespace-nowrap text-xs text-slate-500">{schemaRows.length} {t('fields', 'حقول')}</span></div>
            </div>
            <div className="max-h-[440px] overflow-auto">
              <table className="w-full min-w-[790px] text-left text-xs">
                <thead className="sticky top-0 z-10 bg-[#202447] text-[9px] font-bold uppercase tracking-[.12em] text-slate-400"><tr>{[t('Source / field', 'المصدر / الحقل'), t('Type', 'النوع'), t('Missing', 'مفقود'), t('Unique', 'فريد'), t('Numeric summary', 'ملخص رقمي'), t('Privacy', 'الخصوصية')].map((label) => <th key={label} className="px-4 py-3">{label}</th>)}</tr></thead>
                <tbody className="divide-y divide-slate-700/50">
                  {schemaRows.map(({ dataset, column }, index) => <tr key={`${dataset.id}-${column.name}-${index}`} className="transition-colors hover:bg-white/[.025]">
                    <td className="max-w-[260px] px-4 py-3"><div className="truncate font-semibold text-slate-200" title={column.name}>{column.name}</div><div className="mt-1 truncate text-[10px] text-slate-500" title={dataset.filename}>{dataset.filename}{dataset.sheet ? ` · ${dataset.sheet}` : ''}</div></td>
                    <td className="px-4 py-3"><span className="rounded-md border border-slate-700 bg-slate-800/70 px-2 py-1 text-[10px] text-slate-300">{column.type || column.dtype || t('Unknown', 'غير معروف')}</span></td>
                    <td className="px-4 py-3 tabular-nums text-slate-300">{number(column.missing_count)} <span className="text-slate-500">({number(column.missing_percent)}%)</span></td>
                    <td className="px-4 py-3 tabular-nums text-slate-300">{number(column.unique_count)}</td>
                    <td className="px-4 py-3">{column.numeric_summary ? <div className="space-y-1 text-[10px] text-slate-400"><span>{t('Mean', 'المتوسط')} <b className="text-slate-200">{number(column.numeric_summary.mean)}</b></span><span className="mx-2 text-slate-600">/</span><span>{t('Range', 'النطاق')} <b className="text-slate-200">{number(column.numeric_summary.min)}–{number(column.numeric_summary.max)}</b></span>{column.outlier_count != null && <span className="ms-2 text-amber-300">{number(column.outlier_count)} {t('outliers', 'قيم شاذة')}</span>}</div> : <span className="text-slate-600">—</span>}</td>
                    <td className="px-4 py-3">{column.sensitive ? <span title={column.sensitive_reason ?? undefined} className="inline-flex items-center gap-1 rounded-full border border-amber-300/20 bg-amber-300/10 px-2 py-1 text-[10px] text-amber-200"><LockKeyhole size={11} />{t('Flagged', 'موسوم')}</span> : <span className="inline-flex items-center gap-1 text-[10px] text-[#9bdac0]"><Check size={12} />{t('No flag', 'غير موسوم')}</span>}</td>
                  </tr>)}
                  {schemaRows.length === 0 && <tr><td colSpan={6} className="px-4 py-10 text-center text-sm text-slate-500">{t('No schema fields match this filter.', 'لا توجد حقول مخطط تطابق هذا التصفية.')}</td></tr>}
                </tbody>
              </table>
            </div>
          </section>

          <section className={`${card} p-4 sm:p-5`}>
            <div className="mb-4 flex items-start gap-3"><div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-300/10 text-amber-200"><Fingerprint size={17} /></div><div><h2 className="text-base font-semibold">{t('Aggregate findings', 'النتائج المجمّعة')}</h2><p className="mt-1 text-xs leading-5 text-slate-400">{t('Flags are screening signals, not conclusions. No source values or individual records are displayed.', 'المؤشرات إشارات للفحص وليست استنتاجات. لا تُعرض قيم المصدر أو السجلات الفردية.')}</p></div></div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {inspection.datasets.flatMap((dataset) => dataset.anomalies.map((anomaly) => ({ dataset, anomaly }))).map(({ dataset, anomaly }, index) => <div key={`${dataset.id}-${anomaly.id}-${index}`} className="rounded-xl border border-slate-700/70 bg-[#171a34]/65 p-4">
                <div className="flex items-start justify-between gap-3"><div><div className="text-sm font-semibold text-slate-100">{anomaly.kind === 'temporal_cost_spike' ? t('Monthly cost spikes', 'ارتفاعات التكلفة الشهرية') : anomaly.kind.replace(/_/g, ' ')}</div><div className="mt-1 text-[11px] text-slate-500">{dataset.filename} · {anomaly.column}</div></div><span className={`rounded-full px-2 py-1 text-[9px] font-bold uppercase tracking-wide ${anomaly.severity.toLowerCase() === 'high' || anomaly.severity.toLowerCase() === 'critical' ? 'bg-rose-400/10 text-rose-200' : anomaly.severity.toLowerCase() === 'medium' ? 'bg-amber-300/10 text-amber-100' : 'bg-slate-700 text-slate-300'}`}>{anomaly.severity}</span></div>
                <div className="mt-4 flex items-end justify-between"><div><div className="text-2xl font-semibold tabular-nums text-white">{number(anomaly.count)}</div><div className="text-[10px] text-slate-500">{t('flagged', 'موسوم')}</div></div><div className="text-right text-xs text-slate-400 rtl:text-left"><div>{number(anomaly.percentage)}% · {t('of', 'من')} {number(anomaly.evaluated)}</div><div className="mt-1 max-w-[200px] text-[10px] text-slate-500">{isAr ? anomaly.method_ar ?? anomaly.method : anomaly.method}</div>{anomaly.periods?.length ? <div className="mt-1 text-[10px] text-slate-400">{t('Periods', 'الفترات')}: {anomaly.periods.join(', ')}</div> : null}</div></div>
                {(anomaly.expired || anomaly.due_30_days) && <div className="mt-3 flex flex-wrap gap-2">{anomaly.expired && <span className="rounded-md bg-rose-300/10 px-2 py-1 text-[10px] text-rose-200">{t('Expired', 'منتهي')}</span>}{anomaly.due_30_days && <span className="rounded-md bg-amber-300/10 px-2 py-1 text-[10px] text-amber-100">{t('Due within 30 days', 'يستحق خلال 30 يوماً')}</span>}</div>}
              </div>)}
              {inspection.datasets.every((dataset) => !dataset.anomalies?.length) && <div className="col-span-full rounded-xl border border-dashed border-slate-700 p-6 text-center text-sm text-slate-500">{t('No aggregate flags were returned for these files.', 'لم تُرجع هذه الملفات مؤشرات مجمّعة.')}</div>}
            </div>
          </section>

          <WorkforceScenarioStudio
            datasets={inspection.datasets}
            files={files}
            cleaningOptions={cleaning}
            disabled={busy !== null || forecastBusy || scenarioBusy || chatBusy}
            onBusyChange={setScenarioBusy}
          />

          <section className={`${card} p-4 sm:p-5`}>
            <div className="mb-4 flex items-start gap-3"><div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#5378ac]/15 text-[#a9c3eb]"><BarChart3 size={17} /></div><div><h2 className="text-base font-semibold">{t('Local forecast', 'توقع محلي')}</h2><p className="mt-1 text-xs leading-5 text-slate-400">{t('Available only when a date field and a permitted numeric measure or record count are present.', 'يتاح عند وجود حقل تاريخ ومقياس رقمي مسموح أو عدد السجلات.')}</p></div></div>
            {inspection.datasets.some((dataset) => dataset.date_columns?.length && (dataset.columns.some((column) => !column.sensitive && !!column.numeric_summary) || dataset.analyzed_rows >= 0)) ? <>
              <form onSubmit={(event) => void runForecast(event)} className="grid gap-3 sm:grid-cols-2 xl:grid-cols-[1.35fr_1fr_1fr_.8fr_.75fr_auto] xl:items-end">
                <label className="block text-xs text-slate-400">{t('Dataset', 'مجموعة البيانات')}<select className={`${inputClass} mt-1.5`} value={activeForecastDataset?.id ?? ''} onChange={(event) => { const next = inspection.datasets.find((item) => item.id === event.target.value); setForecastDataset(event.target.value); setForecastDate(next?.date_columns?.[0] ?? ''); setForecastMetric(next?.columns.find((column) => !column.sensitive && !!column.numeric_summary)?.name ?? '__rows__'); setForecast(null) }}>{inspection.datasets.filter((dataset) => dataset.date_columns?.length).map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.filename}{dataset.sheet ? ` · ${dataset.sheet}` : ''}</option>)}</select></label>
                <label className="block text-xs text-slate-400">{t('Date field', 'حقل التاريخ')}<select className={`${inputClass} mt-1.5`} value={forecastDate} onChange={(event) => setForecastDate(event.target.value)}>{(activeForecastDataset?.date_columns ?? []).map((column) => <option key={column} value={column}>{column}</option>)}</select></label>
                <label className="block text-xs text-slate-400">{t('Measure', 'المقياس')}<select className={`${inputClass} mt-1.5`} value={forecastMetric} onChange={(event) => setForecastMetric(event.target.value)}><option value="__rows__">{t('Record count', 'عدد السجلات')}</option>{permittedMeasures.map((column) => <option key={column} value={column}>{column}</option>)}</select></label>
                <label className="block text-xs text-slate-400">{t('Aggregation', 'التجميع')}<select className={`${inputClass} mt-1.5`} value={forecastMetric === '__rows__' ? 'count' : aggregation} onChange={(event) => setAggregation(event.target.value as typeof aggregation)} disabled={forecastMetric === '__rows__'}><option value="sum">{t('Sum', 'المجموع')}</option><option value="mean">{t('Mean', 'المتوسط')}</option><option value="count">{t('Count', 'العدد')}</option></select></label>
                <label className="block text-xs text-slate-400">{t('Horizon', 'الأفق')}<select className={`${inputClass} mt-1.5`} value={horizon} onChange={(event) => setHorizon(Number(event.target.value))}>{Array.from({ length: 12 }, (_, index) => index + 1).map((value) => <option key={value} value={value}>{value} {t('periods', 'فترات')}</option>)}</select></label>
                <button type="submit" disabled={!forecastDate || forecastBusy || scenarioBusy} className={`${primaryButton} w-full xl:w-auto`}>{forecastBusy ? <LoaderCircle size={15} className="animate-spin" /> : <ArrowUpRight size={15} />}{t('Forecast', 'توقع')}</button>
              </form>
              {forecast && <div className="mt-5 rounded-xl border border-slate-700/70 bg-[#171a34]/55 p-3 sm:p-4">
                 <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><div><div className="text-sm font-semibold text-slate-100">{forecast.filename} · {forecast.metric_column === '__rows__' ? t('Record count', 'عدد السجلات') : forecast.metric_column}</div><div className="mt-1 text-[10px] text-slate-500">{forecast.method} · {forecast.period_grain} · {number(forecast.observation_count)} {t('observations', 'مشاهدات')} · {t('Backtest MAE', 'متوسط الخطأ المطلق للاختبار')} {number(forecast.backtest_mae)} ({number(forecast.validation_periods)} {t('periods', 'فترات')})</div></div><div className="text-[10px] text-slate-500">{t('Observed + forecast', 'فعلي + متوقع')}</div></div>
                <div className="h-64 w-full" role="img" aria-label={t('Chart of observed values and forecast with supplied interval', 'مخطط للقيم الفعلية والتوقع مع النطاق المقدم')}>
                  <ResponsiveContainer width="100%" height="100%"><AreaChart data={forecastChartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <defs><linearGradient id="forecastBand" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#72c6a3" stopOpacity={.24} /><stop offset="100%" stopColor="#72c6a3" stopOpacity={.025} /></linearGradient></defs>
                    <CartesianGrid stroke="#3b4264" strokeDasharray="3 5" vertical={false} />
                    <XAxis dataKey="period" tick={{ fill: '#929bb4', fontSize: 10 }} axisLine={{ stroke: '#3b4264' }} tickLine={false} />
                    <YAxis tick={{ fill: '#929bb4', fontSize: 10 }} axisLine={false} tickLine={false} width={48} />
                    <Tooltip contentStyle={{ background: '#202447', border: '1px solid #3b4264', borderRadius: 12, color: '#f2f3f8', fontSize: 12 }} formatter={(value: number, name: string) => [number(value), name]} />
                    <Area type="monotone" dataKey="lower" stackId="interval" stroke="transparent" fill="transparent" connectNulls />
                    <Area type="monotone" dataKey="interval" stackId="interval" stroke="transparent" fill="url(#forecastBand)" connectNulls />
                    <Line type="monotone" dataKey="observed" name={t('Observed', 'فعلي')} stroke="#9db8df" strokeWidth={2.25} connectNulls={false} dot={{ fill: '#9db8df', stroke: '#202447', strokeWidth: 2, r: 3 }} />
                    <Line type="monotone" dataKey="estimate" name={t('Forecast', 'توقع')} stroke="#72c6a3" strokeWidth={2.5} strokeDasharray="6 4" connectNulls={false} dot={{ fill: '#72c6a3', stroke: '#202447', strokeWidth: 2, r: 3 }} activeDot={{ r: 5 }} />
                  </AreaChart></ResponsiveContainer>
                </div>
                {forecast.limitations.length > 0 && <div className="mt-3 border-t border-slate-700/70 pt-3"><div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-amber-200">{t('Limitations', 'القيود')}</div><ul className="space-y-1 text-xs leading-5 text-slate-400">{forecast.limitations.map((item, index) => <li key={index}>· {item}</li>)}</ul></div>}
              </div>}
            </> : <div className="rounded-xl border border-dashed border-slate-700 p-5 text-sm text-slate-500">{t('No eligible date and measure pair was detected. A sensitive field cannot be used as a measure.', 'لم يتم العثور على زوج مؤهل من حقل تاريخ ومقياس. لا يمكن استخدام حقل حساس كمقياس.')}</div>}
          </section>

          <section className={`${card} overflow-hidden`}>
            <div className="flex items-start gap-3 border-b border-slate-700/70 p-4 sm:p-5"><div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#72c6a3]/10 text-[#9bdac0]"><MessageSquareText size={17} /></div><div><h2 className="text-base font-semibold">{t('Ask about these files', 'اسأل عن هذه الملفات')}</h2><p className="mt-1 text-xs leading-5 text-slate-400">{t('Local analysis only. Your selected files are sent to the local analysis service; cloud mode is disabled.', 'تحليل محلي فقط. تُرسل الملفات المحددة إلى خدمة التحليل المحلية؛ الوضع السحابي معطل.')}</p></div></div>
            <div className="max-h-[420px] space-y-3 overflow-auto p-4 sm:p-5">
              {turns.length === 0 && <div className="rounded-xl border border-dashed border-slate-700 px-4 py-6 text-center text-xs text-slate-500">{t('Your questions and grounded summaries will appear here.', 'ستظهر أسئلتك والملخصات المستندة إلى البيانات هنا.')}</div>}
              {turns.map((turn, index) => <div key={`${index}-${turn.question}`} className="space-y-2">
                <div className="ms-auto max-w-[90%] rounded-2xl rounded-ee-sm bg-[#2e3070] px-4 py-3 text-sm text-white">{turn.question}</div>
                 {turn.loading && <div className="flex items-center gap-2 text-xs text-slate-400"><LoaderCircle size={14} className="animate-spin" />{progressText(extractionProgress ?? { stage: 'starting' })}</div>}
                {turn.error && <div role="alert" className="rounded-xl border border-rose-400/20 bg-rose-950/20 p-3 text-xs text-rose-200">{turn.error}</div>}
                {turn.result?.answer && <div className="rounded-2xl rounded-ss-sm border border-slate-700 bg-[#171a34]/75 p-4">
                  <p className="whitespace-pre-wrap text-sm leading-6 text-slate-200">{turn.result.answer.answer_text || t('No answer text was returned.', 'لم يتم إرجاع نص للإجابة.')}</p>
                  {!!turn.result.answer.key_evidence?.length && <div className="mt-3 border-t border-slate-700/70 pt-3"><div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-[#9bdac0]">{t('Key evidence', 'الأدلة الرئيسية')}</div><div className="space-y-1.5">{turn.result.answer.key_evidence.map((entry, i) => <div key={i} className="flex flex-wrap justify-between gap-2 text-xs"><span className="text-slate-400">{entry.label}</span><span className="font-medium text-slate-200">{typeof entry.value === 'object' ? t('Aggregate provided', 'تم تقديم قيمة مجمّعة') : String(entry.value ?? '—')}</span></div>)}</div></div>}
                  {!!turn.result.answer.limitations?.length && <div className="mt-3 text-xs text-amber-200/80"><div className="mb-1 font-semibold">{t('Limitations', 'القيود')}</div>{turn.result.answer.limitations.map((item, i) => <p key={i} className="leading-5">· {item}</p>)}</div>}
                  <div className="mt-3 flex items-center gap-1.5 border-t border-slate-700/70 pt-2 text-[10px] text-slate-500"><ShieldCheck size={12} />{t('Local response · no cloud provider', 'استجابة محلية · دون مزود سحابي')}</div>
                </div>}
              </div>)}
            </div>
            <form onSubmit={(event) => void askLocal(event)} className="flex gap-2 border-t border-slate-700/70 bg-[#171a34]/35 p-3 sm:p-4">
              <label className="sr-only" htmlFor="datahub-question">{t('Ask a question about the selected files', 'اطرح سؤالاً حول الملفات المحددة')}</label>
              <input id="datahub-question" value={question} onChange={(event) => setQuestion(event.target.value)} className={inputClass} placeholder={t('Ask about totals, trends or file structure…', 'اسأل عن الإجماليات أو الاتجاهات أو بنية الملفات…')} disabled={!files.length || chatBusy || scenarioBusy} />
              <button type="submit" className={`${primaryButton} shrink-0 px-3 sm:px-4`} disabled={!files.length || !question.trim() || chatBusy || scenarioBusy} aria-label={t('Send question', 'إرسال السؤال')}>{chatBusy ? <LoaderCircle size={16} className="animate-spin" /> : <ArrowUpRight size={16} />}</button>
            </form>
          </section>
        </>}

        <section className="flex flex-col gap-3 rounded-2xl border border-[#5378ac]/25 bg-[#202447]/55 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-2.5"><LockKeyhole size={16} className="mt-0.5 shrink-0 text-[#9db8df]" /><p className="text-xs leading-5 text-slate-400"><strong className="text-slate-300">{t('Provenance & privacy', 'المصدر والخصوصية')}.</strong> {t(`Mode: ${inspection.privacy?.mode ?? 'local'}. Source rows returned: ${inspection.privacy?.source_rows_returned ? 'yes' : 'no'}. Sensitive column values returned: ${inspection.privacy?.sensitive_column_values_returned ? 'yes' : 'no'}. Persisted: ${inspection.privacy?.persisted ? 'yes' : 'no'}.`, `الوضع: ${inspection.privacy?.mode ?? 'محلي'}. أعيدت سجلات المصدر: ${inspection.privacy?.source_rows_returned ? 'نعم' : 'لا'}. أعيدت قيم الأعمدة الحساسة: ${inspection.privacy?.sensitive_column_values_returned ? 'نعم' : 'لا'}. تم الحفظ: ${inspection.privacy?.persisted ? 'نعم' : 'لا'}.`)}</p></div>
          <button type="button" onClick={() => { setFiles([]); setInspection(null); setForecast(null); setTurns([]); setError('') }} disabled={busy !== null || forecastBusy || scenarioBusy || chatBusy} className="btn-ghost shrink-0 border border-slate-700 text-xs"><Trash2 size={14} />{t('Clear session', 'مسح الجلسة')}</button>
        </section>
      </div>}

      <footer className="flex items-center justify-center gap-2 pb-2 text-[10px] text-slate-600"><ShieldCheck size={12} />{t('THRIVE · controlled local data review', 'ثرايف · مراجعة بيانات محلية بضوابط')}</footer>
    </main>
  )
}

export default DataHub
