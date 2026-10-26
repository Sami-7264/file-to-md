import { descriptorForName, formatBytes } from '../lib/fileTypes'

/**
 * A compact pill showing a file's type icon, type label, and (optionally) size.
 *
 * Props:
 *   name  - filename or URL used to infer the type
 *   size  - optional size in bytes
 *   className - extra classes
 */
export default function FileTypeBadge({ name, size, className = '' }) {
  const { label, icon: Icon, color } = descriptorForName(name)
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border border-border bg-elevated px-2 py-0.5 text-xs font-medium ${className}`}
    >
      <Icon className={`h-3.5 w-3.5 ${color}`} />
      <span className={color}>{label}</span>
      {size != null && (
        <>
          <span className="text-border">·</span>
          <span className="text-muted">{formatBytes(size)}</span>
        </>
      )}
    </span>
  )
}
