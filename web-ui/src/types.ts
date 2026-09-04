// Mirrors src/job_agent/web/schemas.py — keep in sync by hand; there is no
// codegen step in this V1 (BUILD PROMPT section 31, no overengineering).

export interface MatchOut {
  overall_score: number
  decision: 'APPLY' | 'REVIEW' | 'SAVE' | 'SKIP' | 'HUMAN_REQUIRED'
  skills_match: number
  experience_match: number
  role_match: number
  project_match: number
  education_match: number
  location_match: number
  seniority_match: number
  eligibility_match: number
  missing_requirements: string[]
  concerns: string[]
  hard_stop_reasons: string[]
  excluded_reasons: string[]
  reasoning: string
  semantic_available: boolean
}

export interface DataConfidenceOut {
  level: 'High' | 'Medium'
  reasons: string[]
}

export interface ApplicationViabilityOut {
  url_exists: boolean
  direct_application: boolean
  job_active: boolean
  qualifications_status: 'MEETS' | 'GAPS' | 'UNKNOWN'
  location_compatible: boolean | null
  visa_info_available: boolean
  overall: 'VIABLE' | 'CAUTION' | 'BLOCKED'
  reasons: string[]
}

export interface URLCheckResultOut {
  status: 'REACHABLE' | 'UNREACHABLE' | 'UNKNOWN'
  detail: string
  checked_at: string
}

export interface JobOut {
  id: number
  title: string
  company_name: string
  location: string | null
  remote_type: string | null
  employment_type: string | null
  salary_min: number | null
  salary_max: number | null
  currency: string | null
  application_url: string | null
  posted_at: string | null
  discovered_at: string
  freshness_status: string
  freshness_label: string
  source_name: string | null
  match: MatchOut | null
  pipeline_stage: string | null
  application_id: number | null
  lifecycle_status: string
  also_seen_on: string[]
  duplicate_count: number
  data_confidence: DataConfidenceOut
  viability: ApplicationViabilityOut
}

export interface JobDetailOut extends JobOut {
  description: string | null
  requirements: string | null
  preferred_qualifications: string | null
  visa_information: string | null
  company_url: string | null
}

export interface JobListOut {
  total: number
  items: JobOut[]
}

export interface ScanSourceResultOut {
  source_name: string
  identifier: string
  fetched: number
  created: number
  updated: number
  errors: string[]
}

export interface ScanRunOut {
  results: ScanSourceResultOut[]
  enabled_sources: number
}

export interface MatchRunOut {
  matched: number
  apply_count: number
  review_count: number
  save_count: number
  skip_count: number
  human_required_count: number
}

export const PIPELINE_STAGES = [
  'SAVED',
  'SHORTLISTED',
  'APPLY',
  'APPLIED',
  'ASSESSMENT',
  'INTERVIEW',
  'OFFER',
  'REJECTED',
] as const
export type PipelineStage = (typeof PIPELINE_STAGES)[number]

export interface ApplicationScorecardOut {
  candidate_fit: number
  job_quality: number
  career_value: number
  application_viability: number
  overall_score: number
  overall_recommendation: string
}

export interface ApplicationChecklistOut {
  resume_selected: boolean
  resume_tailored: boolean
  cover_letter_ready: boolean
  questions_prepared: boolean
  submitted: boolean
  confirmation_received: boolean
}

export interface ApplicationHistoryEventOut {
  event_type: string
  details: Record<string, unknown>
  created_at: string
}

export interface PipelineItemOut {
  application_id: number
  job: JobOut
  pipeline_stage: PipelineStage
  status: string
  notes: string | null
  recruiter_contact: string | null
  interview_date: string | null
  follow_up_date: string | null
  outcome: string | null
  created_at: string
  updated_at: string
  scorecard: ApplicationScorecardOut
  checklist: ApplicationChecklistOut
}

