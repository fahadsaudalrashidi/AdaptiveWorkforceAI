import { Fragment, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import {
  AlertCircle, ArrowDownRight, ArrowUpRight, Check, ChevronDown, CircleHelp,
  FileSpreadsheet, LockKeyhole, Plus, Scale, ShieldCheck, Trash2,
} from 'lucide-react'
import { useLanguage } from '../../context/LanguageContext'

export interface WorkforceScenarioColumn {
  name: string
  type: string
  sensitive: boolean
  numeric_summary?: {
    non_null?: number
    mean?: number | null
    median?: number | null
    min?: number | null
    max?: number | null
    std?: number | null
  } | null
}

export interface WorkforceScenarioDataset {
  id: string
  filename: string
  sheet: string
  columns: WorkforceScenarioColumn[]
}

export interface WorkforceScenarioStudioProps {
  datasets: WorkforceScenarioDataset[]
  files: File[]
  cleaningOptions: string[]
  disabled: boolean
  onBusyChange: (busy: boolean) => void
}

interface ScenarioInput {
  id: string
  name: string
  headcount: string
  payroll: string
  overtime: string
}

interface ScenarioGroup {
  label: string
  headcount: number
  payroll: number
  overtime: number | null
  labor_cost: number
}

interface ScenarioTotals {
  headcount: number
  payroll: number
  overtime: number | null
  labor_cost: number
}

interface ScenarioResult {
  id: string
  name: string
  assumptions: {
    headcount_change_pct: number
    payroll_growth_pct: number
    overtime_reduction_pct: number
  }
  totals: ScenarioTotals
  groups: ScenarioGroup[]
  group_details_withheld: boolean
}

interface ScenarioResponse {
  filename: string
  sheet: string
  baseline: ScenarioTotals & { groups: ScenarioGroup[]; group_details_withheld: boolean }
  scenarios: ScenarioResult[]
  limitations: string[]
  privacy: { persisted: false; source_rows_returned: false }
}

const MAX_SCENARIOS = 3

function isNumericColumn(column: WorkforceScenarioColumn) {
  return !column.sensitive && (!!column.numeric_summary || /^(number|numeric|integer|int|float|decimal|currency)$/i.test(column.type))
}

function formatNumber(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '—'
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function finiteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function validTotals(value: unknown): value is ScenarioTotals {
  if (!value || typeof value !== 'object') return false
  const totals = value as ScenarioTotals
  return finiteNumber(totals.headcount) && finiteNumber(totals.payroll)
    && (totals.overtime === null || finiteNumber(totals.overtime))
    && finiteNumber(totals.labor_cost)
}

function validGroups(value: unknown): value is ScenarioGroup[] {
  return Array.isArray(value) && value.every((group) =>
    !!group && typeof group === 'object'
    && typeof group.label === 'string'
    && finiteNumber(group.headcount)
    && finiteNumber(group.payroll)
    && (group.overtime === null || finiteNumber(group.overtime))
    && finiteNumber(group.labor_cost),
  )
}

function validateResponse(value: unknown): value is ScenarioResponse {
  if (!value || typeof value !== 'object') return false
  const result = value as ScenarioResponse
  return typeof result.filename === 'string'
    && typeof result.sheet === 'string'
    && validTotals(result.baseline)
    && validGroups(result.baseline.groups)
    && typeof result.baseline.group_details_withheld === 'boolean'
    && Array.isArray(result.scenarios)
    && result.scenarios.every((scenario) =>
      typeof scenario.id === 'string'
      && typeof scenario.name === 'string'
      && validTotals(scenario.totals)
      && validGroups(scenario.groups)
      && typeof scenario.group_details_withheld === 'boolean'
      && !!scenario.assumptions
      && finiteNumber(scenario.assumptions.headcount_change_pct)
      && finiteNumber(scenario.assumptions.payroll_growth_pct)
      && finiteNumber(scenario.assumptions.overtime_reduction_pct),
    )
    && Array.isArray(result.limitations)
    && !!result.privacy
    && result.privacy.persisted === false
    && result.privacy.source_rows_returned === false
}

function makeScenario(id: string, index: number): ScenarioInput {
  return {
    id,
    name: `Scenario ${index + 1}`,
    headcount: '0',
    payroll: '0',
    overtime: '0',
  }
}

function errorText(response: Response, payload: unknown) {
  const detail = payload && typeof payload === 'object' && 'detail' in payload
    ? (payload as { detail?: unknown }).detail : null
  return typeof detail === 'string' ? detail : `Request failed (${response.status})`
}

export function WorkforceScenarioStudio({
  datasets,
  files,
  cleaningOptions,
  disabled,
  onBusyChange,
}: WorkforceScenarioStudioProps) {
  const { t, isAr } = useLanguage()
  const availableDatasets = useMemo(
    () => datasets.filter((dataset) => files.some((file) => file.name === dataset.filename)),
    [datasets, files],
  )
  const [datasetId, setDatasetId] = useState('')
  const selectedDataset = availableDatasets.find((dataset) => dataset.id === datasetId) ?? availableDatasets[0]
  const numericColumns = useMemo(
    () => selectedDataset?.columns.filter(isNumericColumn) ?? [],
    [selectedDataset],
  )
  const [departmentColumn, setDepartmentColumn] = useState('')
  const [headcountColumn, setHeadcountColumn] = useState('__rows__')
  const [payrollColumn, setPayrollColumn] = useState('')
  const [overtimeColumn, setOvertimeColumn] = useState('')
  const [scenarios, setScenarios] = useState<ScenarioInput[]>([makeScenario('scenario-1', 0), makeScenario('scenario-2', 1)])
  const [nextScenarioId, setNextScenarioId] = useState(3)
  const [result, setResult] = useState<ScenarioResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const busyCallback = useRef(onBusyChange)
  busyCallback.current = onBusyChange

  useEffect(() => { busyCallback.current(loading) }, [loading])
  useEffect(() => () => busyCallback.current(false), [])

  useEffect(() => {
    if (!selectedDataset) {
      setDepartmentColumn('')
      setHeadcountColumn('__rows__')
      setPayrollColumn('')
      setOvertimeColumn('')
      return
    }
    const nextNumeric = selectedDataset.columns.filter(isNumericColumn)
    const nextDepartment = selectedDataset.columns.find((column) =>
      !column.sensitive && !isNumericColumn(column) && !/date|time|تاريخ|شهر|فترة/i.test(`${column.type} ${column.name}`),
    )
    setDepartmentColumn(nextDepartment?.name ?? '')
    setHeadcountColumn(nextNumeric.find((column) => /head.?count|employees?|fte|position.?count|staff|عدد.?الموظفين/i.test(column.name))?.name ?? '__rows__')
    setPayrollColumn(nextNumeric.find((column) => /payroll|salary|wage|compensation|labor|labour|راتب|أجر|أجور|تكلفة/i.test(column.name))?.name ?? '')
    setOvertimeColumn(nextNumeric.find((column) => /overtime|over.?time|extra.?hours|عمل.?إضافي/i.test(column.name))?.name ?? '')
    setResult(null)
    setError('')
  }, [selectedDataset?.id])

  useEffect(() => { setResult(null) }, [cleaningOptions])

  const hasSchema = !!selectedDataset && numericColumns.length > 0
  const schemaIssue = !availableDatasets.length
    ? t('Select or inspect a source file first. The original browser file must still be available.', 'اختر ملف مصدر أو افحصه أولاً. يجب أن يظل الملف الأصلي متاحاً في المتصفح.')
    : !selectedDataset
      ? t('Choose a profiled dataset to continue.', 'اختر مجموعة بيانات مفحوصة للمتابعة.')
      : !numericColumns.length
        ? t('This dataset has no eligible, non-sensitive numeric columns for payroll.', 'لا تحتوي مجموعة البيانات على أعمدة رقمية مؤهلة وغير حساسة للرواتب.')
        : ''

  const updateScenario = (id: string, field: keyof Omit<ScenarioInput, 'id'>, value: string) => {
    setScenarios((current) => current.map((scenario) => scenario.id === id ? { ...scenario, [field]: value } : scenario))
    setResult(null)
  }

  const addScenario = () => {
    if (scenarios.length >= MAX_SCENARIOS) return
    const id = `scenario-${nextScenarioId}`
    setScenarios((current) => [...current, makeScenario(id, current.length)])
    setNextScenarioId((current) => current + 1)
    setResult(null)
  }

  const removeScenario = (id: string) => {
    if (scenarios.length <= 1) return
    setScenarios((current) => current.filter((scenario) => scenario.id !== id))
    setResult(null)
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (disabled || loading || !selectedDataset || !hasSchema) return
    setError('')
    setResult(null)

    const parsedScenarios = scenarios.map((scenario) => ({
      ...scenario,
      headcount_change_pct: Number(scenario.headcount),
      payroll_growth_pct: Number(scenario.payroll),
      overtime_reduction_pct: Number(scenario.overtime),
    }))
    const invalid = parsedScenarios.find((scenario) =>
      !scenario.name.trim()
      || !Number.isFinite(scenario.headcount_change_pct) || scenario.headcount_change_pct < -100 || scenario.headcount_change_pct > 100
      || !Number.isFinite(scenario.payroll_growth_pct) || scenario.payroll_growth_pct < -100 || scenario.payroll_growth_pct > 100
      || !Number.isFinite(scenario.overtime_reduction_pct) || scenario.overtime_reduction_pct < 0 || scenario.overtime_reduction_pct > 100,
    )
    if (invalid) {
      setError(t(
        'Check each scenario: enter a name, headcount and payroll changes from −100% to 100%, and overtime reduction from 0% to 100%.',
        'تحقق من كل سيناريو: أدخل اسماً، وتغييراً في عدد الموظفين والرواتب من ‎−100٪ إلى 100٪، وخفضاً للعمل الإضافي من 0٪ إلى 100٪.',
      ))
      return
    }
    if (!payrollColumn) {
      setError(t('Choose the numeric measure that represents payroll or workforce cost.', 'اختر المقياس الرقمي الذي يمثل الرواتب أو تكلفة القوى العاملة.'))
      return
    }
    if ((headcountColumn !== '__rows__' && headcountColumn === payrollColumn)
      || (overtimeColumn && (overtimeColumn === payrollColumn || overtimeColumn === headcountColumn))) {
      setError(t('Choose different columns for headcount, payroll and overtime.', 'اختر أعمدة مختلفة لعدد الموظفين والرواتب والعمل الإضافي.'))
      return
    }
    const file = files.find((item) => item.name === selectedDataset.filename)
    if (!file) {
      setError(t('The source file is no longer selected. Select it again before running this comparison.', 'لم يعد الملف المصدر محدداً. أعد تحديده قبل إجراء المقارنة.'))
      return
    }
    setLoading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('sheet', selectedDataset.sheet)
      form.append('department_column', departmentColumn)
      form.append('headcount_column', headcountColumn)
      form.append('payroll_column', payrollColumn)
      form.append('overtime_column', overtimeColumn)
      form.append('cleaning_options', JSON.stringify(cleaningOptions))
      form.append('language', isAr ? 'ar' : 'en')
      form.append('scenarios', JSON.stringify(parsedScenarios.map((scenario) => ({
        id: scenario.id,
        name: scenario.name.trim(),
        headcount_change_pct: scenario.headcount_change_pct,
        payroll_growth_pct: scenario.payroll_growth_pct,
        overtime_reduction_pct: scenario.overtime_reduction_pct,
      }))))

      const response = await fetch('/api/local/data-hub/scenario', { method: 'POST', body: form })
      const payload: unknown = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(errorText(response, payload))
      if (!validateResponse(payload)) {
        throw new Error(t(
          'The scenario response was incomplete or did not confirm aggregate-only privacy. No results were displayed.',
          'كانت استجابة السيناريو غير مكتملة أو لم تؤكد خصوصية البيانات المجمعة فقط. لم يتم عرض أي نتائج.',
        ))
      }
      setResult(payload)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('The scenario could not be calculated. Please retry.', 'تعذر حساب السيناريو. يرجى إعادة المحاولة.'))
    } finally {
      setLoading(false)
    }
  }

  const panel = 'rounded-2xl border border-[#3b4264]/80 bg-[#202447]/90 shadow-[0_14px_36px_rgba(8,12,34,.18)]'
  const input = 'min-h-10 w-full rounded-xl border border-[#3b4264] bg-[#171a34] px-3 py-2 text-sm text-slate-100 focus:border-[#72c6a3] focus:outline-none focus:ring-2 focus:ring-[#72c6a3]/20 disabled:cursor-not-allowed disabled:opacity-50'
  const label = 'mb-1.5 block text-[11px] font-semibold tracking-wide text-slate-300'

  const delta = (value: number, baseline: number) => {
    const difference = value - baseline
    const percent = baseline ? (difference / Math.abs(baseline)) * 100 : null
    const positive = difference > 0
    return (
      <span className={`inline-flex items-center gap-1 text-[11px] font-semibold tabular-nums ${difference === 0 ? 'text-slate-400' : positive ? 'text-amber-200' : 'text-[#9bdac0]'}`}>
        {difference === 0 ? <Check size={12} /> : positive ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
        {difference > 0 ? '+' : ''}{formatNumber(difference)}
        {percent !== null && <span className="text-slate-500">({percent > 0 ? '+' : ''}{percent.toFixed(1)}%)</span>}
      </span>
    )
  }

  return (
    <section dir={isAr ? 'rtl' : 'ltr'} className="space-y-4 text-slate-100" aria-labelledby="scenario-studio-title">
      <header className={`${panel} relative overflow-hidden p-5 sm:p-6`}>
        <div className="pointer-events-none absolute -top-20 end-10 h-52 w-52 rounded-full border border-[#72c6a3]/10" />
        <div className="pointer-events-none absolute -top-12 end-6 h-36 w-36 rounded-full border border-[#72c6a3]/10" />
        <div className="relative flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
          <div>
            <div className="mb-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[.2em] text-[#9bdac0]">
              <Scale size={14} /> {t('WORKFORCE INTELLIGENCE', 'ذكاء القوى العاملة')}
            </div>
            <h2 id="scenario-studio-title" className="text-xl font-semibold tracking-tight text-white sm:text-2xl">
              {t('Workforce scenario studio', 'استوديو سيناريوهات القوى العاملة')}
            </h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">
              {t('Compare explicit headcount, payroll and overtime assumptions against the selected file’s baseline.', 'قارن افتراضات واضحة لعدد الموظفين والرواتب والعمل الإضافي بخط الأساس للملف المحدد.')}
            </p>
          </div>
          <span className="inline-flex w-fit shrink-0 items-center gap-2 rounded-full border border-[#72c6a3]/25 bg-[#72c6a3]/10 px-3 py-2 text-[11px] font-semibold text-[#b4ebd4]">
            <ShieldCheck size={14} /> {t('LOCAL · DETERMINISTIC', 'محلي · حساب حتمي')}
          </span>
        </div>
        <div className="relative mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-white/10 pt-4 text-[11px] text-slate-400">
          <span className="inline-flex items-center gap-1.5"><LockKeyhole size={13} className="text-[#72c6a3]" />{t('Aggregate results only', 'نتائج مجمعة فقط')}</span>
          <span>{t('No source rows returned', 'لا تُعاد سجلات المصدر')}</span>
          <span>{t('Not a forecast or legal advice', 'ليس توقعاً أو مشورة قانونية')}</span>
        </div>
      </header>

      {disabled && (
        <div role="status" className="rounded-xl border border-[#5378ac]/30 bg-[#5378ac]/10 px-4 py-3 text-xs leading-5 text-[#b8cae6]">
          {t('Scenario analysis is temporarily unavailable while another Data Hub operation is running.', 'تحليل السيناريوهات غير متاح مؤقتاً أثناء تشغيل عملية أخرى في مركز البيانات.')}
        </div>
      )}

      {schemaIssue ? (
        <div className={`${panel} flex items-start gap-3 p-5`} role="status">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[#5378ac]/30 bg-[#5378ac]/10 text-[#9db8df]"><FileSpreadsheet size={19} /></div>
          <div>
            <h3 className="font-semibold text-slate-200">{t('A profiled workforce dataset is needed', 'يلزم توفير مجموعة بيانات مفحوصة للقوى العاملة')}</h3>
            <p className="mt-1 text-sm leading-6 text-slate-400">{schemaIssue}</p>
          </div>
        </div>
      ) : (
        <form onSubmit={(event) => void submit(event)} className="space-y-4">
          <section className={`${panel} p-4 sm:p-5`}>
            <div className="mb-4 flex items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#72c6a3]/10 text-xs font-bold text-[#9bdac0]">01</span>
              <div>
                <h3 className="text-sm font-semibold text-white">{t('Choose the workforce measures', 'اختر مقاييس القوى العاملة')}</h3>
                <p className="mt-0.5 text-xs text-slate-400">{t('Only non-sensitive numeric fields are eligible for cost measures.', 'تقتصر مقاييس التكلفة على الحقول الرقمية غير الحساسة.')}</p>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <div className="sm:col-span-2 lg:col-span-1">
                <label className={label} htmlFor="scenario-dataset">{t('Profiled file', 'الملف المفحوص')}</label>
                <div className="relative">
                  <select id="scenario-dataset" className={`${input} appearance-none pe-9`} value={selectedDataset?.id ?? ''} onChange={(event) => { setDatasetId(event.target.value); setResult(null) }} disabled={disabled || loading}>
                    {availableDatasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.filename} · {dataset.sheet}</option>)}
                  </select>
                  <ChevronDown size={14} className="pointer-events-none absolute end-3 top-3.5 text-slate-500" />
                </div>
              </div>
              <div>
                <label className={label} htmlFor="scenario-department">{t('Group by', 'التجميع حسب')}</label>
                <div className="relative">
                  <select id="scenario-department" className={`${input} appearance-none pe-9`} value={departmentColumn} onChange={(event) => { setDepartmentColumn(event.target.value); setResult(null) }} disabled={disabled || loading}>
                    <option value="">{t('Totals only', 'الإجمالي فقط')}</option>
                    {selectedDataset?.columns.filter((column) => !column.sensitive).map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}
                  </select>
                  <ChevronDown size={14} className="pointer-events-none absolute end-3 top-3.5 text-slate-500" />
                </div>
              </div>
              <div>
                <label className={label} htmlFor="scenario-headcount">{t('Headcount basis', 'أساس عدد الموظفين')}</label>
                <div className="relative">
                  <select id="scenario-headcount" className={`${input} appearance-none pe-9`} value={headcountColumn} onChange={(event) => { setHeadcountColumn(event.target.value); setResult(null) }} disabled={disabled || loading}>
                    <option value="__rows__">{t('Count rows', 'احتساب الصفوف')}</option>
                    {numericColumns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}
                  </select>
                  <ChevronDown size={14} className="pointer-events-none absolute end-3 top-3.5 text-slate-500" />
                </div>
              </div>
              <div>
                <label className={label} htmlFor="scenario-payroll">{t('Payroll measure', 'مقياس الرواتب')}</label>
                <div className="relative">
                  <select id="scenario-payroll" className={`${input} appearance-none pe-9`} value={payrollColumn} onChange={(event) => { setPayrollColumn(event.target.value); setResult(null) }} disabled={disabled || loading}>
                    {numericColumns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}
                  </select>
                  <ChevronDown size={14} className="pointer-events-none absolute end-3 top-3.5 text-slate-500" />
                </div>
              </div>
              <div>
                <label className={label} htmlFor="scenario-overtime">{t('Overtime (optional)', 'العمل الإضافي (اختياري)')}</label>
                <div className="relative">
                  <select id="scenario-overtime" className={`${input} appearance-none pe-9`} value={overtimeColumn} onChange={(event) => { setOvertimeColumn(event.target.value); setResult(null) }} disabled={disabled || loading}>
                    <option value="">{t('Not included', 'غير مشمول')}</option>
                    {numericColumns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}
                  </select>
                  <ChevronDown size={14} className="pointer-events-none absolute end-3 top-3.5 text-slate-500" />
                </div>
              </div>
            </div>
            <p className="mt-3 flex items-start gap-1.5 text-[11px] leading-5 text-slate-500"><CircleHelp size={13} className="mt-0.5 shrink-0" />{t('Count rows uses the profiled row count as headcount. Group details may be withheld when a group is too small.', 'يستخدم احتساب الصفوف عدد الصفوف المفحوصة كأساس لعدد الموظفين. قد تُحجب تفاصيل المجموعة عندما يكون عددها صغيراً.')}</p>
          </section>

          <section className={`${panel} p-4 sm:p-5`}>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#72c6a3]/10 text-xs font-bold text-[#9bdac0]">02</span>
                <div>
                  <h3 className="text-sm font-semibold text-white">{t('Set the assumptions', 'حدد الافتراضات')}</h3>
                  <p className="mt-0.5 text-xs text-slate-400">{t('Changes are applied arithmetically; they are not predictions.', 'تُطبّق التغييرات حسابياً؛ ولا تمثل تنبؤات.')}</p>
                </div>
              </div>
              <button type="button" onClick={addScenario} disabled={disabled || loading || scenarios.length >= MAX_SCENARIOS} className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-[#5378ac]/40 px-3 text-xs font-semibold text-[#b8cae6] transition hover:bg-[#5378ac]/10 disabled:cursor-not-allowed disabled:opacity-40">
                <Plus size={14} />{t('Add scenario', 'إضافة سيناريو')}
              </button>
            </div>
            <div className="grid gap-3 xl:grid-cols-3">
              {scenarios.map((scenario, index) => (
                <article key={scenario.id} className="rounded-xl border border-[#3b4264]/80 bg-[#171a34]/65 p-4">
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <span className="text-[10px] font-bold uppercase tracking-[.16em] text-[#9bdac0]">{t('Scenario', 'السيناريو')} 0{index + 1}</span>
                    {scenarios.length > 1 && <button type="button" onClick={() => removeScenario(scenario.id)} disabled={disabled || loading} className="rounded-md p-1.5 text-slate-500 transition hover:bg-rose-400/10 hover:text-rose-200 disabled:opacity-40" aria-label={t(`Remove ${scenario.name}`, `إزالة ${scenario.name}`)}><Trash2 size={14} /></button>}
                  </div>
                  <label className={label} htmlFor={`${scenario.id}-name`}>{t('Scenario name', 'اسم السيناريو')}</label>
                  <input id={`${scenario.id}-name`} className={input} value={scenario.name} maxLength={48} onChange={(event) => updateScenario(scenario.id, 'name', event.target.value)} disabled={disabled || loading} required />
                  <div className="mt-3 grid grid-cols-3 gap-2">
                    {([
                      ['headcount', t('Headcount', 'عدد الموظفين'), -100, 100],
                      ['payroll', t('Payroll', 'الرواتب'), -100, 100],
                      ['overtime', t('OT reduction', 'خفض الإضافي'), 0, 100],
                    ] as const).map(([field, title, min, max]) => (
                      <div key={field}>
                        <label className={`${label} min-h-8 leading-4`} htmlFor={`${scenario.id}-${field}`}>{title} <span className="text-slate-500">%</span></label>
                        <input
                          id={`${scenario.id}-${field}`}
                          className={`${input} px-2 text-center tabular-nums`}
                          type="number"
                          inputMode="decimal"
                          min={min}
                          max={max}
                          step="0.1"
                          value={scenario[field]}
                          onChange={(event) => updateScenario(scenario.id, field, event.target.value)}
                          disabled={disabled || loading}
                          required
                          aria-label={`${title} ${t('change percent', 'نسبة التغيير')}`}
                        />
                      </div>
                    ))}
                  </div>
                  <p className="mt-2 text-[10px] leading-4 text-slate-500">{t('Headcount and payroll: −100% to +100%. Overtime: reduction only, 0% to 100%.', 'عدد الموظفين والرواتب: من ‎−100٪ إلى +100٪. العمل الإضافي: خفض فقط، من 0٪ إلى 100٪.')}</p>
                </article>
              ))}
            </div>
            {cleaningOptions.length > 0 && (
              <p className="mt-3 text-[11px] text-slate-500">
                {t('In-memory cleaning applied:', 'التنظيف المطبق في الذاكرة:')} <span className="text-slate-300">{cleaningOptions.join(' · ')}</span>
              </p>
            )}
          </section>

          {error && <div role="alert" className="flex items-start gap-2 rounded-xl border border-rose-400/25 bg-rose-950/25 px-4 py-3 text-sm text-rose-200"><AlertCircle size={17} className="mt-0.5 shrink-0" /><span>{error}</span></div>}

          <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="max-w-xl text-[11px] leading-5 text-slate-500">{t('Calculation uses the selected file locally. Results are aggregate-only; source rows are never returned or persisted.', 'يُجرى الحساب على الملف المحدد محلياً. النتائج مجمعة فقط؛ ولا تُعاد سجلات المصدر أو تُحفظ.')}</p>
            <button type="submit" disabled={disabled || loading || !selectedDataset || !payrollColumn} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#72c6a3] px-5 text-sm font-bold text-[#171a34] transition hover:bg-[#8bd6b6] disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto">
              {loading ? <span className="h-4 w-4 animate-pulse rounded-full border-2 border-[#171a34]/30 border-t-[#171a34]" /> : <Scale size={16} />}
              {loading ? t('Calculating scenarios…', 'جارٍ حساب السيناريوهات…') : t('Compare scenarios', 'مقارنة السيناريوهات')}
            </button>
          </div>

          {loading && (
            <section className={`${panel} space-y-4 p-5`} aria-label={t('Scenario results loading', 'جارٍ تحميل نتائج السيناريوهات')} aria-live="polite">
              <div className="skeleton h-5 w-48" />
              <div className="grid gap-3 sm:grid-cols-3">{[1, 2, 3].map((item) => <div key={item} className="skeleton h-28 rounded-xl" />)}</div>
              <div className="skeleton h-36 rounded-xl" />
            </section>
          )}

          {result && !loading && (
            <section className={`${panel} overflow-hidden`} aria-live="polite">
              <div className="flex flex-col justify-between gap-3 border-b border-[#3b4264]/80 p-4 sm:flex-row sm:items-center sm:px-5">
                <div>
                  <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[.18em] text-[#9bdac0]"><Check size={13} />{t('COMPARISON READY', 'المقارنة جاهزة')}</div>
                  <h3 className="mt-1 text-base font-semibold text-white">{t('Baseline vs. scenario', 'خط الأساس مقابل السيناريو')}</h3>
                </div>
                <span className="text-xs text-slate-400">{result.filename} <span className="text-slate-600">/</span> {result.sheet}</span>
              </div>
              <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4 sm:p-5">
                <div className="rounded-xl border border-[#5378ac]/30 bg-[#5378ac]/[.08] p-4">
                  <div className="text-[10px] font-bold uppercase tracking-[.15em] text-slate-400">{t('Baseline', 'خط الأساس')}</div>
                  <div className="mt-3 space-y-2 text-xs">
                    <div className="flex justify-between gap-2"><span className="text-slate-400">{t('Labor cost', 'تكلفة العمل')}</span><strong className="tabular-nums text-white">{formatNumber(result.baseline.labor_cost)}</strong></div>
                    <div className="flex justify-between gap-2"><span className="text-slate-400">{t('Headcount', 'عدد الموظفين')}</span><strong className="tabular-nums text-slate-200">{formatNumber(result.baseline.headcount)}</strong></div>
                    <div className="flex justify-between gap-2"><span className="text-slate-400">{t('Payroll', 'الرواتب')}</span><strong className="tabular-nums text-slate-200">{formatNumber(result.baseline.payroll)}</strong></div>
                    {result.baseline.overtime !== null && <div className="flex justify-between gap-2"><span className="text-slate-400">{t('Overtime', 'العمل الإضافي')}</span><strong className="tabular-nums text-slate-200">{formatNumber(result.baseline.overtime)}</strong></div>}
                  </div>
                </div>
                {result.scenarios.map((scenario) => (
                  <div key={scenario.id} className="rounded-xl border border-[#3b4264]/80 bg-[#171a34]/65 p-4">
                    <div className="truncate text-xs font-semibold text-slate-200" title={scenario.name}>{scenario.name}</div>
                    <div className="mt-3 flex items-baseline justify-between gap-2">
                      <span className="text-[10px] font-bold uppercase tracking-[.12em] text-slate-500">{t('Labor cost', 'تكلفة العمل')}</span>
                      <strong className="text-lg tabular-nums text-white">{formatNumber(scenario.totals.labor_cost)}</strong>
                    </div>
                    <div className="mt-1">{delta(scenario.totals.labor_cost, result.baseline.labor_cost)}</div>
                    <div className="mt-3 space-y-1.5 border-t border-white/[.06] pt-3 text-[11px]">
                      <div className="flex justify-between gap-2"><span className="text-slate-500">{t('Headcount', 'عدد الموظفين')}</span><span className="tabular-nums text-slate-300">{formatNumber(scenario.totals.headcount)}</span></div>
                      <div className="flex justify-between gap-2"><span className="text-slate-500">{t('Payroll', 'الرواتب')}</span><span className="tabular-nums text-slate-300">{formatNumber(scenario.totals.payroll)}</span></div>
                      {scenario.totals.overtime !== null && <div className="flex justify-between gap-2"><span className="text-slate-500">{t('Overtime', 'العمل الإضافي')}</span><span className="tabular-nums text-slate-300">{formatNumber(scenario.totals.overtime)}</span></div>}
                      <div className="pt-1 text-[10px] leading-4 text-slate-500">
                        {t('Assumptions', 'الافتراضات')}: HC {scenario.assumptions.headcount_change_pct}% · {t('payroll', 'الرواتب')} {scenario.assumptions.payroll_growth_pct}% · OT −{scenario.assumptions.overtime_reduction_pct}%
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              {result.baseline.groups.length > 0 && (
                <div className="border-t border-[#3b4264]/80 p-4 sm:p-5">
                  <h4 className="mb-3 text-xs font-semibold text-slate-200">{t('Group comparison', 'مقارنة المجموعات')}</h4>
                  <div className="overflow-x-auto rounded-xl border border-[#3b4264]/70">
                    <table className="w-full min-w-[760px] text-start text-xs">
                      <thead className="bg-[#171a34]/80 text-[10px] uppercase tracking-wider text-slate-500">
                        <tr><th className="px-3 py-2.5 font-bold">{t('Group', 'المجموعة')}</th><th className="px-3 py-2.5 font-bold">{t('Measure', 'المقياس')}</th><th className="px-3 py-2.5 font-bold">{t('Baseline', 'خط الأساس')}</th>{result.scenarios.map((scenario) => <th key={scenario.id} className="px-3 py-2.5 font-bold">{scenario.name}</th>)}</tr>
                      </thead>
                      <tbody className="divide-y divide-[#3b4264]/50">
                        {result.baseline.groups.map((group) => (
                          <Fragment key={group.label}>
                            {([
                              ['labor_cost', t('Labor cost', 'تكلفة العمل')],
                              ['headcount', t('Headcount', 'عدد الموظفين')],
                              ['payroll', t('Payroll', 'الرواتب')],
                              ['overtime', t('Overtime', 'العمل الإضافي')],
                            ] as const).map(([field, title], rowIndex) => (
                              <tr key={field} className="border-t border-[#3b4264]/40">
                                {rowIndex === 0 && <th rowSpan={4} className="max-w-48 px-3 py-3 text-start align-top font-semibold text-slate-300">{group.label}</th>}
                                <td className="px-3 py-2.5 font-medium text-slate-400">{title}</td>
                                <td className="px-3 py-2.5 tabular-nums text-slate-300">{formatNumber(group[field])}</td>
                                {result.scenarios.map((scenario) => {
                                  const scenarioGroup = scenario.groups.find((item) => item.label === group.label)
                                  return <td key={scenario.id} className="px-3 py-2.5 tabular-nums text-slate-200">{scenarioGroup ? formatNumber(scenarioGroup[field]) : '—'}</td>
                                })}
                              </tr>
                            ))}
                          </Fragment>
                        ))}
                      </tbody>
                    </table>
                    {(result.baseline.group_details_withheld || result.scenarios.some((scenario) => scenario.group_details_withheld)) && (
                      <p className="border-t border-[#3b4264]/50 px-3 py-2 text-[10px] text-slate-500">{t('Some group details were withheld to protect privacy.', 'حُجبت بعض تفاصيل المجموعات لحماية الخصوصية.')}</p>
                    )}
                  </div>
                </div>
              )}

              {result.limitations.length > 0 && (
                <div className="mx-4 mb-4 flex items-start gap-2 rounded-xl border border-[#5378ac]/25 bg-[#5378ac]/[.07] px-3 py-3 text-[11px] leading-5 text-slate-400 sm:mx-5 sm:mb-5">
                  <CircleHelp size={14} className="mt-0.5 shrink-0 text-[#9db8df]" />
                  <ul className="list-inside list-disc space-y-1">{result.limitations.map((limitation, index) => <li key={`${index}-${limitation}`}>{limitation}</li>)}</ul>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-[#3b4264]/70 px-4 py-3 text-[10px] text-slate-500 sm:px-5">
                <span className="inline-flex items-center gap-1.5 text-[#9bdac0]"><LockKeyhole size={12} />{t('Not persisted', 'غير محفوظة')}</span>
                <span>{t('Source rows not returned', 'لم تُعَد سجلات المصدر')}</span>
                <span>{t('Arithmetic what-if only', 'حساب افتراضي فقط')}</span>
              </div>
            </section>
          )}

          {!result && !loading && !error && (
            <div className={`${panel} flex items-center gap-3 px-4 py-3 text-xs text-slate-400`}>
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[#3b4264] bg-[#171a34] text-slate-500"><Scale size={15} /></div>
              <span>{t('Set your assumptions, then compare each scenario with the same file baseline.', 'حدد افتراضاتك، ثم قارن كل سيناريو بخط الأساس للملف نفسه.')}</span>
            </div>
          )}
        </form>
      )}
    </section>
  )
}
