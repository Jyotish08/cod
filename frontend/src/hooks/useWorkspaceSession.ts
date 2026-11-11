import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ExecutionResponseDTO, ProblemWorkspaceDTO, SubmissionHistoryDTO } from '@contracts/types'
import { ojClient } from '../adapters/apiClient'

export type ExecutionState = 'IDLE' | 'RUNNING' | 'SUBMITTING'

export function useWorkspaceSession(slugOrId: string | number) {
  const [problem, setProblem] = useState<ProblemWorkspaceDTO | null>(null)
  const [language, setLanguage] = useState('python')
  const [code, setCode] = useState('')
  const [customInputs, setCustomInputs] = useState<string[]>([])
  const [response, setResponse] = useState<ExecutionResponseDTO | null>(null)
  const [history, setHistory] = useState<SubmissionHistoryDTO[]>([])
  const [executionState, setExecutionState] = useState<ExecutionState>('IDLE')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const preserveHistoricalCode = useRef(false)
  const draftKey = useMemo(() => problem ? `oj_draft_${problem.id}_${language}` : null, [language, problem])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    void ojClient.getWorkspaceProblem(slugOrId).then(async workspace => {
      if (!active) return
      setProblem(workspace)
      const key = `oj_draft_${workspace.id}_${language}`
      if (preserveHistoricalCode.current) preserveHistoricalCode.current = false
      else setCode(localStorage.getItem(key) ?? workspace.templates[language] ?? '')
      try { setHistory(await ojClient.getSubmissions(workspace.id)) } catch { setHistory([]) }
    }).catch(reason => {
      if (active) setError(reason instanceof Error ? reason.message : 'Could not load this problem')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [language, slugOrId])

  useEffect(() => {
    if (draftKey) localStorage.setItem(draftKey, code)
  }, [code, draftKey])

  const resetCode = useCallback(() => {
    if (problem) setCode(problem.templates[language] ?? '')
  }, [language, problem])

  const execute = useCallback(async (mode: 'run' | 'submit') => {
    if (!problem) return
    setExecutionState(mode === 'submit' ? 'SUBMITTING' : 'RUNNING')
    setError(null)
    try {
      const result = await ojClient.executeCode({ problem_id: problem.id, language, source_code: code, mode,
        custom_inputs: customInputs.length ? customInputs : null })
      setResponse(result)
      if (mode === 'submit') setHistory(await ojClient.getSubmissions(problem.id))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Execution failed')
    } finally {
      setExecutionState('IDLE')
    }
  }, [code, customInputs, language, problem])

  const loadHistoricalCode = useCallback((item: SubmissionHistoryDTO) => {
    preserveHistoricalCode.current = item.language !== language
    setLanguage(item.language)
    setCode(item.source_code)
    setResponse({ submission_id: item.id, problem_id: item.problem_id,
      overall_verdict: item.overall_verdict, passed_count: item.passed_count,
      total_count: item.total_count, max_runtime_ms: item.max_runtime_ms,
      results: [], plugin_payloads: { ast_metrics: item.ast_metrics } })
  }, [language])

  return { problem, language, setLanguage, code, setCode, customInputs, setCustomInputs,
    response, history, executionState, loading, error, resetCode, execute, loadHistoricalCode }
}
