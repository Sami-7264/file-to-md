import { useEffect, useState } from 'react'
import { FileDown, Github, CircleDot } from 'lucide-react'
import DropZone from './components/DropZone'
import MarkdownViewer from './components/MarkdownViewer'
import HistorySidebar from './components/HistorySidebar'
import { API_BASE } from './lib/api'

/**
 * Top-level layout:
 *   ┌───────────────────────────────────────────────┐
 *   │ header                                          │
 *   ├──────────┬──────────────────────────────────────┤
 *   │ history  │ dropzone (hero)                       │
 *   │ sidebar  │ markdown viewer (split pane)          │
 *   └──────────┴──────────────────────────────────────┘
 */
export default function App() {
  const online = useBackendHealth()

  return (
    <div className="flex h-screen flex-col bg-bg">
      <header className="flex items-center justify-between border-b border-border px-5 py-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-white">
            <FileDown className="h-4.5 w-4.5" />
          </div>
          <div className="leading-tight">
            <h1 className="text-sm font-semibold text-white">
              File <span className="text-muted">→</span> Markdown
            </h1>
            <p className="text-xs text-muted">Powered by Microsoft MarkItDown</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <BackendStatus online={online} />
          <a
            href="https://github.com/microsoft/markitdown"
            target="_blank"
            rel="noreferrer"
            className="text-muted transition-colors hover:text-white"
            title="MarkItDown on GitHub"
          >
            <Github className="h-5 w-5" />
          </a>
        </div>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-4 p-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="hidden min-h-0 lg:block">
          <HistorySidebar />
        </div>

        <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-4">
          <DropZone />
          <MarkdownViewer />
        </div>
      </main>
    </div>
  )
}

function BackendStatus({ online }) {
  const color =
    online === null ? 'text-muted' : online ? 'text-emerald-400' : 'text-rose-400'
  const label = online === null ? 'Connecting…' : online ? 'Backend online' : 'Backend offline'
  return (
    <span className={`flex items-center gap-1.5 text-xs ${color}`}>
      <CircleDot className="h-3.5 w-3.5" />
      {label}
    </span>
  )
}

// Poll /health so the header reflects backend availability.
function useBackendHealth() {
  const [online, setOnline] = useState(null)
  useEffect(() => {
    let alive = true
    const check = async () => {
      try {
        const res = await fetch(`${API_BASE}/health`)
        if (alive) setOnline(res.ok)
      } catch {
        if (alive) setOnline(false)
      }
    }
    check()
    const id = setInterval(check, 10000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])
  return online
}
