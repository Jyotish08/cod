export interface ASTMetricsView {
  cyclomatic_branches?: number
  max_loop_nesting_depth?: number
  has_recursion?: boolean
  recursive_functions?: string[]
  line_count?: number
  parse_error?: string
}

export function ASTTelemetryTab({ metrics }: { metrics?: ASTMetricsView }) {
  if (!metrics) return <div className="empty-card">Run or submit code to see AST telemetry.</div>
  const values = [
    ['Cyclomatic branches', metrics.cyclomatic_branches ?? '—'],
    ['Loop nesting depth', metrics.max_loop_nesting_depth ?? '—'],
    ['Source lines', metrics.line_count ?? '—'],
    ['Recursion', metrics.has_recursion === undefined ? '—' : metrics.has_recursion ? 'Detected' : 'Not detected'],
  ] as const
  return <div>
    <div className="mb-4 flex items-center gap-2">
      <span className="live-dot" />
      <h2 className="section-label !mb-0">Live AST telemetry</h2>
    </div>
    {metrics.parse_error && <div className="mb-4 rounded-xl border border-rose-400/20 bg-rose-400/5 p-3 text-sm text-rose-200">{metrics.parse_error}</div>}
    <div className="grid grid-cols-2 gap-3">
      {values.map(([label, value]) => <div className="metric-card" key={label}>
        <div className="text-xs text-slate-500">{label}</div>
        <div className="mt-2 text-xl font-semibold text-white">{value}</div>
      </div>)}
    </div>
    {!!metrics.recursive_functions?.length && <div className="mt-4 text-xs text-slate-400">Recursive functions: {metrics.recursive_functions.join(', ')}</div>}
    <p className="mt-5 text-xs leading-5 text-slate-500">Static measurements are attached after every execution by the backend plugin socket.</p>
  </div>
}
