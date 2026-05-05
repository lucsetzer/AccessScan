/**
 * api.js — All AccessScan API calls in one place.
 * No fetch() calls anywhere else in the codebase.
 */

const BASE = '/api'

/**
 * Audit an embed snippet or page URL.
 * @param {{ snippet?: string, url?: string }} body
 */
export async function auditEmbed(body) {
  const res = await fetch(`${BASE}/audit/embed`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return _handleJson(res)
}

/**
 * Audit a PDF — file upload or URL.
 * @param {{ file?: File, url?: string }} params
 */
export async function auditPdf({ file, url }) {
  const form = new FormData()
  if (file) form.append('file', file)
  if (url)  form.append('url', url)

  const res = await fetch(`${BASE}/audit/pdf`, {
    method: 'POST',
    body: form,
  })
  return _handleJson(res)
}

/**
 * Audit a DOCX — file upload or URL.
 * @param {{ file?: File, url?: string }} params
 */
export async function auditDocx({ file, url }) {
  const form = new FormData()
  if (file) form.append('file', file)
  if (url)  form.append('url', url)

  const res = await fetch(`${BASE}/audit/docx`, {
    method: 'POST',
    body: form,
  })
  return _handleJson(res)
}

/**
 * Audit a full HTML page.
 * @param {string} url
 */
export async function auditPage(url) {
  const res = await fetch(`${BASE}/audit/page`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  return _handleJson(res)
}

/**
 * Stream sitemap scan results via SSE.
 * @param {{ url: string, scan_types: string[], max_urls: number }} body
 * @param {{ onLog, onProgress, onResult, onComplete, onError }} callbacks
 * @returns {() => void} cancel function
 */
export function auditSitemap(body, { onLog, onProgress, onResult, onComplete, onError }) {
  let cancelled = false

  fetch(`${BASE}/audit/sitemap`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(async (res) => {
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
      onError?.(err.detail || 'Sitemap scan failed')
      return
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (!cancelled) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() // keep incomplete line

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const event = JSON.parse(line.slice(6))
          switch (event.type) {
            case 'log':      onLog?.(event);      break
            case 'progress': onProgress?.(event); break
            case 'result':   onResult?.(event);   break
            case 'complete': onComplete?.(event); break
            case 'error':    onError?.(event.message); break
          }
        } catch {
          // malformed SSE line — skip
        }
      }
    }
  }).catch((err) => {
    if (!cancelled) onError?.(err.message || 'Network error')
  })

  return () => { cancelled = true }
}

/**
 * Export results.
 * @param {{ format: 'csv'|'pdf'|'json', results: object[] }} body
 */
export async function exportResults(body) {
  const res = await fetch(`${BASE}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error('Export failed')

  // Trigger browser download
  const blob = await res.blob()
  const contentDisposition = res.headers.get('Content-Disposition') || ''
  const filenameMatch = contentDisposition.match(/filename=([^\s;]+)/)
  const filename = filenameMatch ? filenameMatch[1] : `accessscan-report.${body.format}`

  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ── Internal ──────────────────────────────────────────────────────────────────

async function _handleJson(res) {
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || data.error || `HTTP ${res.status}`)
  }
  return data
}