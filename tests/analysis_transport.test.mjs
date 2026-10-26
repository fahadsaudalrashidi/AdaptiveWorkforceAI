/** Exercise the actual frontend transport without adding a test dependency. */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { after, afterEach, test } from 'node:test'

const temporary = mkdtempSync(join(tmpdir(), 'awi-analysis-transport-'))
execFileSync(resolve('executive-ui/node_modules/.bin/tsc'), [
  'executive-ui/src/components/analytics/analysisStream.ts',
  '--outDir', temporary, '--module', 'es2022', '--target', 'es2022',
  '--lib', 'dom,es2022', '--skipLibCheck',
])
const source = readFileSync(join(temporary, 'analysisStream.js'), 'utf8')
const { requestLocalAnalysis, readAnalysisStream } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
)
const originalFetch = globalThis.fetch
const base = '/api/local/ai-business-analyst/agentic'
const answer = { answer: { answer_text: 'عدد العقود المنتهية: 2.' }, mode: 'local_fallback' }
const json = (payload, status = 200) => new Response(JSON.stringify(payload), {
  status, headers: { 'Content-Type': 'application/json' },
})
const form = () => { const value = new FormData(); value.set('question', 'كم عقد منتهي؟'); return value }
afterEach(() => { globalThis.fetch = originalFetch })
after(() => rmSync(temporary, { recursive: true, force: true }))

test('older backend capabilities use the established JSON route directly', async () => {
  const calls = []
  globalThis.fetch = async (path) => { calls.push(path); return json(answer) }
  const result = await requestLocalAnalysis(form(), { streaming: false, onProgress() {} })
  assert.deepEqual(result, answer)
  assert.deepEqual(calls, [base])
})

test('advertised streaming works and reports actual page events', async () => {
  const events = []
  globalThis.fetch = async (path) => {
    assert.equal(path, base + '/stream')
    return new Response('event: progress\ndata: {"stage":"extracting","page":1,"total_pages":2}\n\n' +
      `event: result\ndata: ${JSON.stringify(answer)}\n\n`)
  }
  const result = await requestLocalAnalysis(form(), { streaming: true, onProgress: (value) => events.push(value) })
  assert.deepEqual(result, answer)
  assert.equal(events[0].page, 1)
})

for (const missingStatus of [404, 405]) {
  test(`missing streaming route (${missingStatus}) retries only the stable analysis route`, async () => {
    const calls = [], events = []
    const body = form(), signal = new AbortController().signal
    globalThis.fetch = async (path, options) => {
      calls.push(path)
      assert.equal(options.body, body)
      assert.equal(options.signal, signal)
      return path.endsWith('/stream') ? json({ detail: 'Not Found' }, missingStatus) : json(answer)
    }
    const result = await requestLocalAnalysis(body, { streaming: true, signal, onProgress: (value) => events.push(value) })
    assert.deepEqual(calls, [base + '/stream', base])
    assert.deepEqual(result, answer)
    assert.equal(events[0].stage, 'compatibility')
  })
}

for (const status of [401, 403, 422, 500]) {
  test(`authentication/validation/server failure (${status}) is not retried`, async () => {
    let calls = 0
    globalThis.fetch = async () => { calls++; return json({ detail: 'Explicit failure' }, status) }
    await assert.rejects(requestLocalAnalysis(form(), { streaming: true, onProgress() {} }), /Explicit failure/)
    assert.equal(calls, 1)
  })
}

test('SSE parser preserves Arabic UTF-8 and split CRLF event boundaries', async () => {
  const encoder = new TextEncoder()
  const bytes = encoder.encode(`event: result\r\ndata: ${JSON.stringify(answer)}\r\n\r\n`)
  const stream = new ReadableStream({ start(controller) {
    for (let index = 0; index < bytes.length; index++) controller.enqueue(bytes.slice(index, index + 1))
    controller.close()
  } })
  assert.deepEqual(await readAnalysisStream(new Response(stream), () => {}), answer)
})

test('disconnected stream never becomes a partial successful answer or a duplicate request', async () => {
  let calls = 0
  globalThis.fetch = async () => { calls++; return new Response('event: progress\ndata: {"stage":"parsing"}\n\n') }
  await assert.rejects(requestLocalAnalysis(form(), { streaming: true, onProgress() {} }), /before analysis finished/)
  assert.equal(calls, 1)
})

test('stream validation event is an explicit error, not a JSON fallback', async () => {
  globalThis.fetch = async () => new Response('event: error\ndata: {"detail":"Review is required"}\n\n')
  await assert.rejects(requestLocalAnalysis(form(), { streaming: true, onProgress() {} }), /Review is required/)
})

test('missing both routes explains the backend issue instead of surfacing a bare Not Found', async () => {
  globalThis.fetch = async () => json({ detail: 'Not Found' }, 404)
  await assert.rejects(requestLocalAnalysis(form(), { streaming: true, onProgress() {} }), /backend must be started or updated/)
})
