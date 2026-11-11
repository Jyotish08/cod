import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, Bell, Check, ChevronLeft, ChevronRight, Clock3, Code2, Lightbulb, Pause, Play, Terminal } from 'lucide-react'
import Dashboard from './Dashboard'
import { useProblemCatalog } from './hooks/useProblemCatalog'
import { useWorkspaceSession } from './hooks/useWorkspaceSession'
import type { ASTMetricsView } from './components/slots/ASTTelemetryTab'
import { ConsoleSlot } from './components/slots/ConsoleSlot'
import { DescriptionTab } from './components/slots/DescriptionTab'
import { EditorSlot } from './components/slots/EditorSlot'
import { LeftDockSlot, type WorkspaceTabPlugin } from './components/slots/LeftDockSlot'
import { SubmissionsTab } from './components/slots/SubmissionsTab'

function Workspace({ initialSlug, navigate }: { initialSlug: string; navigate: (path: string) => void }) {
  const catalog = useProblemCatalog()
  const [slug, setSlug] = useState(initialSlug)
  const [activeTab, setActiveTab] = useState('description')
  const [focusSeconds, setFocusSeconds] = useState(18 * 60)
  const [focusRunning, setFocusRunning] = useState(true)
  const [scratchpad, setScratchpad] = useState('')
  const [scratchpadProblemId, setScratchpadProblemId] = useState<number | null>(null)
  const [scratchpadOpen, setScratchpadOpen] = useState(false)
  const [notificationsOpen, setNotificationsOpen] = useState(false)

  useEffect(() => setSlug(initialSlug), [initialSlug])
  useEffect(() => {
    if (!focusRunning || focusSeconds <= 0) return
    const timer = window.setInterval(() => setFocusSeconds(value => Math.max(0, value - 1)), 1000)
    return () => window.clearInterval(timer)
  }, [focusRunning, focusSeconds])

  const workspace = useWorkspaceSession(slug)
  const problem = workspace.problem
  const metrics = workspace.response?.plugin_payloads?.ast_metrics as ASTMetricsView | undefined
  const options = catalog.problems
  const currentIndex = options.findIndex(item => item.slug === slug)
  const isBusy = workspace.executionState !== 'IDLE'
  const timeLabel = `${String(Math.floor(focusSeconds / 60)).padStart(2, '0')}:${String(focusSeconds % 60).padStart(2, '0')}`
  const availableLanguages = useMemo(() => Object.keys(problem?.templates ?? {}), [problem])

  useEffect(() => {
    if (!problem) return
    setScratchpad(localStorage.getItem(`oj_scratch_${problem.id}`) ?? '')
    setScratchpadProblemId(problem.id)
    setScratchpadOpen(false)
  }, [problem?.id])

  useEffect(() => {
    if (problem && scratchpadProblemId === problem.id) localStorage.setItem(`oj_scratch_${problem.id}`, scratchpad)
  }, [problem?.id, scratchpad, scratchpadProblemId])

  const openProblem = (index: number) => {
    const next = options[index]
    if (!next) return
    setSlug(next.slug)
    setActiveTab('description')
    navigate(`/problems/${next.slug}`)
  }

  const tags = problem?.tags ?? []
  const tabs: WorkspaceTabPlugin[] = problem ? [
    { id: 'description', label: 'Description', content: <DescriptionTab problem={problem} /> },
    { id: 'hints', label: 'Intuition & Hints', content: <HintsTab title={problem.title} tags={tags} /> },
    { id: 'editorial', label: 'Editorial', content: <UnavailableGuide title="Editorial" detail="A reviewed editorial has not been added for this problem yet." /> },
    { id: 'solutions', label: 'Solutions', content: <UnavailableGuide title="Solutions" detail="Work through the problem first. Saved reference solutions will appear here when they are available." /> },
    { id: 'submissions', label: 'Submissions', content: <SubmissionsTab submissions={workspace.history} onLoadCode={workspace.loadHistoricalCode} /> },
  ] : []

  return <div className="app-shell coding-shell">
    <header className="coding-topbar">
      <div className="coding-brand">
        <img src="/assets/dashboard/04_exact_ui_crops_png/crop_logo_cod_full.png" alt="Cod" />
      </div>
      <button className="back-to-problems" onClick={() => navigate('/')}><ArrowLeft size={18} /> Problem List</button>

      <div className="problem-navigation" aria-label="Problem navigation">
        <select aria-label="Choose a problem" value={slug} onChange={event => {
          const index = options.findIndex(item => item.slug === event.target.value)
          if (index >= 0) openProblem(index)
          else { setSlug(event.target.value); navigate(`/problems/${event.target.value}`) }
        }}>
          {!options.some(item => item.slug === slug) && <option value={slug}>{problem?.title ?? slug}</option>}
          {options.map(item => <option value={item.slug} key={item.id}>{item.id}. {item.title}</option>)}
        </select>
        <button aria-label="Previous problem" disabled={currentIndex <= 0} onClick={() => openProblem(currentIndex - 1)}><ChevronLeft size={19} /></button>
        <button aria-label="Next problem" disabled={currentIndex < 0 || currentIndex >= options.length - 1} onClick={() => openProblem(currentIndex + 1)}><ChevronRight size={19} /></button>
      </div>

      <button className={`focus-clock ${focusRunning ? 'is-running' : ''}`} onClick={() => setFocusRunning(value => !value)} aria-label={focusRunning ? 'Pause focus timer' : 'Resume focus timer'}>
        <Clock3 size={19} /><span>{timeLabel}</span><i />Focus Step {focusRunning ? <Pause size={14} /> : <Play size={14} />}
      </button>

      <div className="coding-actions">
        <button className="coding-run" disabled={isBusy || !problem} onClick={() => void workspace.execute('run')}><Play size={17} /> Run Code</button>
        <button className="coding-submit" disabled={isBusy || !problem} onClick={() => void workspace.execute('submit')}><Check size={18} /> Submit Solution</button>
        <button className="gentle-hint" onClick={() => setActiveTab('hints')}><Lightbulb size={18} /> Gentle Hint</button>
      </div>
      <span className="well-pill coding-well"><i />All is well</span>
      <div className="notification-wrap"><button className="icon-action" aria-label="Notifications" aria-expanded={notificationsOpen} onClick={() => setNotificationsOpen(value => !value)}><Bell size={19} /><b /></button>
        {notificationsOpen && <div className="notification-popover"><strong>All caught up</strong><span>You don’t have any new notifications.</span></div>}
      </div>
      <button className="icon-action terminal-action" aria-label="Open scratchpad" onClick={() => setScratchpadOpen(value => !value)}><Terminal size={19} /></button>
      <button className="coding-avatar" onClick={() => navigate('/profile')} aria-label="Open profile">J</button>
    </header>

    {catalog.error && <div className="inline-notice coding-notice">Problem navigation is offline. The current problem is still available.</div>}
    {workspace.error && <div className="inline-notice inline-error coding-notice">{workspace.error}</div>}
    {workspace.loading || !problem ? <div className="workspace-loading"><span className="loading-spinner" /> Loading problem workspace…</div> :
      <main className="coding-workspace">
        <section className="problem-pane" aria-label="Problem details">
          <LeftDockSlot tabs={tabs} activeId={activeTab} onActiveIdChange={setActiveTab} />
          <div className="hint-rail"><span>Hint 1 · Read the constraints</span><span>Hint 2 · Start with a simple approach</span><ChevronRight size={16} /></div>
        </section>
        <section className="coding-pane" aria-label="Code editor and test results">
          <div className="editor-pane">
            <EditorSlot code={workspace.code} onCodeChange={workspace.setCode} language={workspace.language}
              onLanguageChange={workspace.setLanguage} onRun={() => void workspace.execute('run')}
              onSubmit={() => void workspace.execute('submit')} onReset={workspace.resetCode} busy={isBusy}
              availableLanguages={availableLanguages} scratchpad={scratchpad} onScratchpadChange={setScratchpad}
              scratchpadOpen={scratchpadOpen} onScratchpadToggle={() => setScratchpadOpen(value => !value)} />
          </div>
          <div className="console-pane">
            <ConsoleSlot samples={problem.sample_test_cases} customInputs={workspace.customInputs}
              onCustomInputsChange={workspace.setCustomInputs} response={workspace.response} error={workspace.error}
              busy={isBusy} metrics={metrics} />
          </div>
        </section>
      </main>}
  </div>
}

