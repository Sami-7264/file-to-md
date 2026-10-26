import { Trash2, History as HistoryIcon } from 'lucide-react'
import { useHistory } from '../context/HistoryContext'
import { iconForKind, formatCount, formatTime } from '../lib/fileTypes'

/**
 * Session history. Lists every conversion; clicking one reloads it into the
 * viewer. Shows a type icon, name, timestamp, and char count per entry.
 */
export default function HistorySidebar() {
  const { history, activeId, selectEntry, removeEntry, clearHistory } = useHistory()

  return (
    <aside className="flex h-full min-h-0 w-full flex-col rounded-2xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <HistoryIcon className="h-4 w-4 text-accent" />
          <h2 className="text-sm font-semibold text-white">History</h2>
          {history.length > 0 && (
            <span className="rounded-full bg-elevated px-1.5 py-0.5 text-xs text-muted">
              {history.length}
            </span>
          )}
        </div>
        {history.length > 0 && (
          <button
            onClick={clearHistory}
            className="text-xs text-muted transition-colors hover:text-rose-400"
          >
            Clear
          </button>
        )}
      </div>

      {history.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center px-4 py-8 text-center">
          <p className="text-sm text-muted">No conversions yet.</p>
          <p className="mt-1 text-xs text-muted/70">
            Converted files from this session will show up here.
          </p>
        </div>
      ) : (
        <ul className="min-h-0 flex-1 overflow-auto p-2">
          {history.map((entry) => {
            const Icon = iconForKind(entry.kind)
            const isActive = entry.id === activeId
            return (
              <li key={entry.id}>
                <button
                  onClick={() => selectEntry(entry.id)}
                  className={`group flex w-full items-start gap-3 rounded-lg p-2.5 text-left transition-colors ${
                    isActive ? 'bg-accent/10 ring-1 ring-accent/40' : 'hover:bg-elevated'
                  }`}
                >
                  <span
                    className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border ${
                      isActive ? 'bg-accent/20 text-accent' : 'bg-elevated text-muted'
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span
                      className="block truncate text-sm font-medium text-white"
                      title={entry.sourceName}
                    >
                      {entry.outputName}
                    </span>
                    <span className="mt-0.5 flex items-center gap-2 text-xs text-muted">
                      <span>{formatTime(entry.createdAt)}</span>
                      <span className="text-border">·</span>
                      <span>{formatCount(entry.charCount)} chars</span>
                    </span>
                  </span>
                  <span
                    onClick={(e) => {
                      e.stopPropagation()
                      removeEntry(entry.id)
                    }}
                    role="button"
                    tabIndex={-1}
                    className="rounded-md p-1 text-muted opacity-0 transition-all hover:text-rose-400 group-hover:opacity-100"
                    aria-label="Remove from history"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </aside>
  )
}
