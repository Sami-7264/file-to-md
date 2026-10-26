import { createContext, useCallback, useContext, useMemo, useState } from 'react'

/**
 * HistoryContext holds every conversion produced during the current session
 * plus the currently-selected entry. Centralizing it here avoids prop-drilling
 * the history/selection through DropZone, Viewer, and Sidebar.
 *
 * A history entry shape:
 *   {
 *     id, sourceName, outputName, kind, markdown, charCount, createdAt
 *   }
 */
const HistoryContext = createContext(null)

export function HistoryProvider({ children }) {
  const [history, setHistory] = useState([])
  const [activeId, setActiveId] = useState(null)

  // Add (or replace) an entry and make it the active selection.
  const addEntry = useCallback((entry) => {
    const normalized = { ...entry, createdAt: entry.createdAt ?? Date.now() }
    setHistory((prev) => {
      const without = prev.filter((e) => e.id !== normalized.id)
      return [normalized, ...without]
    })
    setActiveId(normalized.id)
  }, [])

  const selectEntry = useCallback((id) => setActiveId(id), [])

  const removeEntry = useCallback((id) => {
    setHistory((prev) => prev.filter((e) => e.id !== id))
    setActiveId((curr) => (curr === id ? null : curr))
  }, [])

  const clearHistory = useCallback(() => {
    setHistory([])
    setActiveId(null)
  }, [])

  const active = useMemo(
    () => history.find((e) => e.id === activeId) ?? null,
    [history, activeId],
  )

  const value = useMemo(
    () => ({
      history,
      active,
      activeId,
      addEntry,
      selectEntry,
      removeEntry,
      clearHistory,
    }),
    [history, active, activeId, addEntry, selectEntry, removeEntry, clearHistory],
  )

  return <HistoryContext.Provider value={value}>{children}</HistoryContext.Provider>
}

export function useHistory() {
  const ctx = useContext(HistoryContext)
  if (!ctx) throw new Error('useHistory must be used within a HistoryProvider')
  return ctx
}