function HintsTab({ title, tags }: { title: string; tags: string[] }) {
  const topic = tags[0] ?? 'the input structure'
  return <div className="guide-content">
    <span className="guide-eyebrow">A calm way in</span>
    <h2>Build your intuition</h2>
    <p className="guide-intro">Use these prompts to make a plan for <strong>{title}</strong> without giving away the implementation.</p>
    <article className="hint-card"><span>01</span><div><b>Understand the shape</b><p>Write down what the function receives and exactly what it must return. Try the smallest valid input by hand.</p></div></article>
    <article className="hint-card"><span>02</span><div><b>Look for repeated work</b><p>Notice whether a {topic.toLowerCase()} can be summarized or reused as you scan the input.</p></div></article>
    <article className="hint-card"><span>03</span><div><b>Let the limits guide you</b><p>Estimate how many steps a nested loop would take before choosing an approach.</p></div></article>
  </div>
}

function UnavailableGuide({ title, detail }: { title: string; detail: string }) {
  return <div className="guide-empty"><span className="guide-empty-icon"><Code2 size={22} /></span><h2>{title}</h2><p>{detail}</p></div>
}

export default function App() {
  const [path, setPath] = useState(window.location.pathname)
  const navigate = (next: string) => { window.history.pushState({}, '', next); setPath(next); window.scrollTo(0, 0) }
  useEffect(() => { const pop = () => setPath(window.location.pathname); window.addEventListener('popstate', pop); return () => window.removeEventListener('popstate', pop) }, [])
  if (path === '/') return <Dashboard navigate={navigate} />
  if (path === '/profile') return <div className="profile-placeholder"><a href="/" onClick={e => { e.preventDefault(); navigate('/') }}>← Problems</a><h1>Your Progress</h1><p>Detailed analytics will be available here.</p></div>
  const slug = path.startsWith('/problems/') ? decodeURIComponent(path.slice('/problems/'.length)) : 'two-sum'
  return <Workspace key={slug} initialSlug={slug} navigate={navigate} />
}
