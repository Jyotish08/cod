import type {
  ExecutionRequestDTO,
  ExecutionResponseDTO,
  ProblemSummaryDTO,
  ProblemWorkspaceDTO,
  SubmissionHistoryDTO,
} from '@contracts/types'

export interface CatalogQuery {
  difficulty?: 'EASY' | 'MEDIUM' | 'HARD'
  tag?: string
  search?: string
  limit?: number
  offset?: number
}

export interface UserStatsDTO {
  solved_by_difficulty: Record<'Easy' | 'Medium' | 'Hard', number>
  total_submissions: number
  acceptance_rate: number
  recent_activity: SubmissionHistoryDTO[]
}

export interface IOJClientPort {
  listProblems(query?: CatalogQuery): Promise<ProblemSummaryDTO[]>
  getWorkspaceProblem(slug: string | number): Promise<ProblemWorkspaceDTO>
  executeCode(payload: ExecutionRequestDTO): Promise<ExecutionResponseDTO>
  getSubmissions(problemId: number): Promise<SubmissionHistoryDTO[]>
  getStats(): Promise<UserStatsDTO>
}

export class HttpOJClientAdapter implements IOJClientPort {
  constructor(private readonly baseUrl = 'http://localhost:8000/api') {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
    if (!response.ok) {
      const message = await response.text()
      throw new Error(message || `Request failed (${response.status})`)
    }
    return response.json() as Promise<T>
  }

  listProblems(query: CatalogQuery = {}) {
    const params = new URLSearchParams({ limit: String(query.limit ?? 50), offset: String(query.offset ?? 0) })
    if (query.difficulty) params.set('difficulty', query.difficulty)
    if (query.tag) params.set('tag', query.tag)
    if (query.search) params.set('search', query.search)
    return this.request<ProblemSummaryDTO[]>(`/problems?${params}`)
  }

  getWorkspaceProblem(slug: string | number) {
    return this.request<ProblemWorkspaceDTO>(`/problems/${encodeURIComponent(slug)}`)
  }

  executeCode(payload: ExecutionRequestDTO) {
    return this.request<ExecutionResponseDTO>('/execute', { method: 'POST', body: JSON.stringify(payload) })
  }

  getSubmissions(problemId: number) {
    return this.request<SubmissionHistoryDTO[]>(`/problems/${problemId}/submissions`)
  }

  getStats() {
    return this.request<UserStatsDTO>('/stats')
  }
}

const mockProblem: ProblemWorkspaceDTO = {
  id: 1,
  slug: 'two-sum',
  title: 'Two Sum',
  difficulty: 'EASY',
  statement_md: 'Given an array of integers nums and an integer target, return the indices of two numbers that add up to target.',
  constraints_md: 'Exactly one solution exists. You may not use the same element twice.',
  tags: ['Array', 'Hash Table'],
  templates: { python: 'class Solution:\n    def twoSum(self, nums: list[int], target: int) -> list[int]:\n        pass' },
  sample_test_cases: [
    { input_data: 'nums = [2,7,11,15], target = 9', expected_output: '[0, 1]', is_sample: true, order_index: 0 },
  ],
  time_limit_ms: 2000,
  memory_limit_kb: 262144,
}

export class MockOJClientAdapter implements IOJClientPort {
  async listProblems(): Promise<ProblemSummaryDTO[]> {
    return [{ id: 1, slug: 'two-sum', title: 'Two Sum', difficulty: 'EASY', tags: ['Array', 'Hash Table'], is_ready_to_solve: true, user_status: 'UNSOLVED' }]
  }
  async getWorkspaceProblem(): Promise<ProblemWorkspaceDTO> { return mockProblem }
  async executeCode(payload: ExecutionRequestDTO): Promise<ExecutionResponseDTO> {
    const accepted = payload.source_code.includes('return')
    return {
      submission_id: `mock-${Date.now()}`,
      problem_id: payload.problem_id,
      overall_verdict: accepted ? 'AC' : 'WA',
      passed_count: accepted ? 1 : 0,
      total_count: 1,
      max_runtime_ms: 0.42,
      results: [{ test_case_index: 0, passed: accepted, verdict: accepted ? 'AC' : 'WA', input_data: 'nums = [2,7,11,15], target = 9', expected_output: '[0, 1]', actual_output: accepted ? '[0, 1]' : '[]', runtime_ms: 0.42 }],
      plugin_payloads: { ast_metrics: { cyclomatic_branches: 1, max_loop_nesting_depth: 0, has_recursion: false, line_count: payload.source_code.split('\n').length } },
    }
  }
  async getSubmissions(): Promise<SubmissionHistoryDTO[]> { return [] }
  async getStats(): Promise<UserStatsDTO> { return { solved_by_difficulty: { Easy: 0, Medium: 0, Hard: 0 }, total_submissions: 0, acceptance_rate: 0, recent_activity: [] } }
}

export const ojClient: IOJClientPort = import.meta.env.VITE_USE_MOCK === 'true'
  ? new MockOJClientAdapter()
  : new HttpOJClientAdapter()