export interface PipelineUpdateIn {
  pipeline_stage?: PipelineStage
  notes?: string
  recruiter_contact?: string
  interview_date?: string
  follow_up_date?: string
  outcome?: string
  cover_letter_ready?: boolean
  questions_prepared?: boolean
}

export interface CandidateProfileOut {
  candidate_id: number
  name: string
  email: string
  phone: string
  linkedin: string
  current_location: string
  years_experience: number
  target_roles_primary: string[]
  target_roles_secondary: string[]
  skills: string[]
  technical_skills: string[]
  experience: Record<string, unknown>[]
  education: Record<string, unknown>[]
  projects: Record<string, unknown>[]
  achievements: Record<string, unknown>[]
  certifications: Record<string, unknown>[]
  source_files: string[]
  parsed_at: string
}

export interface ResumeUploadResult {
  saved_path: string
  profile_version_id: number | null
  validation_status: string
  issues: string[]
}

export interface DashboardSummaryOut {
  resume_parsed: boolean
  resume_validation_status: string | null
  job_matches: number
  shortlisted: number
  applied: number
  interviewing: number
  offers: number
  total_jobs_discovered: number
  apply_priority_count: number
  top_opportunities: JobOut[]
}

export interface StageBreakdownOut {
  stage: string
  count: number
}

export interface CareerPathAnalyticsOut {
  label: string
  applications: number
  interviews: number
  offers: number
  interview_rate: number
}

export interface AnalyticsOut {
  stage_breakdown: StageBreakdownOut[]
  total_jobs_discovered: number
  total_matched: number
  total_shortlisted: number
  total_applied: number
  total_interviews: number
  total_offers: number
  total_rejections: number
  application_rate: number
  interview_rate: number
  offer_rate: number
  by_company: CareerPathAnalyticsOut[]
}

// --------------------------------------------------------------------------
// Resume tailoring / cover letter / application assistant (Phase 9)
// --------------------------------------------------------------------------

export interface TailoredResumeOut {
  job_id: number
  professional_summary: string
  relevant_skills: string[]
  emphasized_experience: Record<string, unknown>[]
  relevant_projects: Record<string, unknown>[]
  ats_keywords: string[]
  notes: string[]
  generated_by: 'llm' | 'deterministic'
}

export interface CoverLetterOut {
  job_id: number
  body: string
  notes: string[]
  generated_by: 'llm' | 'deterministic'
}

export interface AssistantAnswerOut {
  question: string
  category: string
  answer: string | null
  confidence: number
  source: string
  requires_human: boolean
  validation_notes: string[]
}

export interface AssistantResponseOut {
  job_id: number
  answers: AssistantAnswerOut[]
}

// --------------------------------------------------------------------------
// Career paths (Phase 8 section 5)
// --------------------------------------------------------------------------

export interface CareerPathOut {
  label: string
  fit_score: number
  evidence: string[]
  relevant_skills: string[]
  relevant_experience: string[]
  missing_skills: string[]
  typical_titles: string[]
  career_upside: string
  recommended_priority: string
}

export interface CareerProfileOut {
  primary_direction: string | null
  strengths: string[]
  growing_area: string | null
  skill_gaps: string[]
  best_locations: string[]
}

export interface CareerPathComparisonRowOut {
  label: string
  current_fit: number
  job_volume: number
  career_upside: string
  skill_gap: string
  interview_rate: number | null
  interview_sample_size: number
  overall: number
}

export interface SkillGapEntryOut {
  skill: string
  frequency_count: number
  frequency_pct: number
  unlocks_count: number
  relevant_career_paths: string[]
}

// --------------------------------------------------------------------------
// Search runs / ranking (Phase 8)
// --------------------------------------------------------------------------

export interface SearchRunOut {
  id: number
  started_at: string
  completed_at: string | null
  sources: string[]
  queries: string[]
  jobs_found: number
  duplicates_removed: number
  expired_removed: number
  qualified: number
  errors: string[]
  status: string
  top_matches: JobOut[]
}

