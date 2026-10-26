import {
  FileText,
  FileSpreadsheet,
  Presentation,
  Image as ImageIcon,
  Music,
  Video,
  Braces,
  Archive,
  BookOpen,
  Globe,
  Link as LinkIcon,
  File,
} from 'lucide-react'

// Maps a file extension (without dot) to a visual descriptor: a lucide icon,
// a short label, and a tailwind color class used by the FileTypeBadge.
const EXT_GROUPS = [
  { label: 'PDF', icon: FileText, color: 'text-rose-400', exts: ['pdf'] },
  {
    label: 'DOC',
    icon: FileText,
    color: 'text-sky-400',
    exts: ['doc', 'docx', 'rtf', 'odt', 'txt', 'md'],
  },
  {
    label: 'SHEET',
    icon: FileSpreadsheet,
    color: 'text-emerald-400',
    exts: ['xls', 'xlsx', 'ods', 'csv'],
  },
  {
    label: 'SLIDES',
    icon: Presentation,
    color: 'text-orange-400',
    exts: ['ppt', 'pptx', 'odp'],
  },
  {
    label: 'IMAGE',
    icon: ImageIcon,
    color: 'text-fuchsia-400',
    exts: ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'tif', 'webp', 'heic'],
  },
  {
    label: 'AUDIO',
    icon: Music,
    color: 'text-yellow-400',
    exts: ['mp3', 'wav', 'm4a', 'flac', 'ogg', 'aac'],
  },
  {
    label: 'VIDEO',
    icon: Video,
    color: 'text-purple-400',
    exts: ['mp4', 'mov', 'mkv', 'avi', 'webm'],
  },
  {
    label: 'DATA',
    icon: Braces,
    color: 'text-teal-400',
    exts: ['json', 'jsonl', 'xml', 'yaml', 'yml'],
  },
  { label: 'ZIP', icon: Archive, color: 'text-amber-400', exts: ['zip'] },
  { label: 'EPUB', icon: BookOpen, color: 'text-lime-400', exts: ['epub'] },
  { label: 'HTML', icon: Globe, color: 'text-cyan-400', exts: ['html', 'htm'] },
]

const FALLBACK = { label: 'FILE', icon: File, color: 'text-muted' }
const URL_DESC = { label: 'URL', icon: LinkIcon, color: 'text-indigo-400' }

export function descriptorForName(name = '') {
  if (/^https?:\/\//i.test(name)) return URL_DESC
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  for (const group of EXT_GROUPS) {
    if (group.exts.includes(ext)) return { ...group, ext }
  }
  return { ...FALLBACK, ext }
}

// Map the backend's FileKind value -> a descriptor (used when reloading history).
const KIND_TO_LABEL = {
  document: FileText,
  spreadsheet: FileSpreadsheet,
  presentation: Presentation,
  image: ImageIcon,
  audio: Music,
  video: Video,
  data: Braces,
  archive: Archive,
  ebook: BookOpen,
  web: Globe,
  url: LinkIcon,
}

export function iconForKind(kind) {
  return KIND_TO_LABEL[kind] ?? File
}

export function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let size = bytes
  let i = 0
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

export function formatCount(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

export function formatTime(ts) {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}
