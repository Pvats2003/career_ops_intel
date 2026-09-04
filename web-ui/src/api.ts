import type {
  AnalyticsOut,
  ApplicationHistoryEventOut,
  AssistantResponseOut,
  CandidateProfileOut,
  CareerPathComparisonRowOut,
  CareerPathOut,
  CareerProfileOut,
  CompanyOut,
  CoverLetterOut,
  DashboardSummaryOut,
  FollowUpRecommendationOut,
  InsightsOut,
  JobDetailOut,
  JobListOut,
  MatchRunOut,
  MorningBriefingOut,
  NewSinceLastVisitOut,
  NotificationOut,
  PipelineItemOut,
  PipelineUpdateIn,
  RankedJobOut,
  ResumeUploadResult,
  ScanRunOut,
  SearchPreferencesIn,
  SearchPreferencesOut,
  SearchRunOut,
  SkillGapEntryOut,
  TailoredResumeOut,
  URLCheckResultOut,
  WatchlistEntryIn,
  WatchlistEntryOut,
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
  newSinceLastVisit: () => request<NewSinceLastVisitOut>('/dashboard/new-since-last-visit'),
  morningBriefing: () => request<MorningBriefingOut>('/dashboard/briefing'),

  candidateProfile: () => request<CandidateProfileOut>('/candidate/profile'),
  uploadResume: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<ResumeUploadResult>('/candidate/resume', { method: 'POST', body: form })
  },

  listJobs: (params: Record<string, string | number | boolean | undefined>) => {
    const search = new URLSearchParams()
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== '') search.set(key, String(value))
    }
    const qs = search.toString()
    return request<JobListOut>(`/jobs${qs ? `?${qs}` : ''}`)
  },
  getJob: (id: number) => request<JobDetailOut>(`/jobs/${id}`),
  saveJob: (id: number) => request<JobDetailOut>(`/jobs/${id}/save`, { method: 'POST' }),
  checkUrl: (id: number) => request<URLCheckResultOut>(`/jobs/${id}/check-url`, { method: 'POST' }),
  compareJobs: (ids: number[]) =>
    request<JobDetailOut[]>(`/jobs/compare?ids=${ids.join(',')}`),
  scanJobs: () => request<ScanRunOut>('/jobs/scan', { method: 'POST' }),
  matchJobs: () => request<MatchRunOut>('/jobs/match', { method: 'POST' }),
  runSearch: () => request<SearchRunOut>('/jobs/search-run', { method: 'POST' }),
  listSearchRuns: () => request<SearchRunOut[]>('/jobs/search-runs'),
  top10: () => request<RankedJobOut[]>('/jobs/top10'),
  applyNowQueue: () => request<RankedJobOut[]>('/jobs/apply-now'),
  tailorResume: (jobId: number) =>
    request<TailoredResumeOut>(`/jobs/${jobId}/tailor-resume`, { method: 'POST' }),
  coverLetter: (jobId: number) =>
    request<CoverLetterOut>(`/jobs/${jobId}/cover-letter`, { method: 'POST' }),
  askAssistant: (jobId: number, questions: string[]) =>
    request<AssistantResponseOut>(`/jobs/${jobId}/assistant`, {
      method: 'POST',
      body: JSON.stringify({ questions }),
    }),

  listPipeline: () => request<PipelineItemOut[]>('/pipeline'),
  updatePipelineItem: (applicationId: number, body: PipelineUpdateIn) =>
    request<PipelineItemOut>(`/pipeline/${applicationId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  removePipelineItem: (applicationId: number) =>
    request<void>(`/pipeline/${applicationId}`, { method: 'DELETE' }),
  applicationHistory: (applicationId: number) =>
    request<ApplicationHistoryEventOut[]>(`/pipeline/${applicationId}/history`),
  analytics: () => request<AnalyticsOut>('/pipeline/analytics'),
  followUps: () => request<FollowUpRecommendationOut[]>('/pipeline/follow-ups'),

  careerPaths: () => request<CareerPathOut[]>('/candidate/career-paths'),
  careerProfile: () => request<CareerProfileOut>('/candidate/career-profile'),
  careerPathComparison: () =>
    request<CareerPathComparisonRowOut[]>('/candidate/career-paths/compare'),
  skillGaps: () => request<SkillGapEntryOut[]>('/candidate/skill-gaps'),
  insights: () => request<InsightsOut>('/candidate/insights'),

  listCompanies: () => request<CompanyOut[]>('/companies'),
  getCompany: (id: number) => request<CompanyOut>(`/companies/${id}`),

  listWatchlist: () => request<WatchlistEntryOut[]>('/watchlist'),
  addWatchlistEntry: (body: WatchlistEntryIn) =>
    request<WatchlistEntryOut>('/watchlist', { method: 'POST', body: JSON.stringify(body) }),
  removeWatchlistEntry: (id: number) =>
    request<void>(`/watchlist/${id}`, { method: 'DELETE' }),

  listNotifications: (unreadOnly?: boolean) =>
    request<NotificationOut[]>(`/notifications${unreadOnly ? '?unread_only=true' : ''}`),
  markNotificationRead: (id: number) =>
    request<NotificationOut>(`/notifications/${id}/read`, { method: 'POST' }),

  getSearchPreferences: () => request<SearchPreferencesOut>('/settings/search-preferences'),
  updateSearchPreferences: (body: SearchPreferencesIn) =>
    request<SearchPreferencesOut>('/settings/search-preferences', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  supportedCountries: () => request<string[]>('/settings/supported-countries'),
}
