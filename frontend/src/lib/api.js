// Thin client for the FastAPI backend. The base URL can be overridden at build
// time with VITE_API_BASE; it defaults to the local dev server.
export const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

/**
 * Kick off a conversion from a File object. Returns the created job { id, ... }.
 */
export async function startFileConversion(file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${API_BASE}/convert`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

/**
 * Kick off a conversion from a URL (web page or YouTube). Returns the job.
 */
export async function startUrlConversion(url) {
  const res = await fetch(`${API_BASE}/convert`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

/**
 * Subscribe to a job's SSE progress stream.
 *
 * @param {string} jobId
 * @param {(percent:number, message:string)=>void} onProgress
 * @param {(result:object)=>void} onResult
 * @param {(message:string)=>void} onError
 * @returns {() => void} an unsubscribe / close function
 */
export function streamConversion(jobId, { onProgress, onResult, onError }) {
  const source = new EventSource(`${API_BASE}/convert/${jobId}/stream`)
  let settled = false

  source.onmessage = (e) => {
    let data
    try {
      data = JSON.parse(e.data)
    } catch {
      return
    }
    switch (data.event) {
      case 'progress':
        onProgress?.(data.percent, data.message)
        break
      case 'result':
        settled = true
        onResult?.(data)
        break
      case 'error':
        settled = true
        onError?.(data.message)
        break
      case 'done':
        source.close()
        break
      default:
        break
    }
  }

  source.onerror = () => {
    // EventSource fires onerror on normal close too; only surface a real error
    // if we never received a terminal event.
    source.close()
    if (!settled) onError?.('Lost connection to the conversion stream.')
  }

  return () => source.close()
}

/** URL to download a finished job's .md file. */
export function downloadUrl(jobId) {
  return `${API_BASE}/convert/${jobId}/download`
}

async function readError(res) {
  try {
    const body = await res.json()
    return body.detail || `Request failed (${res.status})`
  } catch {
    return `Request failed (${res.status})`
  }
}
