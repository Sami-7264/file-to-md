import { useCallback, useRef, useState } from 'react'
import { UploadCloud, Link2, X, Loader2, CheckCircle2, AlertCircle } from 'lucide-react'
import FileTypeBadge from './FileTypeBadge'
import { useHistory } from '../context/HistoryContext'
import { startFileConversion, startUrlConversion, streamConversion } from '../lib/api'

const MAX_BYTES = 100 * 1024 * 1024 // mirror the backend limit for instant feedback

let _seq = 0
const nextId = () => `q${++_seq}`

/**
 * The hero element: a large drop zone plus a URL bar. Owns a queue of in-flight
 * conversions and pushes finished results into the shared HistoryContext.
 */
export default function DropZone() {
  const { addEntry } = useHistory()
  const [queue, setQueue] = useState([])
  const [dragging, setDragging] = useState(false)
  const [url, setUrl] = useState('')
  const inputRef = useRef(null)

  const patch = useCallback((id, changes) => {
    setQueue((prev) => prev.map((it) => (it.id === id ? { ...it, ...changes } : it)))
  }, [])

  // Drive a single queue item through start -> stream -> done/error.
  const run = useCallback(
    async (item, starter) => {
      try {
        patch(item.id, { status: 'uploading', message: 'Uploading…', percent: 2 })
        const job = await starter()
        patch(item.id, { status: 'converting', jobId: job.id, percent: 5 })

        streamConversion(job.id, {
          onProgress: (percent, message) => patch(item.id, { percent, message }),
          onResult: (result) => {
            patch(item.id, { status: 'done', percent: 100, message: 'Done' })
            addEntry({
              id: result.id,
              sourceName: result.source_name,
              outputName: result.output_name,
              kind: result.kind,
              markdown: result.markdown,
              charCount: result.char_count,
            })
          },
          onError: (message) =>
            patch(item.id, { status: 'error', error: message, message }),
        })
      } catch (err) {
        patch(item.id, { status: 'error', error: err.message, message: err.message })
      }
    },
    [addEntry, patch],
  )

  const addFiles = useCallback(
    (files) => {
      for (const file of files) {
        const id = nextId()
        if (file.size > MAX_BYTES) {
          setQueue((prev) => [
            {
              id,
              name: file.name,
              size: file.size,
              status: 'error',
              percent: 0,
              error: `File exceeds the 100 MB limit (${(file.size / 1048576).toFixed(0)} MB).`,
            },
            ...prev,
          ])
          continue
        }
        const item = { id, name: file.name, size: file.size, status: 'queued', percent: 0 }
        setQueue((prev) => [item, ...prev])
        run(item, () => startFileConversion(file))
      }
    },
    [run],
  )

  const submitUrl = useCallback(
    (e) => {
      e.preventDefault()
      const trimmed = url.trim()
      if (!/^https?:\/\//i.test(trimmed)) return
      const item = { id: nextId(), name: trimmed, size: null, status: 'queued', percent: 0 }
      setQueue((prev) => [item, ...prev])
      run(item, () => startUrlConversion(trimmed))
      setUrl('')
    },
    [run, url],
  )

  const onDrop = useCallback(
    (e) => {
      e.preventDefault()
      setDragging(false)
      if (e.dataTransfer.files?.length) addFiles(Array.from(e.dataTransfer.files))
    },
    [addFiles],
  )

  const removeItem = (id) => setQueue((prev) => prev.filter((it) => it.id !== id))

  return (
    <div className="flex flex-col gap-4">
      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`group relative flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-14 text-center transition-all ${
          dragging
            ? 'border-accent bg-accent/5 scale-[1.01]'
            : 'border-border bg-surface hover:border-accent/60 hover:bg-elevated'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) addFiles(Array.from(e.target.files))
            e.target.value = ''
          }}
        />
        <div
          className={`flex h-16 w-16 items-center justify-center rounded-2xl border border-border bg-elevated transition-colors ${
            dragging ? 'text-accent' : 'text-muted group-hover:text-accent'
          }`}
        >
          <UploadCloud className="h-8 w-8" />
        </div>
        <div>
          <p className="text-lg font-semibold text-white">
            Drop files here, or <span className="text-accent">browse</span>
          </p>
          <p className="mt-1 text-sm text-muted">
            PDF · DOCX · PPTX · XLSX · images · audio · video · CSV · JSON · HTML · EPUB · ZIP
          </p>
          <p className="mt-0.5 text-xs text-muted/70">Up to 100 MB per file</p>
        </div>
      </div>

      {/* URL bar */}
      <form onSubmit={submitUrl} className="flex items-center gap-2">
        <div className="flex flex-1 items-center gap-2 rounded-xl border border-border bg-surface px-3 focus-within:border-accent/70">
          <Link2 className="h-4 w-4 shrink-0 text-muted" />
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="…or paste a URL / YouTube link"
            className="w-full bg-transparent py-2.5 text-sm text-white placeholder:text-muted focus:outline-none"
          />
        </div>
        <button
          type="submit"
          disabled={!/^https?:\/\//i.test(url.trim())}
          className="rounded-xl bg-accent px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
        >
          Convert
        </button>
      </form>

      {/* Queue */}
      {queue.length > 0 && (
        <ul className="flex flex-col gap-2">
          {queue.map((item) => (
            <QueueRow key={item.id} item={item} onRemove={() => removeItem(item.id)} />
          ))}
        </ul>
      )}
    </div>
  )
}

function QueueRow({ item, onRemove }) {
  const { status, percent = 0, message, error, name, size } = item
  return (
    <li className="animate-fade-in rounded-xl border border-border bg-surface p-3">
      <div className="flex items-center gap-3">
        <StatusIcon status={status} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-white" title={name}>
              {name}
            </span>
            <FileTypeBadge name={name} size={size} className="shrink-0" />
          </div>
          {status !== 'done' && status !== 'error' && (
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-elevated">
              <div
                className="h-full rounded-full bg-accent transition-all duration-300"
                style={{ width: `${percent}%` }}
              />
            </div>
          )}
          <p
            className={`mt-1 truncate text-xs ${
              status === 'error' ? 'text-rose-400' : 'text-muted'
            }`}
          >
            {status === 'error' ? error : message || 'Queued…'}
          </p>
        </div>
        <button
          onClick={onRemove}
          className="rounded-md p-1 text-muted transition-colors hover:bg-elevated hover:text-white"
          aria-label="Remove from queue"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </li>
  )
}

function StatusIcon({ status }) {
  if (status === 'done')
    return <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-400" />
  if (status === 'error') return <AlertCircle className="h-5 w-5 shrink-0 text-rose-400" />
  return <Loader2 className="h-5 w-5 shrink-0 animate-spin text-accent" />
}
