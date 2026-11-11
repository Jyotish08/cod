import type { SubmissionHistoryDTO } from '@contracts/types'

export function SubmissionsTab({ submissions, onLoadCode }: {
  submissions: SubmissionHistoryDTO[]
  onLoadCode: (item: SubmissionHistoryDTO) => void
}) {
  return <div>
    <div className="mb-4 flex items-center justify-between">
      <h2 className="section-label !mb-0">Submission history</h2>
      <span className="text-xs text-slate-500">{submissions.length} recent</span>
    </div>
    {!submissions.length ? <div className="empty-card">Submitted solutions will appear here.</div> :
      <div className="space-y-2">
        {submissions.map(item => <button className="submission-row" key={item.id} onClick={() => onLoadCode(item)}>
          <span className={`verdict-pill verdict-${item.overall_verdict.toLowerCase()}`}>{item.overall_verdict}</span>
          <span className="min-w-0 flex-1 text-left">
            <span className="block text-sm text-slate-200">{item.passed_count}/{item.total_count} tests · {item.max_runtime_ms.toFixed(2)} ms</span>
            <span className="block text-xs text-slate-500">{new Date(item.created_at).toLocaleString()} · {item.language}</span>
          </span>
          <span className="text-xs text-slate-500">Load</span>
        </button>)}
      </div>}
  </div>
}
