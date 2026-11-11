import { useEffect, useState, type ReactNode } from 'react'

export interface WorkspaceTabPlugin {
  id: string
  label: string
  content: ReactNode
}

export function LeftDockSlot({ tabs, activeId: controlledId, onActiveIdChange }: {
  tabs: WorkspaceTabPlugin[]; activeId?: string; onActiveIdChange?: (id: string) => void
}) {
  const [localId, setLocalId] = useState(tabs[0]?.id ?? '')
  const activeId = controlledId ?? localId
  const active = tabs.find(tab => tab.id === activeId) ?? tabs[0]
  useEffect(() => {
    if (tabs.length && !tabs.some(tab => tab.id === activeId)) {
      const first = tabs[0].id
      setLocalId(first)
      onActiveIdChange?.(first)
    }
  }, [activeId, onActiveIdChange, tabs])
  return <section className="panel flex min-h-0 flex-col overflow-hidden">
    <div className="dock-tabs" role="tablist" aria-label="Workspace panels">
      {tabs.map(tab => <button key={tab.id} role="tab" aria-selected={tab.id === active?.id}
        className={`dock-tab ${tab.id === active?.id ? 'dock-tab-active' : ''}`} onClick={() => { setLocalId(tab.id); onActiveIdChange?.(tab.id) }}>
        {tab.label}
      </button>)}
    </div>
    <div className="min-h-0 flex-1 overflow-y-auto p-5" role="tabpanel">{active?.content}</div>
  </section>
}
