import { useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import {
  Columns2,
  Eye,
  Code2,
  Copy,
  Check,
  Download,
  Sparkles,
  FileText,
} from 'lucide-react'
import { useHistory } from '../context/HistoryContext'
import { downloadUrl } from '../lib/api'
import { buildSpecMarkdown } from '../lib/spec'

const VIEWS = [
  { key: 'both', label: 'Both', icon: Columns2 },
  { key: 'preview', label: 'Preview', icon: Eye },
  { key: 'raw', label: 'Raw', icon: Code2 },
]

/**
 * Split-pane markdown viewer for the active conversion result. Left = raw
 * source, right = rendered preview. Includes copy, copy-as-SPEC, and download.
 */
export default function MarkdownViewer() {
  const { active } = useHistory()
  const [view, setView] = useState('both')
  const [copied, setCopied] = useState(null) // 'raw' | 'spec' | null

  const markdown = active?.markdown ?? ''

  const copy = async (text, tag) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(tag)
      setTimeout(() => setCopied(null), 1600)
    } catch {
      /* clipboard may be unavailable over http; silently ignore */
    }
  }

  if (!active) return <EmptyState />

  return (
    <div className="flex h-full min-h-0 flex-col rounded-2xl border border-border bg-surface">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <FileText className="h-4 w-4 shrink-0 text-accent" />
          <span className="truncate text-sm font-medium text-white" title={active.outputName}>
            {active.outputName}
          </span>
          <span className="shrink-0 text-xs text-muted">
            {active.charCount.toLocaleString()} chars
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* View toggle */}
          <div className="flex rounded-lg border border-border bg-elevated p-0.5">
            {VIEWS.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setView(key)}
                className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  view === key ? 'bg-accent text-white' : 'text-muted hover:text-white'
                }`}
                title={label}
              >
                <Icon className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">{label}</span>
              </button>
            ))}
          </div>

          <ToolbarButton
            onClick={() => copy(markdown, 'raw')}
            icon={copied === 'raw' ? Check : Copy}
            label={copied === 'raw' ? 'Copied' : 'Copy'}
            active={copied === 'raw'}
          />
          <ToolbarButton
            onClick={() => copy(buildSpecMarkdown(active), 'spec')}
            icon={copied === 'spec' ? Check : Sparkles}
            label={copied === 'spec' ? 'Copied' : 'Copy SPEC'}
            active={copied === 'spec'}
            title="Copy as a Claude Code SPEC.md with scaffolding instructions"
          />
          <a
            href={downloadUrl(active.id)}
            download={active.outputName}
            className="flex items-center gap-1.5 rounded-lg bg-accent px-2.5 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent-hover"
          >
            <Download className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Download</span>
          </a>
        </div>
      </div>

      {/* Panes */}
      <div
        className={`grid min-h-0 flex-1 ${
          view === 'both' ? 'grid-cols-1 md:grid-cols-2' : 'grid-cols-1'
        }`}
      >
        {(view === 'raw' || view === 'both') && (
          <pre className="min-h-0 overflow-auto whitespace-pre-wrap break-words border-border p-4 font-mono text-[13px] leading-relaxed text-[#c5c5d2] md:border-r">
            {markdown}
          </pre>
        )}
        {(view === 'preview' || view === 'both') && (
          <div className="prose-md min-h-0 overflow-auto p-5">
            <Rendered markdown={markdown} />
          </div>
        )}
      </div>
    </div>
  )
}

function Rendered({ markdown }) {
  // Memoize so re-renders (e.g. view toggles) don't re-parse a large document.
  return useMemo(
    () => (
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ inline, className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            if (inline || !match) {
              return (
                <code className={className} {...props}>
                  {children}
                </code>
              )
            }
            return (
              <SyntaxHighlighter
                style={oneDark}
                language={match[1]}
                PreTag="div"
                customStyle={{ margin: 0, background: '#16161b', fontSize: '0.85rem' }}
              >
                {String(children).replace(/\n$/, '')}
              </SyntaxHighlighter>
            )
          },
        }}
      >
        {markdown}
      </ReactMarkdown>
    ),
    [markdown],
  )
}

function ToolbarButton({ onClick, icon: Icon, label, active, title }) {
  return (
    <button
      onClick={onClick}
      title={title || label}
      className={`flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium transition-colors ${
        active ? 'border-emerald-500/50 text-emerald-400' : 'text-muted hover:bg-elevated hover:text-white'
      }`}
    >
      <Icon className="h-3.5 w-3.5" />
      <span className="hidden sm:inline">{label}</span>
    </button>
  )
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-surface p-10 text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-border bg-elevated text-muted">
        <FileText className="h-7 w-7" />
      </div>
      <p className="text-sm font-medium text-white">No conversion selected</p>
      <p className="mt-1 max-w-xs text-sm text-muted">
        Drop a file or paste a URL above. Your converted Markdown will appear here.
      </p>
    </div>
  )
}
