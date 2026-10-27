export interface ExtractionProgress {
  stage: string
  filename?: string
  page?: number
  total_pages?: number
  method?: string
}

const ANALYSIS_ENDPOINT = '/api/local/ai-business-analyst/agentic'

/** The long-lived JSON API remains compatible with older backend workers. */
export async function requestLocalAnalysis<T>(
  form: FormData,
  options: {
    streaming: boolean
    signal?: AbortSignal
    onProgress: (progress: ExtractionProgress) => void
  },
): Promise<T> {
  const request = { method: 'POST', body: form, signal: options.signal }
  let response: Response
  if (options.streaming) {
    response = await fetch(`${ANALYSIS_ENDPOINT}/stream`, request)
    if (response.status !== 404 && response.status !== 405) {
      return readAnalysisStream<T>(response, options.onProgress)
    }
    // A rolling update can advertise streaming on one worker while another
    // still runs the previous version. Never retry auth/validation/5xx failures.
    await response.body?.cancel()
    options.onProgress({ stage: 'compatibility' })
  } else {
    options.onProgress({ stage: 'standard' })
  }
  response = await fetch(ANALYSIS_ENDPOINT, request)
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('The local analysis API is unavailable on this server. The backend must be started or updated.')
    }
    const error = await response.json().catch(() => ({}))
    throw new Error(typeof error.detail === 'string' ? error.detail : `Analysis failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

/** Consume request-bound SSE, including events split across network chunks. */
export async function readAnalysisStream<T>(
  response: Response,
  onProgress: (progress: ExtractionProgress) => void,
): Promise<T> {
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || `Analysis failed (${response.status})`)
  }
  if (!response.body) throw new Error('Live extraction is unavailable. Please retry.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: T | undefined
  const consume = (block: string) => {
    const lines = block.split('\n')
    const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
    const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
    if (!data) return
    const payload = JSON.parse(data)
    if (event === 'error') throw new Error(payload.detail || 'Analysis failed. Please retry.')
    if (event === 'progress') onProgress(payload)
    if (event === 'result') result = payload as T
  }
  try {
    let done = false
    while (!done) {
      const chunk = await reader.read()
      done = chunk.done
      buffer = (buffer + decoder.decode(chunk.value, { stream: !done })).replace(/\r\n/g, '\n')
      let boundary: number
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        consume(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
      }
    }
    if (buffer.trim()) consume(buffer)
    if (!result) throw new Error('The connection ended before analysis finished. Please retry; no partial answer was accepted.')
    return result
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
