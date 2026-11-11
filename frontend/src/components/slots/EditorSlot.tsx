import { useEffect, useRef, useState, type ComponentType, type KeyboardEvent } from 'react'
import { RotateCcw } from 'lucide-react'

type MonacoProps = { height: string; language: string; theme: string; value: string; onChange: (value?: string) => void; onMount: (editor: any, monaco: any) => void; options: Record<string, unknown> }
type MonacoComponent = ComponentType<MonacoProps>

export function EditorSlot({ code, onCodeChange, language, onLanguageChange, onRun, onSubmit, onReset, busy,
  availableLanguages, scratchpad, onScratchpadChange, scratchpadOpen, onScratchpadToggle }: {
  code: string; onCodeChange: (code: string) => void; language: string; onLanguageChange: (language: string) => void
  onRun: () => void; onSubmit: () => void; onReset: () => void; busy: boolean; availableLanguages: string[]
  scratchpad: string; onScratchpadChange: (value: string) => void; scratchpadOpen: boolean; onScratchpadToggle: () => void
}) {
  const [Monaco, setMonaco] = useState<MonacoComponent | null>(null)
  const [editorFailed, setEditorFailed] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [fontSize, setFontSize] = useState(14)
  const editorRef = useRef<any>(null)

  useEffect(() => {
    let active = true
    const fallbackTimer = window.setTimeout(() => { if (active && !editorRef.current) setEditorFailed(true) }, 8000)
    import('@monaco-editor/react').then(module => { if (active) setMonaco(() => module.default as MonacoComponent) })
      .catch(() => { if (active) setEditorFailed(true) })
    return () => { active = false; window.clearTimeout(fallbackTimer) }
  }, [])

  const onMount = (editor: any, monaco: any) => {
    editorRef.current = editor
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, onRun)
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.Enter, onSubmit)
  }

  const onFallbackKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault()
      if (event.shiftKey) onSubmit(); else onRun()
    }
    if (!scratchpadOpen && event.key === 'Tab') {
      event.preventDefault()
      const field = event.currentTarget
      const start = field.selectionStart; const end = field.selectionEnd
      const next = `${code.slice(0, start)}    ${code.slice(end)}`
      onCodeChange(next)
      requestAnimationFrame(() => { field.selectionStart = field.selectionEnd = start + 4 })
    }
  }

  const languageLabel = (value: string) => value === 'python' ? 'Python 3' : value === 'javascript' ? 'JavaScript' : value.toUpperCase()
  return <section className="panel editor-panel">
    <div className="editor-toolbar">
      <div className="editor-toolbar-left">
        <label className="language-control"><span className="sr-only">Language</span>
          <select value={language} onChange={event => onLanguageChange(event.target.value)} aria-label="Programming language">
            {(availableLanguages.length ? availableLanguages : [language]).map(value => <option key={value} value={value}>{languageLabel(value)}</option>)}
          </select>
        </label>
        <button className={`scratchpad-toggle ${scratchpadOpen ? 'active' : ''}`} onClick={onScratchpadToggle}>
          {scratchpadOpen ? 'Solution editor' : 'Scratchpad / Dry Run Notes'}
        </button>
      </div>
      <div className="editor-toolbar-right">
        <span className="saved-state"><i />Saved</span>
        <button className="editor-icon-button" aria-label="Reset code to starter template" title="Reset template" onClick={onReset}><RotateCcw size={17} /></button>
        <button className="editor-icon-button editor-settings" aria-label="Editor settings" title="Editor settings" aria-expanded={settingsOpen} onClick={() => setSettingsOpen(value => !value)}><span>⚙</span></button>
      </div>
      {settingsOpen && <div className="editor-settings-popover"><label htmlFor="editor-font-size">Editor font size</label><select id="editor-font-size" value={fontSize} onChange={event => setFontSize(Number(event.target.value))}><option value={12}>12 px</option><option value={14}>14 px</option><option value={16}>16 px</option><option value={18}>18 px</option></select></div>}
    </div>
    <div className="editor-surface">
      {scratchpadOpen ? <div className="scratchpad-wrap">
        <div className="scratchpad-heading"><span>Dry run notes</span><small>Private to this device · not submitted</small></div>
        <textarea aria-label="Scratchpad notes" className="scratchpad-editor" value={scratchpad} onChange={event => onScratchpadChange(event.target.value)} placeholder={'Try a small example…\n\nWhat information should you keep as you scan?'} />
      </div> : Monaco && !editorFailed ? <Monaco height="100%" language={language === 'cpp' ? 'cpp' : language} theme="vs"
        value={code} onChange={value => onCodeChange(value ?? '')} onMount={onMount}
        options={{ minimap: { enabled: false }, fontSize, fontFamily: 'JetBrains Mono, Consolas, monospace', padding: { top: 18 }, scrollBeyondLastLine: false, automaticLayout: true, tabSize: 4, lineNumbersMinChars: 3, renderLineHighlight: 'line' }} /> :
        <textarea aria-label="Code editor" className="fallback-editor" value={code} onChange={event => onCodeChange(event.target.value)} onKeyDown={onFallbackKeyDown} spellCheck={false} />}
      {editorFailed && !scratchpadOpen && <span className="editor-mode-badge">Text editor mode</span>}
    </div>
    <div className="editor-statusbar">
      {scratchpadOpen ? <span>Scratchpad</span> : <span>Solution · {languageLabel(language)}</span>}
      <span>{busy ? 'Running…' : '⌃↵ Run  ·  ⌃⇧↵ Submit'}</span>
    </div>
  </section>
}
