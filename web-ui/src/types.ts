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
}

export interface PipelineUpdateIn {
  pipeline_stage?: PipelineStage
  notes?: string
  recruiter_contact?: string
  interview_date?: string
  follow_up_date?: string
  outcome?: string
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
