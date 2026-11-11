import { useEffect, useState, type ReactNode } from 'react'
import type { ProblemWorkspaceDTO } from '@contracts/types'

function splitStatement(problem: ProblemWorkspaceDTO) {
  const text = problem.statement_md.replace(/\uFFFD/g, '').replace(/\u00a0/g, ' ').trim()
  const exampleAt = text.search(/\n\s*Example\s+1\s*:/i)
  const constraintMatch = /\n\s*Constraints\s*:\s*/i.exec(text)
  const bodyEnd = [exampleAt, constraintMatch?.index ?? -1].filter(index => index >= 0).reduce((a, b) => Math.min(a, b), text.length)
  const body = text.slice(0, bodyEnd).trim()
  const extracted = constraintMatch ? text.slice(constraintMatch.index + constraintMatch[0].length).split(/\n\s*(?:Follow[- ]?up|Note)\s*:/i)[0].trim() : ''
  return { body, constraints: problem.constraints_md?.trim() || extracted }
}

function inlineCode(text: string): ReactNode[] {
  return text.split(/(`[^`]+`)/g).filter(Boolean).map((part, index) => part.startsWith('`') && part.endsWith('`')
    ? <code key={index}>{part.slice(1, -1)}</code> : <span key={index}>{part}</span>)
}

function StatementBody({ text }: { text: string }) {
  const blocks = text.split(/\n\s*\n/).map(block => block.trim()).filter(Boolean)
  return <div className="statement-body">{blocks.map((block, index) => {
    if (block.startsWith('```')) {
      const code = block.replace(/^```[^\n]*\n?/, '').replace(/```\s*$/, '')
      return <pre className="statement-code" key={index}><code>{code}</code></pre>
    }
    const lines = block.split('\n').map(line => line.trim()).filter(Boolean)
    if (lines.every(line => line.startsWith('- '))) return <ul className="statement-list" key={index}>{lines.map((line, i) => <li key={i}>{inlineCode(line.slice(2))}</li>)}</ul>
    return <p key={index}>{inlineCode(block.replace(/\n/g, ' '))}</p>
  })}</div>
}

export function DescriptionTab({ problem }: { problem: ProblemWorkspaceDTO }) {
  const { body, constraints } = splitStatement(problem)
  const examples = problem.sample_test_cases.slice(0, 2)
  const [bookmarked, setBookmarked] = useState(false)
  useEffect(() => setBookmarked(localStorage.getItem(`oj_bookmark_${problem.id}`) === 'true'), [problem.id])
  const toggleBookmark = () => {
    const next = !bookmarked
    setBookmarked(next)
    localStorage.setItem(`oj_bookmark_${problem.id}`, String(next))
    void fetch(`http://localhost:8000/api/problems/${problem.id}/bookmark?is_bookmarked=${next}`, { method: 'PATCH' }).catch(() => undefined)
  }
  return <div className="description-content">
    <header className="problem-title-block">
      <div className="problem-meta-line">
        <span className={`difficulty difficulty-${problem.difficulty.toLowerCase()}`}>{problem.difficulty.toLowerCase()}</span>
        <span className="problem-number">Problem {problem.id}</span>
      </div>
      <div className="problem-title-row">
        <h1>{problem.id}. {problem.title}</h1>
        <button className={`bookmark-problem ${bookmarked ? 'saved' : ''}`} aria-label={bookmarked ? 'Remove saved problem' : 'Save problem'} title={bookmarked ? 'Saved' : 'Save problem'} aria-pressed={bookmarked} onClick={toggleBookmark}>{bookmarked ? '★' : '☆'}</button>
      </div>
      <div className="problem-tags">{problem.tags.map(tag => <span className="tag-chip" key={tag}>{tag}</span>)}</div>
      <p className="problem-nudge">Take it one step at a time. Understand the pattern before coding.</p>
    </header>

    <section className="description-section">
      <h2 className="section-label">Problem</h2>
      <StatementBody text={body || problem.statement_md} />
    </section>

    <section className="example-section">
      <h2 className="section-label">Examples</h2>
      {examples.length ? <div className="examples-grid">{examples.map((test, index) => <article className="example-card" key={test.id ?? index}>
        <h3>Example {index + 1}</h3>
        <div className="example-row"><b>Input</b><code>{test.input_data}</code></div>
        <div className="example-row"><b>Output</b><code>{test.expected_output}</code></div>
        {test.explanation && <p className="example-explanation">{test.explanation}</p>}
      </article>)}</div> : <p className="subtle-copy">No sample examples are available yet.</p>}
    </section>

    {constraints && <section className="constraints-section">
      <h2 className="section-label">Constraints</h2>
      <StatementBody text={constraints} />
    </section>}
  </div>
}
