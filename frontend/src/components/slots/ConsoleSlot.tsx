import { useMemo, useState } from 'react'
import { Activity, Check, ChevronRight, Plus } from 'lucide-react'
import type { ExecutionResponseDTO, TestCaseContract } from '@contracts/types'
import { ASTTelemetryTab, type ASTMetricsView } from './ASTTelemetryTab'

type ConsoleTab = 'testcase' | 'result' | 'steps' | 'metrics'

export function ConsoleSlot({ samples, customInputs, onCustomInputsChange, response, error, busy, metrics }: {
  samples: TestCaseContract[]; customInputs: string[]; onCustomInputsChange: (inputs: string[]) => void
  response: ExecutionResponseDTO | null; error: string | null; busy: boolean; metrics?: ASTMetricsView
}) {
  const [tab, setTab] = useState<ConsoleTab>('result')
  const [selectedCase, setSelectedCase] = useState(0)
  const selectedResult = response?.results[selectedCase]
  const selectedSample = samples[selectedCase]
  const caseCount = response?.results.length || samples.length
  const statusClass = response?.overall_verdict.toLowerCase() ?? 'pending'
  const inputValue = selectedResult?.input_data ?? selectedSample?.input_data
  const tabItems = useMemo(() => [
    ['testcase', 'Testcase'], ['result', 'Test Result'], ['steps', 'Step Visualizer'], ['metrics', 'Sandbox Metrics'],
  ] as const, [])

  const updateCustomInputs = (value: string) => onCustomInputsChange(value.split('\n').filter(line => line.length > 0))
  return <section className="panel console-panel">
    <div className="console-tabs" role="tablist" aria-label="Run details">
      {tabItems.map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id}
        className={`console-tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>
        {id === 'metrics' && <Activity size={15} />}{label}{id === 'result' && response?.overall_verdict === 'AC' && <Check size={15} className="tab-check" />}
      </button>)}
    </div>

    <div className="console-content">
      {tab === 'testcase' && <div className="testcase-view">
        <div className="case-picker-row">
          <div className="case-picker">
            {(samples.length ? samples : customInputs.map(input => ({ input_data: input, expected_output: '', is_sample: false }))).slice(0, 20).map((item, index) =>
              <button key={('id' in item ? item.id : null) ?? index} className={`case-select ${selectedCase === index ? 'selected' : ''}`} onClick={() => setSelectedCase(index)}>
                {response?.results[index]?.passed && <Check size={13} />}Case {index + 1}
              </button>)}
          </div>
          <button className="add-case-button" onClick={() => { setTab('testcase'); onCustomInputsChange([...customInputs, '']); }}><Plus size={16} /> Add Custom Case</button>
        </div>
        {customInputs.length > 0 && <div className="custom-case-editor">
          <label htmlFor="custom-case-input">Custom inputs <span>One serialized input per line</span></label>
          <textarea id="custom-case-input" value={customInputs.join('\n')} onChange={event => updateCustomInputs(event.target.value)} placeholder={'nums = [2, 7, 11, 15], target = 9'} />
        </div>}
        <div className="case-input-preview">
          <span>Input</span><pre>{inputValue ?? 'Select a case to inspect its input.'}</pre>
        </div>
      </div>}

      {tab === 'result' && <div className="result-view">
        {busy && <div className="run-progress"><span className="loading-spinner" /> Running your solution against the selected cases…</div>}
        {error && <div className="run-error">{error}</div>}
        {response ? <>
          <div className="result-summary">
            <span className={`result-verdict ${statusClass}`}>{response.overall_verdict === 'AC' && <Check size={15} />}{response.overall_verdict === 'AC' ? 'Accepted' : response.overall_verdict}</span>
            <span className="passed-count">{response.passed_count} / {response.total_count} cases passed</span>
            <span className="result-metric">Runtime <b>{response.max_runtime_ms.toFixed(2)} ms</b></span>
          </div>
          <div className="case-picker-row result-case-row">
            <div className="case-picker">
              {response.results.slice(0, 30).map((result, index) => <button key={result.test_case_index}
                className={`case-select ${selectedCase === index ? 'selected' : ''} ${result.passed ? 'passed' : 'failed'}`}
                onClick={() => setSelectedCase(index)} title={`Case ${index + 1}: ${result.verdict}`}>
                {result.passed && <Check size={13} />}Case {index + 1}
              </button>)}
            </div>
            <button className="add-case-button" onClick={() => setTab('testcase')}><Plus size={16} /> Add Custom Case</button>
          </div>
          {selectedResult ? <div className="result-columns">
            <ResultCard label="Input" value={selectedResult.input_data ?? selectedSample?.input_data ?? 'Input is hidden for this test.'} />
            <ResultCard label="Your Output" value={selectedResult.actual_output ?? selectedResult.error_message ?? 'No output recorded.'} tone={selectedResult.passed ? 'sage' : 'rose'} />
            <ResultCard label="Expected" value={selectedResult.expected_output ?? selectedSample?.expected_output ?? 'Expected output is hidden for this test.'} />
          </div> : <div className="empty-result">Run your code to see input, output, and expected result side by side.</div>}
        </> : <div className="empty-result"><span className="empty-result-icon"><Check size={19} /></span><b>Ready when you are</b><p>Run your code to compare it with the sample cases.</p></div>}
        {!response && !busy && !error && caseCount > 0 && <span className="sample-count">{caseCount} sample {caseCount === 1 ? 'case' : 'cases'} ready</span>}
      </div>}

      {tab === 'steps' && <div className="step-view">
        <div className="step-icon"><ChevronRight size={20} /></div><div><b>Step-by-step view</b><p>This workspace does not have a runtime trace for the selected run. Use the editor and case results to walk through your code manually.</p></div>
      </div>}
      {tab === 'metrics' && <div className="metrics-view"><ASTTelemetryTab metrics={metrics} /></div>}
    </div>
  </section>
}

function ResultCard({ label, value, tone = '' }: { label: string; value: string; tone?: string }) {
  return <article className={`result-output-card ${tone}`}><h3>{label}</h3><pre>{value}</pre></article>
}
