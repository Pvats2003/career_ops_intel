import type {
  AnalyticsOut,
  CandidateProfileOut,
  DashboardSummaryOut,
  JobDetailOut,
  JobListOut,
  MatchRunOut,
  PipelineItemOut,
  PipelineUpdateIn,
  ResumeUploadResult,
  ScanRunOut,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: init?.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // non-JSON error body; fall back to statusText
    }
    throw new ApiError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string }>('/health'),

  dashboardSummary: () => request<DashboardSummaryOut>('/dashboard/summary'),

  candidateProfile: () => request<CandidateProfileOut>('/candidate/profile'),
  uploadResume: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<ResumeUploadResult>('/candidate/resume', { method: 'POST', body: form })
  },

  listJobs: (params: Record<string, string | number | undefined>) => {
    const search = new URLSearchParams()
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== '') search.set(key, String(value))
    }
    const qs = search.toString()
    return request<JobListOut>(`/jobs${qs ? `?${qs}` : ''}`)
  },
  getJob: (id: number) => request<JobDetailOut>(`/jobs/${id}`),
  saveJob: (id: number) => request<JobDetailOut>(`/jobs/${id}/save`, { method: 'POST' }),
  scanJobs: () => request<ScanRunOut>('/jobs/scan', { method: 'POST' }),
  matchJobs: () => request<MatchRunOut>('/jobs/match', { method: 'POST' }),

  listPipeline: () => request<PipelineItemOut[]>('/pipeline'),
  updatePipelineItem: (applicationId: number, body: PipelineUpdateIn) =>
    request<PipelineItemOut>(`/pipeline/${applicationId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  removePipelineItem: (applicationId: number) =>
    request<void>(`/pipeline/${applicationId}`, { method: 'DELETE' }),
  analytics: () => request<AnalyticsOut>('/pipeline/analytics'),
}
