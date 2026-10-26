/**
 * AI Business Analyst — Phase 37 (capstone) + Phase 44 (agentic Claude-API
 * mode).
 *
 * Natural-language Q&A spanning every HR module and all 6 Business
 * Intelligence domains. Two modes, both real:
 *   - Local (Phase 37, original): fully offline, Ollama-optional, a fixed
 *     query registry, numbers only from real computed metrics.
 *   - Optional cloud agent: Claude tool-use is available only after the user
 *     opts in. Deterministic file analysis works locally without a paid API.
 *
 * SECURITY-CRITICAL UI CONTRACT: every answer renders the actual verified
 * number/table alongside the prose (never prose alone), the mode that
 * answered (cloud agent / local LLM / deterministic fallback / documentation
 * / refused) is always visible, any tool the agent actually invoked is
 * listed as "Actions Taken", and the Evidence Level badge uses this
 * platform's established 🟢/🟡/🔴 convention — never an LLM self-reported
 * confidence score. See backend/core/ai_business_analyst_engine.py's and
 * backend/core/agentic_orchestrator.py's module docstrings for the full
 * trust-boundary architecture this page surfaces.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Send, Upload, X, ShieldCheck, Wifi, Bot, FileText, AlertTriangle,
  Sparkles, BookOpen, ChevronDown, ChevronUp, Wrench, Code2, Download,
  CheckCircle2, XCircle, Lock, Cloud, CloudOff, Zap,
} from 'lucide-react'
import { useLanguage } from '../context/LanguageContext'
import { requestLocalAnalysis } from '../components/analytics/analysisStream'
import { collectReviewSources, OcrFigureReview } from '../components/analytics/OcrFigureReview'
import type { ReviewDetail, ReviewedTable } from '../components/analytics/OcrFigureReview'
import { GovernanceDisclaimer } from '../components/shared/GovernanceDisclaimer'
import { StatusBadge } from '../components/shared/StatusBadge'
import { StatusBanner } from '../components/shared/StatusBanner'

// ── Types (mirror backend/core/ai_business_analyst_engine.py) ─────────────

interface ComputedMetricEvidenceJSON {
  kind: 'computed_metric'
  label: string; value: unknown; unit: string | null
  source_engine: string; data_period: string | null
  evidence_level: 'high' | 'limited' | 'insufficient'
  evidence_level_reason: string
}
interface KnowledgeContextEvidenceJSON {
  kind: 'knowledge_context'
  label: string; excerpt: string; source_file: string
  source_section: string | null; relevance_score: number
}
type EvidenceEntryJSON = ComputedMetricEvidenceJSON | KnowledgeContextEvidenceJSON

interface QueryAuditJSON {
  source_file: string
  operation: 'total' | 'average' | 'count'
  measure: string | null
  currency: string | null
  cohorts: {
    filters: { column: string; operator: string; value: string | number; kind: string }[]
    source_rows: number
    matched_rows: number
    included_rows: number
    excluded_rows: number
    missing_filter_rows: number
    missing_measure_rows: number
    value: number | null
  }[]
}

interface AnalystAnswerJSON {
  answer_text: string
  key_evidence: EvidenceEntryJSON[]
  source_engine: string | null
  data_period: string | null
  evidence_level: 'high' | 'limited' | 'insufficient'
  limitations: string[]
  mode: 'llm' | 'deterministic' | 'rag' | 'rag+llm' | 'refused' | 'unsupported'
  matched_query_id: string | null
  computed_at: string
  query_audit?: QueryAuditJSON | null
}
interface AskResponse {
  answer: AnalystAnswerJSON
  domains_detected: string[]
  files_ingested: string[]
  ollama_reachable: boolean
}
interface RegistryEntry {
  query_id: string; intent: string; domain: string
  keywords: string[]; description_en: string; description_ar: string
}
interface RegistryResponse {
  registry: RegistryEntry[]
  ollama_reachable: boolean
  ollama_model: string
}
// ── Phase 44: agentic Claude-API mode types (mirror the /agentic route) ───

interface CloudStatusJSON {
  configured: boolean; valid: boolean; detail: string; masked_key: string; model: string
}
interface AgenticStatus extends CloudStatusJSON {
  streaming_supported?: boolean
  cloud_configured: boolean; cloud_valid: boolean; cloud_detail: string
  local_fallback_reachable: boolean; tools_available: string[]
}
interface AgenticActionTaken {
  tool_name: string; tool_input: Record<string, unknown>; ok: boolean; summary: string
}
interface GeneratedFileRef { filename: string; download_url: string }
interface LocalFallbackAnswerJSON extends AnalystAnswerJSON { actions_taken: AgenticActionTaken[] }
interface CloudAgentAnswerJSON {
  answer_text: string; mode: string; actions_taken: AgenticActionTaken[]; error: string | null
}
interface AgenticResponse {
  mode: 'cloud' | 'local_fallback'
  cloud_status: CloudStatusJSON
  answer: LocalFallbackAnswerJSON | CloudAgentAnswerJSON
  files_generated: GeneratedFileRef[]
  domains_detected: string[]
  files_ingested: string[]
  file_details?: FileIngestionDetail[]
}
interface FileIngestionDetail extends ReviewDetail {
  filename: string
  source_type?: string
  rows?: number
  columns?: string[]
  warnings?: string[]
  error?: string
  pdf_extraction?: {
    pages: Array<{
      page: number
      method: 'native' | 'ocr' | 'native+ocr'
      confidence: number | null
      low_confidence_numbers: number
    }>
    ocr_languages: string
    requires_numeric_review: boolean
  }
}
interface OcrProgress {
  stage: string
  filename?: string
  page?: number
  total_pages?: number
  method?: string
}
function isLocalFallbackAnswer(a: LocalFallbackAnswerJSON | CloudAgentAnswerJSON): a is LocalFallbackAnswerJSON {
  return 'key_evidence' in a
}

interface ChatTurn {
  id: string
  question: string
  response: AgenticResponse | null
  error: string | null
  loading: boolean
  hasPdf: boolean
  sourceFiles: File[]
  ocrProgress?: OcrProgress | null
}

// ── Phase 43: sandboxed file-editing types (mirror the /edit-file route) ──

interface DiffCellChange { sheet?: string; row?: number; cell?: string; column?: string; old_value: unknown; new_value: unknown }
interface DiffSummaryJSON {
  supported: boolean; changed: boolean
  summary_en: string; summary_ar: string
  cell_changes_sample: DiffCellChange[]
  n_cells_changed: number; n_rows_added: number; n_rows_removed: number
  n_paragraphs_changed: number
}
interface SandboxedEditJSON {
  fulfilled_via: 'sandboxed_code_execution'
  ok: boolean
  run_id?: string
  generated_code?: string | null
  duration_ms?: number
  diff_summary?: DiffSummaryJSON | null
  download_url?: string
  outcome?: string
  error?: string
}
interface GroundedAnswerJSON { fulfilled_via: 'grounded_answer'; answer?: AnalystAnswerJSON; error?: string }
interface EditFileResponse {
  filename: string
  request_split: { question_part: string | null; edit_part: string | null; is_mixed: boolean; is_ambiguous: boolean }
  grounded_answer: GroundedAnswerJSON | null
  sandboxed_edit: SandboxedEditJSON | null
  note?: string
}
interface EditFileStatus { sandbox_available: boolean; code_gen_available: boolean; code_gen_model: string }
interface EditTurn {
  id: string
  filename: string
  instruction: string
  response: EditFileResponse | null
  error: string | null
  loading: boolean
}

const EVIDENCE_BADGE: Record<string, { tone: 'positive' | 'caution' | 'critical'; icon: string }> = {
  high: { tone: 'positive', icon: '🟢' },
  limited: { tone: 'caution', icon: '🟡' },
  insufficient: { tone: 'critical', icon: '🔴' },
}
const MODE_LABEL_EN: Record<string, string> = {
  llm: 'Local LLM', deterministic: 'Deterministic fallback', rag: 'Project documentation',
  'rag+llm': 'Local LLM (from documentation)', tabular: 'Local data analysis',
  document: 'Local PDF text search', refused: 'Trust-boundary refusal', unsupported: 'Not supported',
}
const MODE_LABEL_AR: Record<string, string> = {
  llm: 'نموذج محلي', deterministic: 'احتياطي حتمي', rag: 'وثائق المشروع',
  'rag+llm': 'نموذج محلي (من الوثائق)', tabular: 'تحليل البيانات محلياً',
  document: 'بحث نصي محلي في PDF', refused: 'رفض حدود الثقة', unsupported: 'غير مدعوم',
}

function fmtValue(value: unknown, unit: string | null): string {
  if (value === null || value === undefined) return '—'
  let text: string
  if (typeof value === 'number') text = value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  else if (typeof value === 'boolean') text = value ? 'Yes' : 'No'
  else text = String(value)
  return unit ? `${text} ${unit}` : text
}

export function AIBusinessAnalyst() {
  const { t, isAr } = useLanguage()
  const [mode, setMode] = useState<'ask' | 'edit'>('ask')
  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [files, setFiles] = useState<File[]>([])
  const [useLlm, setUseLlm] = useState(false)
  const [useCloud, setUseCloud] = useState(false)
  const [registry, setRegistry] = useState<RegistryResponse | null>(null)
  const [showRegistry, setShowRegistry] = useState(false)
  const [agenticStatus, setAgenticStatus] = useState<AgenticStatus | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const requestControllersRef = useRef(new Map<string, AbortController>())

  useEffect(() => () => {
    requestControllersRef.current.forEach((controller) => controller.abort())
    requestControllersRef.current.clear()
  }, [])

  // Phase 43: sandboxed file-editing state — deliberately separate state
  // from the Q&A flow above, matching the backend's architectural split.
  const [editStatus, setEditStatus] = useState<EditFileStatus | null>(null)
  const [editFile, setEditFile] = useState<File | null>(null)
  const [instruction, setInstruction] = useState('')
  const [editTurns, setEditTurns] = useState<EditTurn[]>([])
  const editFileInputRef = useRef<HTMLInputElement>(null)
  const editScrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch('/api/local/ai-business-analyst/registry')
      .then((r) => r.json())
      .then((d: RegistryResponse) => setRegistry(d))
      .catch(() => setRegistry(null))
    fetch('/api/local/ai-business-analyst/edit-file/status')
      .then((r) => r.json())
      .then((d: EditFileStatus) => setEditStatus(d))
      .catch(() => setEditStatus(null))
    fetch('/api/local/ai-business-analyst/agentic/status')
      .then((r) => r.json())
      .then((d: AgenticStatus) => setAgenticStatus(d))
      .catch(() => setAgenticStatus(null))
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? [])
    if (picked.length) setFiles((prev) => [...prev, ...picked])
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [])

  const removeFile = useCallback((name: string) => {
    setFiles((prev) => prev.filter((f) => f.name !== name))
  }, [])

  const runQuestion = useCallback(async (q: string, selectedFiles: File[], reviews: ReviewedTable[] = []) => {
    q = q.trim()
    if (!q) return
    const turnId = crypto.randomUUID()
    const hasPdf = selectedFiles.some((file) => file.name.toLowerCase().endsWith('.pdf'))
    setTurns((prev) => [...prev, { id: turnId, question: q, response: null, error: null, loading: true, hasPdf, sourceFiles: selectedFiles, ocrProgress: null }])

    const controller = new AbortController()
    requestControllersRef.current.set(turnId, controller)
    try {
      // The endpoint stays local by default. Cloud processing is selected
      // explicitly and disclosed in the form before uploaded files are sent.
      const formData = new FormData()
      formData.append('question', q)
      formData.append('use_llm', String(useLlm))
      formData.append('use_cloud', String(reviews.length ? false : useCloud))
      if (reviews.length) formData.append('reviewed_tables', JSON.stringify(reviews))
      selectedFiles.forEach((file) => formData.append('files', file))
      const data = await requestLocalAnalysis<AgenticResponse>(formData, {
        streaming: agenticStatus?.streaming_supported === true,
        signal: controller.signal,
        onProgress: (progress) => {
          setTurns((prev) => prev.map((turn) => turn.id === turnId ? { ...turn, ocrProgress: { ...turn.ocrProgress, ...progress } } : turn))
        },
      })
      setTurns((prev) => prev.map((tn) => (tn.id === turnId ? { ...tn, response: data, loading: false } : tn)))
    } catch (err) {
      setTurns((prev) => prev.map((tn) => (tn.id === turnId ? { ...tn, error: err instanceof Error ? err.message : String(err), loading: false } : tn)))
    } finally {
      requestControllersRef.current.delete(turnId)
    }
  }, [useLlm, useCloud, agenticStatus])

  const ask = useCallback(async () => {
    const q = question.trim()
    if (!q) return
    setQuestion('')
    await runQuestion(q, files)
  }, [question, files, runQuestion])

  // Phase 43: sandboxed file-editing submit — a completely separate request
  // to a separate endpoint, never reusing `ask`'s call above.
  const runEdit = useCallback(async () => {
    const instr = instruction.trim()
    if (!instr || !editFile) return
    const turnId = `${Date.now()}`
    setEditTurns((prev) => [...prev, { id: turnId, filename: editFile.name, instruction: instr, response: null, error: null, loading: true }])
    setInstruction('')

    try {
      const formData = new FormData()
      formData.append('instruction', instr)
      formData.append('file', editFile)
      const res = await fetch('/api/local/ai-business-analyst/edit-file', { method: 'POST', body: formData })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data?.detail || `Server error (${res.status})`)
      }
      const data = (await res.json()) as EditFileResponse
      setEditTurns((prev) => prev.map((tn) => (tn.id === turnId ? { ...tn, response: data, loading: false } : tn)))
    } catch (err) {
      setEditTurns((prev) => prev.map((tn) => (tn.id === turnId ? { ...tn, error: err instanceof Error ? err.message : String(err), loading: false } : tn)))
    }
  }, [instruction, editFile])

  useEffect(() => {
    editScrollRef.current?.scrollTo({ top: editScrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [editTurns])

  return (
    <div className="space-y-7">
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-headline text-slate-900 dark:text-white flex items-center gap-2">
          <Bot size={26} className="text-blue-500" />
          {t('AI Business Analyst', 'المحلل التجاري الذكي')}
        </h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
          {t(
            'Ask a question about your uploaded HR or Business Intelligence data, or about how this platform works.',
            'اسأل سؤالاً عن بيانات الموارد البشرية أو ذكاء الأعمال المُحمّلة، أو عن كيفية عمل هذه المنصة.'
          )}
        </p>
      </motion.div>

      <div className="flex flex-wrap items-center gap-2">
        {useCloud && agenticStatus?.cloud_configured ? (
          <StatusBanner tone="caution" compact>
            <div className="flex items-center gap-1.5">
              <Cloud size={14} />
              {t(
                'Optional cloud AI is selected. Submitting this question will validate and contact the configured provider; the question and uploaded files may be sent externally.',
                'تم اختيار الذكاء الاصطناعي السحابي الاختياري. عند الإرسال سيجري التحقق والاتصال بالمزوّد المُعدّ؛ وقد يُرسل السؤال والملفات خارجياً.'
              )}
            </div>
          </StatusBanner>
        ) : (
          <StatusBanner tone="informational" compact>
            <div className="flex items-center gap-1.5">
              <ShieldCheck size={14} />
              {t('Local mode: calculations and document search run on this server without a paid AI API. An external AI provider is contacted only if you explicitly select cloud mode.', 'الوضع المحلي: تُجرى الحسابات والبحث في المستندات على هذا الخادم من دون واجهة ذكاء اصطناعي مدفوعة. لا يُتصل بمزوّد خارجي إلا عند اختيار الوضع السحابي صراحة.')}
            </div>
          </StatusBanner>
        )}
        {agenticStatus && (
          agenticStatus.cloud_valid && useCloud ? (
            <StatusBadge tone="caution"><Zap size={12} className="inline mr-1" />{t(`Cloud agent active (${agenticStatus.model})`, `الوكيل السحابي نشط (${agenticStatus.model})`)}</StatusBadge>
          ) : agenticStatus.cloud_configured ? (
            <StatusBadge tone="neutral"><CloudOff size={12} className="inline mr-1" />{t(agenticStatus.cloud_detail, agenticStatus.cloud_detail)}</StatusBadge>
          ) : null
        )}
        {registry && (
          registry.ollama_reachable ? (
            <StatusBadge tone="positive"><Wifi size={12} className="inline mr-1" />{t(`Local LLM connected (${registry.ollama_model})`, `نموذج محلي متصل (${registry.ollama_model})`)}</StatusBadge>
          ) : (
            <StatusBadge tone="neutral"><ShieldCheck size={12} className="inline mr-1" />{t('Local analytics ready — no AI API or local model required', 'التحليل المحلي جاهز — لا يتطلب واجهة ذكاء اصطناعي أو نموذجاً محلياً')}</StatusBadge>
          )
        )}
      </div>

      {agenticStatus && agenticStatus.tools_available.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-slate-400">
          <span className="font-semibold uppercase tracking-wide">{t('Action tools available:', 'أدوات الإجراءات المتاحة:')}</span>
          {agenticStatus.tools_available.map((tool) => (
            <span key={tool} className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">{tool}</span>
          ))}
        </div>
      )}

      {/* Phase 43: mode switcher — visually distinct tabs matching the
          backend's two architecturally separate paths (grounded Q&A vs.
          sandboxed code execution), never blended into one flow. */}
      <div className="flex gap-1 border-b border-slate-200 dark:border-slate-700">
        <button
          onClick={() => setMode('ask')}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${mode === 'ask' ? 'border-blue-500 text-blue-600 dark:text-blue-400' : 'border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'}`}
        >
          <Bot size={14} />{t('Ask a Question', 'اطرح سؤالاً')}
        </button>
        <button
          onClick={() => setMode('edit')}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${mode === 'edit' ? 'border-blue-500 text-blue-600 dark:text-blue-400' : 'border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'}`}
        >
          <Wrench size={14} />{t('Edit a File', 'تعديل ملف')}
        </button>
      </div>

      {mode === 'ask' && (
      <>
      <div className="card p-4 space-y-3">
        <button onClick={() => setShowRegistry((s) => !s)} className="flex items-center gap-2 text-sm font-medium text-slate-600 dark:text-slate-300">
          <BookOpen size={16} />
          {t('What can I ask?', 'ماذا يمكنني أن أسأل؟')}
          {showRegistry ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
        <AnimatePresence>
          {showRegistry && registry && (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
              <p className="text-xs text-slate-400 mb-2">
                {t('Only these registered queries are answered from real data — every question is matched against this fixed list, never freely computed.', 'يُجاب فقط على هذه الاستعلامات المُسجّلة من بيانات حقيقية.')}
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 max-h-64 overflow-y-auto">
                {registry.registry.map((entry) => (
                  <button key={entry.query_id} onClick={() => setQuestion(isAr ? entry.description_ar : entry.description_en)}
                    className="text-left text-xs px-3 py-2 rounded-lg bg-slate-50 dark:bg-slate-800/60 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors">
                    <span className="font-medium text-slate-700 dark:text-slate-300">{isAr ? entry.description_ar : entry.description_en}</span>
                    <span className="block text-slate-400 mt-0.5">{entry.domain} · {entry.intent}</span>
                  </button>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="card p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">{t('Optional: upload data to ask about', 'اختياري: حمّل بيانات للسؤال عنها')}</span>
        </div>
        <p className="text-[11px] text-slate-400">
          {t('Excel includes all non-empty sheets. Scanned PDFs use offline Arabic + English OCR on this server—no paid API. Uncertain figures must be verified against a corrected source before calculations.', 'يشمل Excel كل الأوراق غير الفارغة. تُحلَّل ملفات PDF الممسوحة ضوئياً محلياً وبلا إنترنت باستخدام OCR للعربية والإنجليزية، من دون واجهة مدفوعة. يجب التحقق من الأرقام غير المؤكدة بمصدر مُصحح قبل إجراء الحسابات.')}
        </p>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {t('Use exact column names. For filters, use the explicit English syntax below with your own column names and values. Dates must be YYYY-MM-DD; category values are case-sensitive. Add from "exact-file.csv" before where when multiple files or sheets are uploaded. Supported: total, average, count records; =, !=, >, >=, <, <=; join filters with and.', 'استخدم أسماء الأعمدة الفعلية. للتصفية، استخدم الصيغة الإنجليزية الصريحة أدناه مع أسماء أعمدتك وقيمك. يجب أن تكون التواريخ بصيغة YYYY-MM-DD؛ قيم الفئات حساسة لحالة الأحرف. أضف from "exact-file.csv" قبل where عند رفع ملفات أو أوراق متعددة. العمليات المدعومة: total وaverage وcount records؛ المعاملات = و!= و> و>= و< و<=؛ اربط الشروط باستخدام and.')}
          <code dir="ltr" className="block text-xs mt-2 whitespace-pre-wrap">{'total "Net Sales" where "Department" = "Retail" and "Date" >= "2025-01-01"\ncompare total "Net Sales" where "Department" = "Retail" versus "Department" = "Online"'}</code>
        </p>
        <div className="flex flex-wrap gap-4 text-xs text-slate-500 dark:text-slate-400">
          <label className={`flex items-center gap-1.5 ${registry?.ollama_reachable ? 'cursor-pointer' : 'cursor-not-allowed opacity-70'}`} title={t('Optional local Ollama rephrasing; deterministic calculations work without it.', 'إعادة صياغة اختيارية باستخدام Ollama محلياً؛ تعمل الحسابات الحتمية من دونه.')}>
            <input type="checkbox" checked={useLlm} disabled={!registry?.ollama_reachable} onChange={(e) => setUseLlm(e.target.checked)} />
            {t('Use local Ollama for optional phrasing', 'استخدام Ollama المحلي للصياغة الاختيارية')}
          </label>
          <label className={`flex items-center gap-1.5 ${agenticStatus?.cloud_configured ? 'cursor-pointer' : 'cursor-not-allowed opacity-70'}`}>
            <input type="checkbox" checked={useCloud} disabled={!agenticStatus?.cloud_configured} onChange={(e) => setUseCloud(e.target.checked)} />
            {t('Use optional external AI (sends this question and files to the provider)', 'استخدام ذكاء اصطناعي خارجي اختياري (يرسل السؤال والملفات إلى المزوّد)')}
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          {files.map((f) => (
            <span key={f.name} className="text-xs flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
              <FileText size={12} />{f.name}
              <button onClick={() => removeFile(f.name)}><X size={12} /></button>
            </span>
          ))}
          <label className="text-xs flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-dashed border-slate-300 dark:border-slate-600 text-slate-500 cursor-pointer hover:border-blue-400">
            <input ref={fileInputRef} type="file" multiple accept=".xlsx,.xls,.csv,.parquet,.json,.pdf" onChange={handleFileSelect} className="hidden" />
            <Upload size={12} />{t('Add file(s)', 'إضافة ملف')}
          </label>
        </div>
      </div>

      <div ref={scrollRef} className="space-y-4 max-h-[60vh] overflow-y-auto pr-1">
        {turns.length === 0 && (
          <div className="text-center py-10 text-sm text-slate-400">
            {t('Ask a question below to get started.', 'اطرح سؤالاً أدناه للبدء.')}
          </div>
        )}
        {turns.map((turn) => (
          <div key={turn.id} className="space-y-2">
            <div className="flex justify-end">
              <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-blue-600 text-white px-4 py-2.5 text-sm">{turn.question}</div>
            </div>
            {turn.loading && (
              <div className="flex flex-col items-start gap-1.5 text-xs text-slate-400" aria-live="polite">
                <div className="flex items-center gap-2">
                  <Sparkles size={12} className="animate-pulse" />
                  {turn.ocrProgress
                    ? ocrStageLabel(turn.ocrProgress.stage, t)
                    : t('Uploading files and connecting to live processing…', 'تحميل الملفات والاتصال بالمعالجة المباشرة…')}
                </div>
                {turn.ocrProgress?.filename && (
                  <div className="ml-5 text-[11px] text-slate-500 dark:text-slate-400">
                    <span>{turn.ocrProgress.filename}</span>
                    {turn.ocrProgress.page != null && turn.ocrProgress.total_pages != null && (
                      <span className="ml-2 font-mono">
                        {t('Page', 'الصفحة')} {turn.ocrProgress.page} {t('of', 'من')} {turn.ocrProgress.total_pages}
                      </span>
                    )}
                    {turn.ocrProgress.method && <span className="ml-2">{turn.ocrProgress.method}</span>}
                  </div>
                )}
              </div>
            )}
            {turn.error && <StatusBanner tone="critical" compact>{turn.error}</StatusBanner>}
            {turn.response && <AgenticAnswerCard response={turn.response} t={t} isAr={isAr} />}
            {turn.response && collectReviewSources(turn.response.file_details ?? []).map((source) => {
              const file = turn.sourceFiles.find((candidate) => candidate.name === source.source_filename)
              return <OcrFigureReview key={source.source_id} source={source} file={file} originalQuestion={turn.question}
                onSubmit={async (table, reviewQuestion) => { if (file) await runQuestion(reviewQuestion, [file], [table]) }} />
            })}
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') void ask() }}
          placeholder={t('e.g. What is our total revenue?', 'مثال: ما هو إجمالي إيراداتنا؟')}
          className="flex-1 px-4 py-2.5 rounded-xl border border-slate-200 dark:border-navy-500/60 bg-white dark:bg-navy-700 text-sm text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-400"
        />
        <button onClick={() => void ask()} className="p-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white">
          <Send size={18} />
        </button>
      </div>
      </>
      )}

      {mode === 'edit' && (
      <>
      <StatusBanner tone="informational" compact>
        <div className="flex items-start gap-1.5">
          <Lock size={14} className="flex-shrink-0 mt-0.5" />
          <span>
            {t(
              'File edits run entirely locally in an isolated sandbox process — no network access, no access to any file outside a temporary working copy, and hard memory/CPU/time limits enforced by the operating system itself. The generated code is always shown below, and the original file is never modified.',
              'تعمل تعديلات الملفات محلياً بالكامل داخل عملية معزولة — بلا اتصال شبكي، وبلا وصول لأي ملف خارج نسخة عمل مؤقتة، مع حدود صارمة للذاكرة والمعالج والوقت يفرضها نظام التشغيل نفسه. يُعرض الكود المُولَّد دائماً أدناه، ولا يُعدَّل الملف الأصلي أبداً.'
            )}
          </span>
        </div>
      </StatusBanner>

      {editStatus && !editStatus.sandbox_available && (
        <StatusBanner tone="critical" compact>
          {t('Sandboxed execution is unavailable on this machine (Windows Job Objects not installed) — file editing is disabled until this is resolved.', 'التنفيذ المعزول غير متاح على هذا الجهاز — تعديل الملفات معطّل حتى يُحل ذلك.')}
        </StatusBanner>
      )}
      {editStatus && editStatus.sandbox_available && !editStatus.code_gen_available && (
        <StatusBanner tone="caution" compact>
          {t(`Local code-generation model (${editStatus.code_gen_model}) is not reachable — start Ollama to enable file editing.`, `نموذج توليد الكود المحلي (${editStatus.code_gen_model}) غير متاح — شغّل Ollama لتفعيل تعديل الملفات.`)}
        </StatusBanner>
      )}

      <div className="card p-4 space-y-3">
        <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">{t('File to edit', 'الملف المراد تعديله')}</span>
        {editFile ? (
          <span className="text-xs flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 w-fit">
            <FileText size={12} />{editFile.name}
            <button onClick={() => setEditFile(null)}><X size={12} /></button>
          </span>
        ) : (
          <label className="text-xs flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-dashed border-slate-300 dark:border-slate-600 text-slate-500 cursor-pointer hover:border-blue-400 w-fit">
            <input ref={editFileInputRef} type="file" accept=".xlsx,.xls,.csv,.docx,.pptx" onChange={(e) => { const f = e.target.files?.[0]; if (f) setEditFile(f); if (editFileInputRef.current) editFileInputRef.current.value = '' }} className="hidden" />
            <Upload size={12} />{t('Choose file', 'اختر ملفاً')}
          </label>
        )}
      </div>

      <div ref={editScrollRef} className="space-y-4 max-h-[60vh] overflow-y-auto pr-1">
        {editTurns.length === 0 && (
          <div className="text-center py-10 text-sm text-slate-400">
            {t('Upload a file above, then describe the edit you want below.', 'حمّل ملفاً أعلاه، ثم صف التعديل المطلوب أدناه.')}
          </div>
        )}
        {editTurns.map((turn) => (
          <div key={turn.id} className="space-y-2">
            <div className="flex justify-end">
              <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-blue-600 text-white px-4 py-2.5 text-sm">
                <span className="block text-[11px] text-blue-200 mb-0.5">{turn.filename}</span>
                {turn.instruction}
              </div>
            </div>
            {turn.loading && (
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <Sparkles size={12} className="animate-pulse" />{t('Generating and running code in the sandbox…', 'جارٍ توليد وتنفيذ الكود في البيئة المعزولة…')}
              </div>
            )}
            {turn.error && <StatusBanner tone="critical" compact>{turn.error}</StatusBanner>}
            {turn.response && <EditResultCard response={turn.response} t={t} isAr={isAr} />}
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <input
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') void runEdit() }}
          placeholder={t('e.g. Add a column that multiplies Quantity by UnitPrice', 'مثال: أضف عموداً يضرب الكمية في سعر الوحدة')}
          disabled={!editFile}
          className="flex-1 px-4 py-2.5 rounded-xl border border-slate-200 dark:border-navy-500/60 bg-white dark:bg-navy-700 text-sm text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:opacity-50"
        />
        <button onClick={() => void runEdit()} disabled={!editFile} className="p-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white">
          <Send size={18} />
        </button>
      </div>
      </>
      )}

      <GovernanceDisclaimer compact />
    </div>
  )
}

function AnswerCard({ response, t, isAr }: { response: AskResponse; t: (en: string, ar: string) => string; isAr: boolean }) {
  const a = response.answer
  const badge = EVIDENCE_BADGE[a.evidence_level] ?? EVIDENCE_BADGE.insufficient
  const modeLabel = isAr ? MODE_LABEL_AR[a.mode] : MODE_LABEL_EN[a.mode]

  return (
    <div className="max-w-[92%] card p-4 space-y-3 border-l-4" style={{ borderLeftColor: a.mode === 'refused' ? '#dc2626' : a.evidence_level === 'high' ? '#059669' : a.evidence_level === 'limited' ? '#d97706' : '#dc2626' }}>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <StatusBadge tone={badge.tone}>{badge.icon} {t(a.evidence_level === 'high' ? 'High Evidence' : a.evidence_level === 'limited' ? 'Limited Evidence' : 'Insufficient Data', a.evidence_level === 'high' ? 'أدلة قوية' : a.evidence_level === 'limited' ? 'أدلة محدودة' : 'بيانات غير كافية')}</StatusBadge>
          <span className="text-[11px] text-slate-400">{modeLabel}</span>
        </div>
        {a.mode === 'refused' && <AlertTriangle size={16} className="text-red-500" />}
      </div>

      {/* 1. Answer */}
      <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">{a.answer_text}</p>

      {a.query_audit && (
        <section className="rounded-lg bg-slate-50 dark:bg-slate-800 p-3 space-y-2 text-xs" aria-label={t('Applied filters', 'التصفية المطبقة')}>
          <h4 className="font-semibold">{t('Applied filters', 'التصفية المطبقة')}</h4>
          <p>{t('Source', 'المصدر')}: {a.query_audit.source_file} · {a.query_audit.measure ?? t('Record count', 'عدد السجلات')}{a.query_audit.currency ? ` · ${t('Source currency context', 'عملة المصدر')}: ${a.query_audit.currency}` : ''}</p>
          {a.query_audit.cohorts.map((cohort, i) => (
            <div key={i} className="space-y-1">
              <p className="font-medium">{a.query_audit!.cohorts.length > 1 ? `${t('Cohort', 'المجموعة')} ${i + 1}` : t('Selected rows', 'الصفوف المختارة')}</p>
              <ul className="list-disc list-inside">
                {cohort.filters.map((filter, j) => <li key={j}><bdi>{filter.column} {filter.operator} {typeof filter.value === 'string' ? `"${filter.value}"` : filter.value}</bdi></li>)}
              </ul>
              <p>{t('Included', 'المشمولة')}: {cohort.included_rows} / {cohort.source_rows} · {t('Excluded', 'المستبعدة')}: {cohort.excluded_rows}</p>
              <p className="text-slate-500 dark:text-slate-400">{t('Missing filter values (source rows)', 'قيم تصفية مفقودة (صفوف المصدر)')}: {cohort.missing_filter_rows} · {t('Missing measure values (matched rows)', 'قيم المقياس المفقودة (الصفوف المطابقة)')}: {cohort.missing_measure_rows}</p>
            </div>
          ))}
          <p className="text-slate-500 dark:text-slate-400">{t('All filters within a cohort must match. Missing filter values are excluded, even for !=. Cohorts may overlap; their counts must not be added. No currency conversion is performed.', 'يجب تطابق جميع الشروط داخل المجموعة. تُستبعد قيم التصفية المفقودة حتى مع !=. قد تتداخل المجموعات؛ لا تجمع أعدادها. لا يتم تحويل العملات.')}</p>
        </section>
      )}

      {/* 2. Key Evidence — the actual number/table, not prose alone */}
      {a.key_evidence.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">{t('Key Evidence', 'الأدلة الرئيسية')}</p>
          <div className="rounded-lg border border-slate-100 dark:border-slate-800 overflow-hidden">
            <table className="w-full text-xs">
              <tbody>
                {a.key_evidence.map((e, i) => (
                  <tr key={i} className="border-b border-slate-100 dark:border-slate-800 last:border-0">
                    <td className="px-3 py-2 text-slate-500 dark:text-slate-400 align-top">{e.label}</td>
                    <td className="px-3 py-2 text-right font-mono text-slate-700 dark:text-slate-300 align-top">
                      {e.kind === 'computed_metric' ? fmtValue(e.value, e.unit) : (
                        <span className="block text-left font-sans text-slate-600 dark:text-slate-400 whitespace-pre-wrap">
                          <span className="text-[10px] text-slate-400 block">{e.source_file}{e.source_section ? ` — ${e.source_section}` : ''} · {t('relevance', 'الصلة')} {e.relevance_score}</span>
                          {e.excerpt.slice(0, 300)}{e.excerpt.length > 300 ? '…' : ''}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 3 & 4. Source Engine / Data Period */}
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-slate-400">
        {a.source_engine && <span><strong className="text-slate-500 dark:text-slate-300">{t('Source Engine', 'المحرك المصدر')}:</strong> {a.source_engine}</span>}
        {a.data_period && <span><strong className="text-slate-500 dark:text-slate-300">{t('Data Period', 'فترة البيانات')}:</strong> {a.data_period}</span>}
        {response.domains_detected.length > 0 && <span><strong className="text-slate-500 dark:text-slate-300">{t('Domains detected', 'المجالات المكتشفة')}:</strong> {response.domains_detected.join(', ')}</span>}
      </div>

      {/* 6. Limitations */}
      {a.limitations.length > 0 && (
        <div className="text-[11px] text-amber-600 dark:text-amber-400 space-y-0.5">
          {a.limitations.map((lim, i) => <div key={i}>⚠ {lim}</div>)}
        </div>
      )}
    </div>
  )
}

// ── Phase 44: wraps every /agentic response. For mode='local_fallback' this
// reuses AnswerCard's exact existing 6-part rendering (the `answer` there IS
// Phase 37's AnalystAnswerJSON shape, just with an added, always-empty
// `actions_taken`) — local mode looks and behaves identically to before this
// phase. For mode='cloud' it renders the new 7-part layout: mode badge,
// answer text, Actions Taken (every tool the agent actually invoked, with
// its real result — never a claimed action with nothing behind it), and any
// generated file with a real download link. ──────────────────────────────

function AgenticAnswerCard({ response, t, isAr }: { response: AgenticResponse; t: (en: string, ar: string) => string; isAr: boolean }) {
  const { mode, answer, files_generated, domains_detected, files_ingested } = response
  const fileDetails = response.file_details ?? []

  if (mode === 'local_fallback' && isLocalFallbackAnswer(answer)) {
    return (
      <div className="space-y-1.5">
        <FileIngestionSummary files={fileDetails} t={t} />
        <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide flex items-center gap-1"><ShieldCheck size={11} />{t('Answered locally', 'أُجيب محلياً')}</span>
        <AnswerCard response={{ answer, domains_detected, files_ingested, ollama_reachable: true }} t={t} isAr={isAr} />
      </div>
    )
  }

  const cloudAnswer = answer as CloudAgentAnswerJSON
  return (
    <div className="max-w-[92%] card p-4 space-y-3 border-l-4" style={{ borderLeftColor: cloudAnswer.error ? '#dc2626' : '#7c3aed' }}>
      <FileIngestionSummary files={fileDetails} t={t} />
      <div className="flex items-center justify-between flex-wrap gap-2">
        <StatusBadge tone="caution"><Cloud size={12} className="inline mr-1" />{t('Cloud Agent (Claude)', 'الوكيل السحابي (Claude)')}</StatusBadge>
        {cloudAnswer.error && <AlertTriangle size={16} className="text-red-500" />}
      </div>

      {/* 1. Answer */}
      <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed whitespace-pre-wrap">{cloudAnswer.answer_text}</p>

      {cloudAnswer.error && <StatusBanner tone="caution" compact>{cloudAnswer.error}</StatusBanner>}

      {/* 7. Actions Taken — every real tool call, never a claimed action with nothing behind it */}
      {cloudAnswer.actions_taken.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">{t('Actions Taken', 'الإجراءات المُتخذة')}</p>
          <div className="space-y-1">
            {cloudAnswer.actions_taken.map((act, i) => (
              <div key={i} className="flex items-start gap-1.5 text-xs">
                {act.ok ? <CheckCircle2 size={13} className="text-emerald-500 flex-shrink-0 mt-0.5" /> : <XCircle size={13} className="text-red-500 flex-shrink-0 mt-0.5" />}
                <span className="text-slate-600 dark:text-slate-400"><span className="font-mono text-slate-400">{act.tool_name}</span> — {act.summary}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Generated files, with real download links */}
      {files_generated.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {files_generated.map((f) => (
            <a key={f.download_url} href={f.download_url} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 hover:bg-blue-700 text-white">
              <Download size={12} />{f.filename}
            </a>
          ))}
        </div>
      )}

      {domains_detected.length > 0 && (
        <p className="text-[11px] text-slate-400"><strong className="text-slate-500 dark:text-slate-300">{t('Domains detected', 'المجالات المكتشفة')}:</strong> {domains_detected.join(', ')}</p>
      )}
    </div>
  )
}

function FileIngestionSummary({ files, t }: { files: FileIngestionDetail[]; t: (en: string, ar: string) => string }) {
  if (!files.length) return null
  return (
    <div className="space-y-2" aria-live="polite">
      {files.map((file, index) => (
        <div key={`${file.filename}-${index}`} className="rounded-lg border border-slate-100 dark:border-slate-800 p-3 text-xs">
          <div className="flex flex-wrap items-center gap-2 text-slate-600 dark:text-slate-300">
            <FileText size={13} />
            <span className="font-medium">{file.filename}</span>
            {file.rows !== undefined && <span className="text-slate-400">{file.rows.toLocaleString()} {t('rows', 'صف')}</span>}
          </div>
          {file.error && <p className="mt-1 text-red-600 dark:text-red-400">{file.error}</p>}
          {file.columns && file.columns.length > 0 && (
            <p className="mt-1 text-slate-400">
              {t('Columns', 'الأعمدة')}: {file.columns.slice(0, 12).join(', ')}
              {file.columns.length > 12 ? `, +${file.columns.length - 12}` : ''}
            </p>
          )}
          {file.pdf_extraction && (
            <div className="mt-2 space-y-2 rounded-md bg-slate-50 dark:bg-slate-800/50 p-2.5">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500 dark:text-slate-400">
                <span>{t('Offline OCR languages', 'لغات OCR المحلي')}: {file.pdf_extraction.ocr_languages}</span>
                <span>{t('No paid API used', 'لم تُستخدم واجهة مدفوعة')}</span>
              </div>
              {file.pdf_extraction.pages.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {file.pdf_extraction.pages.map((page) => (
                    <span key={page.page} className="inline-flex items-center gap-1 rounded-md border border-slate-200 dark:border-slate-700 px-2 py-1 text-[10px] text-slate-600 dark:text-slate-300">
                      <span className="font-mono">{t('Page', 'الصفحة')} {page.page}</span>
                      <span>· {pdfMethodLabel(page.method, t)}</span>
                      <span>· {t('confidence', 'الثقة')} {page.confidence == null
                        ? t('not reported', 'غير متاحة')
                        : `${page.confidence.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`}</span>
                      {page.low_confidence_numbers > 0 && (
                        <span className="text-amber-700 dark:text-amber-300">
                          · {page.low_confidence_numbers} {t('uncertain numeric tokens', 'رموز رقمية غير مؤكدة')}
                        </span>
                      )}
                    </span>
                  ))}
                </div>
              )}
              {(file.pdf_extraction.requires_numeric_review || file.pdf_extraction.pages.some((page) => page.low_confidence_numbers > 0)) && (
                <p className="flex items-start gap-1.5 text-[11px] text-amber-700 dark:text-amber-300">
                  <AlertTriangle size={13} className="mt-0.5 flex-shrink-0" />
                  <span>{t(
                    'Some figures need human review. Verify them against a corrected, authoritative source before using them in calculations. Only the count is shown here; OCR token text is not displayed.',
                    'تحتاج بعض الأرقام إلى مراجعة بشرية. تحقّق منها بمصدر موثوق ومُصحح قبل استخدامها في الحسابات. يُعرض العدد فقط ولا يُعرض نص الرموز المستخرجة.'
                  )}</span>
                </p>
              )}
            </div>
          )}
          {file.warnings?.map((warning, warningIndex) => (
            <p key={warningIndex} className="mt-1 text-amber-600 dark:text-amber-400">{warning}</p>
          ))}
        </div>
      ))}
    </div>
  )
}

function pdfMethodLabel(method: 'native' | 'ocr' | 'native+ocr', t: (en: string, ar: string) => string) {
  if (method === 'native') return t('Native text', 'نص أصلي')
  if (method === 'native+ocr') return t('Native + OCR', 'نص أصلي + OCR')
  return t('OCR', 'OCR')
}

function ocrStageLabel(stage: string, t: (en: string, ar: string) => string) {
  const messages: Record<string, [string, string]> = {
    parsing: ['Preparing PDF', 'جارٍ تجهيز PDF'],
    extracting: ['Extracting PDF pages', 'جارٍ استخراج صفحات PDF'],
    governance: ['Checking extraction governance', 'جارٍ التحقق من ضوابط الاستخراج'],
    standard: ['Running local analysis through the standard API', 'جارٍ تشغيل التحليل المحلي عبر الواجهة القياسية'],
    compatibility: ['Live progress is unavailable on this worker; continuing through the standard local API', 'التقدم المباشر غير متاح على هذا الخادم؛ جارٍ المتابعة عبر واجهة التحليل المحلي القياسية'],
    analyzing: ['Computing local analytics', 'جارٍ حساب التحليلات محلياً'],
    answering: ['Preparing the evidence-based answer', 'جارٍ إعداد الإجابة المبنية على الأدلة'],
    complete: ['PDF extraction complete', 'اكتمل استخراج PDF'],
    failed: ['PDF extraction failed', 'فشل استخراج PDF'],
  }
  const message = messages[stage]
  return message ? t(message[0], message[1]) : t('Processing PDF locally', 'جارٍ معالجة PDF محلياً')
}

// ── Phase 43: sandboxed edit result — always shows WHICH path fulfilled the
// request (grounded answer / sandboxed code execution), the independently-
// computed diff (never the LLM's own claim), and a way to inspect the
// exact code that ran, consistent with this platform's whole-session
// transparency discipline. ──────────────────────────────────────────────

function EditResultCard({ response, t, isAr }: { response: EditFileResponse; t: (en: string, ar: string) => string; isAr: boolean }) {
  const [showCode, setShowCode] = useState(false)
  const { grounded_answer, sandboxed_edit, request_split } = response

  return (
    <div className="max-w-[92%] space-y-3">
      {request_split.is_mixed && (
        <StatusBanner tone="informational" compact>
          {t('This request had both a question and an edit — each was routed to its own path below.', 'تضمّن هذا الطلب سؤالاً وتعديلاً معاً — وُجِّه كل منهما إلى مساره الخاص أدناه.')}
        </StatusBanner>
      )}
      {response.note && <StatusBanner tone="caution" compact>{response.note}</StatusBanner>}

      {grounded_answer?.answer && (
        <div>
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5 flex items-center gap-1.5"><Bot size={12} />{t('Fulfilled via: Grounded Answer', 'أُنجز عبر: إجابة موثّقة')}</p>
          <AnswerCard response={{ answer: grounded_answer.answer, domains_detected: [], files_ingested: [], ollama_reachable: true }} t={t} isAr={isAr} />
        </div>
      )}
      {grounded_answer?.error && <StatusBanner tone="critical" compact>{grounded_answer.error}</StatusBanner>}

      {sandboxed_edit && (
        <div className="card p-4 space-y-3 border-l-4" style={{ borderLeftColor: sandboxed_edit.ok ? '#059669' : '#dc2626' }}>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <StatusBadge tone={sandboxed_edit.ok ? 'positive' : 'critical'}>
                <Wrench size={12} className="inline mr-1" />{t('Fulfilled via: Sandboxed Code Execution', 'أُنجز عبر: تنفيذ كود معزول')}
              </StatusBadge>
              {sandboxed_edit.ok ? <CheckCircle2 size={16} className="text-emerald-500" /> : <XCircle size={16} className="text-red-500" />}
            </div>
            {sandboxed_edit.duration_ms != null && (
              <span className="text-[11px] text-slate-400">{(sandboxed_edit.duration_ms / 1000).toFixed(2)}s</span>
            )}
          </div>

          {!sandboxed_edit.ok && (
            <StatusBanner tone="critical" compact>{sandboxed_edit.error}</StatusBanner>
          )}

          {sandboxed_edit.ok && sandboxed_edit.diff_summary && (
            <div className="space-y-1.5">
              <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">{t('What actually changed', 'ما الذي تغيّر فعلياً')}</p>
              <p className="text-sm text-slate-700 dark:text-slate-300">
                {isAr ? sandboxed_edit.diff_summary.summary_ar : sandboxed_edit.diff_summary.summary_en}
              </p>
              {sandboxed_edit.diff_summary.cell_changes_sample.length > 0 && (
                <div className="rounded-lg border border-slate-100 dark:border-slate-800 overflow-hidden overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead><tr className="border-b border-slate-100 dark:border-slate-800 text-left">
                      <th className="px-3 py-1.5 text-slate-400">{t('Location', 'الموقع')}</th>
                      <th className="px-3 py-1.5 text-slate-400 text-right">{t('Before', 'قبل')}</th>
                      <th className="px-3 py-1.5 text-slate-400 text-right">{t('After', 'بعد')}</th>
                    </tr></thead>
                    <tbody>
                      {sandboxed_edit.diff_summary.cell_changes_sample.slice(0, 10).map((c, i) => (
                        <tr key={i} className="border-b border-slate-100 dark:border-slate-800 last:border-0">
                          <td className="px-3 py-1.5 font-mono text-slate-500">{c.cell ?? c.column ?? '—'}</td>
                          <td className="px-3 py-1.5 text-right font-mono text-slate-500">{String(c.old_value ?? '—')}</td>
                          <td className="px-3 py-1.5 text-right font-mono text-slate-700 dark:text-slate-300">{String(c.new_value ?? '—')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {sandboxed_edit.ok && sandboxed_edit.download_url && (
            <a
              href={sandboxed_edit.download_url}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 hover:bg-blue-700 text-white w-fit"
            >
              <Download size={12} />{t('Download edited file', 'تحميل الملف المُعدَّل')}
            </a>
          )}

          {sandboxed_edit.generated_code && (
            <div>
              <button onClick={() => setShowCode((s) => !s)} className="flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-slate-600 dark:hover:text-slate-300">
                <Code2 size={12} />{t('View generated code', 'عرض الكود المُولَّد')}
                {showCode ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              </button>
              <AnimatePresence>
                {showCode && (
                  <motion.pre
                    initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
                    className="mt-2 overflow-hidden text-[11px] font-mono bg-slate-900 text-slate-200 rounded-lg p-3 overflow-x-auto whitespace-pre"
                  >
                    {sandboxed_edit.generated_code}
                  </motion.pre>
                )}
              </AnimatePresence>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
