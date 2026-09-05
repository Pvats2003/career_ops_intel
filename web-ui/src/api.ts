import type {
  AnalyticsOut,
  ApplicationHistoryEventOut,
  AssistantResponseOut,
  CandidateProfileOut,
  CareerChatIn,
  CareerChatOut,
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
  SchedulerStatusOut,
  SearchPreferencesIn,
  SearchPreferencesOut,
  SearchRunOut,
  SourceHealthOut,
  SkillGapEntryOut,
  TailoredResumeOut,
  URLCheckResultOut,
  WatchlistEntryIn,
  WatchlistEntryOut,
  WatchlistEntrySummaryOut,
  WhyBreakdownOut,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// Dashboard-loading forensic audit: `request()` used to call plain
// `fetch()` with no timeout at all, so a genuinely slow backend response
// (e.g. an N+1 query pattern at production job-count scale) left the
// calling page's loading state stuck indefinitely with no way to fail
// visibly. Two deliberately different deadlines, not one universal one —
// a normal dashboard/read GET should fail fast enough to show an error
// instead of hanging forever, but an intentionally long-running
// operation (a full search, a scan, a matching run, or anything that
// calls the LLM) must never be aborted just for taking longer than a
// short UI read timeout would allow.
const DEFAULT_TIMEOUT_MS = 20_000
const LONG_RUNNING_TIMEOUT_MS = 5 * 60_000

interface RequestOptions extends RequestInit {
  /** Overrides the default read timeout — pass `LONG_RUNNING_TIMEOUT_MS`
   * (via the endpoints below that already do) for anything that
   * legitimately takes minutes, never a raw number scattered ad hoc. */
  timeoutMs?: number
}

async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...requestInit } = init ?? {}
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs)

  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      headers:
        requestInit.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
      ...requestInit,
      signal: controller.signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(
        0,
        'The request took too long and was cancelled. Please check your connection and try again.',
      )
    }
    throw err
  } finally {
    window.clearTimeout(timeoutId)
  }

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
    // Long-running: parses/validates the resume, which can call the LLM.
    return request<ResumeUploadResult>('/candidate/resume', {
      method: 'POST',
      body: form,
      timeoutMs: LONG_RUNNING_TIMEOUT_MS,
    })
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
  // Long-running: makes a real outbound HTTP request to the job's own
  // application_url, whose latency this app has no control over.
  checkUrl: (id: number) =>
    request<URLCheckResultOut>(`/jobs/${id}/check-url`, {
      method: 'POST',
      timeoutMs: LONG_RUNNING_TIMEOUT_MS,
    }),
  whyThisJob: (id: number) => request<WhyBreakdownOut>(`/jobs/${id}/why`),
  compareJobs: (ids: number[]) =>
    request<JobDetailOut[]>(`/jobs/compare?ids=${ids.join(',')}`),
  // Long-running: full source scan / matching run / end-to-end search —
  // exactly the "intentionally long-running operations" this timeout
  // mechanism must never abort early.
  scanJobs: () =>
    request<ScanRunOut>('/jobs/scan', { method: 'POST', timeoutMs: LONG_RUNNING_TIMEOUT_MS }),
  matchJobs: () =>
    request<MatchRunOut>('/jobs/match', { method: 'POST', timeoutMs: LONG_RUNNING_TIMEOUT_MS }),
  runSearch: () =>
    request<SearchRunOut>('/jobs/search-run', {
      method: 'POST',
      timeoutMs: LONG_RUNNING_TIMEOUT_MS,
    }),
  listSearchRuns: () => request<SearchRunOut[]>('/jobs/search-runs'),
  sourceHealth: () => request<SourceHealthOut[]>('/sources/health'),
  schedulerStatus: () => request<SchedulerStatusOut>('/sources/scheduler-status'),
  top10: () => request<RankedJobOut[]>('/jobs/top10'),
  applyNowQueue: () => request<RankedJobOut[]>('/jobs/apply-now'),
  // Long-running: both call the LLM to generate real content.
  tailorResume: (jobId: number) =>
    request<TailoredResumeOut>(`/jobs/${jobId}/tailor-resume`, {
      method: 'POST',
      timeoutMs: LONG_RUNNING_TIMEOUT_MS,
    }),
  coverLetter: (jobId: number) =>
    request<CoverLetterOut>(`/jobs/${jobId}/cover-letter`, {
      method: 'POST',
      timeoutMs: LONG_RUNNING_TIMEOUT_MS,
    }),
  askAssistant: (jobId: number, questions: string[]) =>
    request<AssistantResponseOut>(`/jobs/${jobId}/assistant`, {
      method: 'POST',
      body: JSON.stringify({ questions }),
      timeoutMs: LONG_RUNNING_TIMEOUT_MS,
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
  // Long-running: generates a real conversational reply via the LLM.
  careerChat: (body: CareerChatIn) =>
    request<CareerChatOut>('/candidate/chat', {
      method: 'POST',
      body: JSON.stringify(body),
      timeoutMs: LONG_RUNNING_TIMEOUT_MS,
    }),

  listCompanies: () => request<CompanyOut[]>('/companies'),
  getCompany: (id: number) => request<CompanyOut>(`/companies/${id}`),

  listWatchlist: () => request<WatchlistEntryOut[]>('/watchlist'),
  watchlistSummary: () => request<WatchlistEntrySummaryOut[]>('/watchlist/summary'),
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