export interface SourceHealthOut {
  name: string
  kind: string
  enabled: boolean
  status: 'HEALTHY' | 'UNHEALTHY' | 'UNKNOWN'
  last_error: string | null
  suggested_action: string | null
  last_success_at: string | null
  last_checked_at: string | null
}

export interface SchedulerStatusOut {
  frequency_hours: number
  last_run_completed_at: string | null
  next_run_due_at: string | null
}

export interface RankedJobOut {
  job: JobOut
  rank_score: number
  why: string[]
  gaps: string[]
  recommendation: string
}

export interface NewSinceLastVisitOut {
  previous_visit_at: string | null
  jobs: RankedJobOut[]
}

export interface BriefingHighlightOut {
  job_id: number
  title: string
  company: string
  location: string | null
  rank_score: number
  freshness_label: string
  why: string | null
}

export interface MorningBriefingOut {
  total_opportunities: number
  exceptional_count: number
  strong_count: number
  possible_count: number
  top_highlights: BriefingHighlightOut[]
  follow_up_summaries: string[]
  career_insight: string | null
  recommendation: string | null
}

// --------------------------------------------------------------------------
// Company intelligence (Phase 10)
// --------------------------------------------------------------------------

export interface CompanyOut {
  id: number
  name: string
  industry: string | null
  size: string | null
  website: string | null
  career_page_url: string | null
  notes: string | null
  open_roles: number
  matching_jobs: JobOut[]
  best_role: JobOut | null
  company_fit: number | null
  company_fit_reasons: string[]
}

// --------------------------------------------------------------------------
// Watchlist (Phase 11 section 19)
// --------------------------------------------------------------------------

export const WATCHLIST_KINDS = ['COMPANY', 'ROLE', 'LOCATION'] as const
export type WatchlistKind = (typeof WATCHLIST_KINDS)[number]

export interface WatchlistEntryOut {
  id: number
  kind: WatchlistKind
  value: string
  created_at: string
}

export interface WatchlistEntryIn {
  kind: WatchlistKind
  value: string
}

export interface WatchlistEntrySummaryOut {
  entry: WatchlistEntryOut
  matching_count: number
  new_matching_count: number
  highest_match_score: number | null
  latest_posted_at: string | null
}

// --------------------------------------------------------------------------
// Notifications (Phase 11 section 20)
// --------------------------------------------------------------------------

export interface NotificationOut {
  id: number
  event_type: string
  title: string
  message: string
  related_job_id: number | null
  related_application_id: number | null
  read_at: string | null
  created_at: string
}

// --------------------------------------------------------------------------
// Search preferences / settings (Phase 15)
// --------------------------------------------------------------------------

export interface SearchPreferencesOut {
  target_roles: string[]
  target_countries: string[]
  target_cities: string[]
  remote_preference: string | null
  min_salary: number | null
  max_experience_gap_years: number | null
  industries: string[]
  companies_priority: string[]
  companies_excluded: string[]
  min_match_score: number
  search_frequency_hours: number
  notification_min_score: number
  notification_frequency: string
}

export type SearchPreferencesIn = Partial<SearchPreferencesOut>

// --------------------------------------------------------------------------
// Follow-up intelligence (Phase 13)
// --------------------------------------------------------------------------

export interface FollowUpMessageOut {
  subject: string
  body: string
}

export interface FollowUpRecommendationOut {
  application_id: number
  job: JobOut
  applied_days_ago: number
  suggested_action: string
  message: FollowUpMessageOut
}

// --------------------------------------------------------------------------
// Learning / insights (Phase 12)
// --------------------------------------------------------------------------

export interface CategoryInsightOut {
  category: string
  saved: number
  ignored: number
  applied: number
  save_rate: number
  explanation: string
}

export interface InsightsOut {
  categories: CategoryInsightOut[]
  summary: string[]
}
