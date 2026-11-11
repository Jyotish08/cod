import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ProblemSummaryDTO } from '@contracts/types'
import { ojClient, type UserStatsDTO } from '../adapters/apiClient'

export function useProblemCatalog() {
  const [problems, setProblems] = useState<ProblemSummaryDTO[]>([])
  const [stats, setStats] = useState<UserStatsDTO | null>(null)
  const [difficulty, setDifficulty] = useState<'EASY' | 'MEDIUM' | 'HARD' | ''>('')
  const [tagSearch, setTagSearch] = useState('')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'SOLVED' | 'ATTEMPTED' | 'UNSOLVED'>('ALL')
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const pageSize = 50

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [items, summary] = await Promise.all([
        ojClient.listProblems({ difficulty: difficulty || undefined, tag: tagSearch || undefined, search: search || undefined, limit: pageSize, offset: page * pageSize }),
        ojClient.getStats(),
      ])
      setProblems(items)
      setStats(summary)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not load the catalog')
    } finally {
      setLoading(false)
    }
  }, [difficulty, page, search, tagSearch])

  useEffect(() => { void refresh() }, [refresh])

  const visibleProblems = useMemo(() => problems.filter(problem => statusFilter === 'ALL' || problem.user_status === statusFilter), [problems, statusFilter])
  const setDifficultyFilter = (value: 'EASY' | 'MEDIUM' | 'HARD' | '') => { setPage(0); setDifficulty(value) }
  const setTagFilter = (value: string) => { setPage(0); setTagSearch(value) }
  const setSearchFilter = (value: string) => { setPage(0); setSearch(value) }

  return { problems: visibleProblems, stats, difficulty, tagSearch, search, statusFilter, page, pageSize, loading, error,
    setDifficulty: setDifficultyFilter, setTagSearch: setTagFilter, setSearch: setSearchFilter,
    setStatusFilter, setPage, refresh }
}
