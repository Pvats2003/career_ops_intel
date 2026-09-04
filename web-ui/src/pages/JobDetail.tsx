import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import {
  Button,
  Card,
  DecisionBadge,
  ErrorBanner,
  LoadingState,
  PipelineStageBadge,
  ScoreRing,
} from '../components/ui'
import type {
  AssistantAnswerOut,
  CoverLetterOut,
  JobDetailOut,
  TailoredResumeOut,
  URLCheckResultOut,
  WhyBreakdownOut,
} from '../types'

const MATCH_ROWS: { key: keyof NonNullable<JobDetailOut['match']>; label: string }[] = [
  { key: 'skills_match', label: 'Skills' },
  { key: 'experience_match', label: 'Experience' },
  { key: 'role_match', label: 'Role fit' },
  { key: 'project_match', label: 'Projects' },
  { key: 'education_match', label: 'Education' },
  { key: 'location_match', label: 'Location / remote' },
  { key: 'seniority_match', label: 'Seniority' },
  { key: 'eligibility_match', label: 'Eligibility' },
]

export default function JobDetail() {
  const { id } = useParams()
  const [job, setJob] = useState<JobDetailOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const load = () => {
    if (!id) return
    api
      .getJob(Number(id))
      .then(setJob)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load job.'))
  }

  useEffect(load, [id])

  if (error) return <ErrorBanner message={error} />
  if (!job) return <LoadingState />

  const save = async () => {
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await api.saveJob(job.id)
      setJob(updated)
    } catch (e) {
      setSaveError(e instanceof ApiError ? e.message : 'Failed to save this job.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Link to="/jobs" className="text-sm text-indigo-600 hover:underline dark:text-indigo-400">
        ← Back to jobs
      </Link>

      <Card className="p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">
              {job.title}
            </h1>
            <div className="mt-1 text-slate-600 dark:text-slate-400">
              {job.company_name}
              {job.location ? ` · ${job.location}` : ''}
              {job.remote_type ? ` · ${job.remote_type}` : ''}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {job.match && <DecisionBadge decision={job.match.decision} />}
              {job.pipeline_stage && <PipelineStageBadge stage={job.pipeline_stage} />}
              <span className="text-xs text-slate-500 dark:text-slate-400">
                {job.freshness_label}
              </span>
              <DataConfidenceBadge confidence={job.data_confidence} />
            </div>
          </div>
          {job.match && <ScoreRing score={job.match.overall_score} />}
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          {job.application_url ? (
            <a href={job.application_url} target="_blank" rel="noreferrer">
              <Button variant="primary">Open application page</Button>
            </a>
          ) : (
            <span className="text-sm text-slate-500 dark:text-slate-400">
              No direct application URL is available for this posting.
            </span>
          )}
          {!job.application_id ? (
            <div className="flex flex-col items-end gap-1.5">
              <Button variant="secondary" onClick={save} disabled={saving}>
                {saving ? 'Saving…' : 'Save to pipeline'}
              </Button>
              {saveError && (
                <span className="text-xs text-rose-600 dark:text-rose-400">{saveError}</span>
              )}
            </div>
          ) : (
            <Link to="/pipeline">
              <Button variant="secondary">View in pipeline</Button>
            </Link>
          )}
        </div>
      </Card>

      {job.match && (
        <Card className="p-6">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
            Why this matches you
          </h2>
          <p className="mt-2 text-sm text-slate-700 dark:text-slate-300">{job.match.reasoning}</p>

          <div className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
            {MATCH_ROWS.map((row) => (
              <div key={row.key}>
                <div className="text-xs text-slate-500 dark:text-slate-400">{row.label}</div>
                <div className="text-lg font-semibold text-slate-900 dark:text-slate-50">
                  {job.match![row.key] as number}
                </div>
              </div>
            ))}
          </div>

          {job.match.missing_requirements.length > 0 && (
            <div className="mt-5">
              <div className="text-sm font-medium text-slate-700 dark:text-slate-300">
                Gaps to address
              </div>
              <ul className="mt-1 list-inside list-disc text-sm text-slate-600 dark:text-slate-400">
                {job.match.missing_requirements.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </div>
          )}
          {job.match.concerns.length > 0 && (
            <div className="mt-4">
              <div className="text-sm font-medium text-slate-700 dark:text-slate-300">
                Potential concerns
              </div>
              <ul className="mt-1 list-inside list-disc text-sm text-slate-600 dark:text-slate-400">
                {job.match.concerns.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      )}

      {job.match && <WhyBreakdownPanel jobId={job.id} />}

      <ViabilityPanel job={job} />

      <TailorResumePanel jobId={job.id} />
      <CoverLetterPanel jobId={job.id} />
      <AssistantPanel jobId={job.id} />

      {(job.description || job.requirements) && (
        <Card className="p-6">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
            Job description
          </h2>
          {job.description && (
            <p className="mt-2 whitespace-pre-line text-sm text-slate-700 dark:text-slate-300">
              {job.description}
            </p>
          )}
          {job.requirements && (
            <>
              <h3 className="mt-4 text-sm font-semibold text-slate-800 dark:text-slate-200">
                Requirements
              </h3>
              <p className="mt-1 whitespace-pre-line text-sm text-slate-700 dark:text-slate-300">
                {job.requirements}
              </p>
            </>
          )}
        </Card>
      )}
    </div>
  )
}

function WhyBreakdownPanel({ jobId }: { jobId: number }) {
  const [breakdown, setBreakdown] = useState<WhyBreakdownOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      setBreakdown(await api.whyThisJob(jobId))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not load the ranking breakdown.')
    } finally {
      setLoading(false)
    }
  }

  if (!breakdown) {
    return (
      <Card className="p-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
              Why is this ranked this way?
            </h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              A numbered breakdown of exactly what produced this job's rank score.
            </p>
          </div>
          <Button variant="ghost" onClick={load} disabled={loading}>
            {loading ? 'Loading…' : 'Show breakdown'}
          </Button>
        </div>
        {error && <p className="mt-2 text-sm text-rose-600 dark:text-rose-400">{error}</p>}
      </Card>
    )
  }

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
          Why is this ranked this way?
        </h2>
        <span className="text-xl font-bold text-indigo-600 dark:text-indigo-400">
          {breakdown.rank_score}
        </span>
      </div>
      <ol className="mt-3 list-inside list-decimal space-y-1 text-sm text-slate-700 dark:text-slate-300">
        {breakdown.reasons.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ol>
      {breakdown.main_weakness && (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
          Main weakness: {breakdown.main_weakness}
        </p>
      )}
    </Card>
  )
}

function DataConfidenceBadge({ confidence }: { confidence: JobDetailOut['data_confidence'] }) {
  const isHigh = confidence.level === 'High'
  return (
    <span
      title={confidence.reasons.join('; ') || 'All key fields verified from the source.'}
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
        isHigh
          ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
          : 'bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
      }`}
    >
      Data confidence: {confidence.level}
    </span>
  )
}

const VIABILITY_STYLES: Record<string, string> = {
  VIABLE: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
  CAUTION: 'bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  BLOCKED: 'bg-rose-50 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300',
}

function ViabilityCheck({ label, ok }: { label: string; ok: boolean | null }) {
  const icon = ok === null ? '—' : ok ? '✓' : '✗'
  const color =
    ok === null
      ? 'text-slate-400 dark:text-slate-500'
      : ok
        ? 'text-emerald-600 dark:text-emerald-400'
        : 'text-rose-600 dark:text-rose-400'
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={`w-4 font-semibold ${color}`}>{icon}</span>
      <span className="text-slate-700 dark:text-slate-300">{label}</span>
    </div>
  )
}

function ViabilityPanel({ job }: { job: JobDetailOut }) {
  const v = job.viability
  const [checking, setChecking] = useState(false)
  const [urlResult, setUrlResult] = useState<URLCheckResultOut | null>(null)
  const [error, setError] = useState<string | null>(null)

  const checkUrl = async () => {
    setChecking(true)
    setError(null)
    try {
      setUrlResult(await api.checkUrl(job.id))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not check the URL.')
    } finally {
      setChecking(false)
    }
  }

  return (
    <Card className="p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
          Application viability
        </h2>
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-semibold ${VIABILITY_STYLES[v.overall]}`}
        >
          {v.overall}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-y-2 sm:grid-cols-2">
        <ViabilityCheck label="Application URL exists" ok={v.url_exists} />
        <ViabilityCheck label="Direct application available" ok={v.direct_application} />
        <ViabilityCheck label="Job still active" ok={v.job_active} />
        <ViabilityCheck
          label="Required qualifications"
          ok={v.qualifications_status === 'UNKNOWN' ? null : v.qualifications_status === 'MEETS'}
        />
        <ViabilityCheck label="Location compatible" ok={v.location_compatible} />
        <ViabilityCheck label="Visa information provided" ok={v.visa_info_available} />
      </div>

      {v.reasons.length > 0 && (
        <ul className="mt-4 list-inside list-disc text-sm text-slate-500 dark:text-slate-400">
          {v.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}

      {job.application_url && (
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
          <Button variant="ghost" onClick={checkUrl} disabled={checking}>
            {checking ? 'Checking…' : 'Check application URL is live'}
          </Button>
          {urlResult && (
            <span
              className={`text-sm ${
                urlResult.status === 'REACHABLE'
                  ? 'text-emerald-600 dark:text-emerald-400'
                  : urlResult.status === 'UNREACHABLE'
                    ? 'text-rose-600 dark:text-rose-400'
                    : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              {urlResult.status === 'REACHABLE'
                ? 'Reachable'
                : urlResult.status === 'UNREACHABLE'
                  ? 'Not reachable'
                  : 'Could not verify (no result either way)'}{' '}
              — {urlResult.detail}
            </span>
          )}
          {error && <span className="text-sm text-rose-600 dark:text-rose-400">{error}</span>}
        </div>
      )}
    </Card>
  )
}

function GeneratedByNote({ generatedBy }: { generatedBy: 'llm' | 'deterministic' }) {
  return (
    <p className="mt-3 text-xs text-slate-400 dark:text-slate-500">
      {generatedBy === 'llm'
        ? 'Refined with AI, validated against your profile.'
        : 'Generated deterministically from your profile (no AI configured, or the AI draft was rejected).'}
    </p>
  )
}

function TailorResumePanel({ jobId }: { jobId: number }) {
  const [result, setResult] = useState<TailoredResumeOut | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const generate = async () => {
    setLoading(true)
    setError(null)
    try {
      setResult(await api.tailorResume(jobId))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to tailor resume.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
          Tailor resume for this job
        </h2>
        <Button variant="secondary" onClick={generate} disabled={loading}>
          {loading ? 'Generating…' : result ? 'Regenerate' : 'Generate'}
        </Button>
      </div>
      {error && <p className="mt-2 text-sm text-rose-600 dark:text-rose-400">{error}</p>}
      {result && (
        <div className="mt-4 space-y-4">
          <div>
            <div className="text-sm font-medium text-slate-700 dark:text-slate-300">
              Professional summary
            </div>
            <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
              {result.professional_summary}
            </p>
          </div>
          {result.relevant_skills.length > 0 && (
            <div>
              <div className="text-sm font-medium text-slate-700 dark:text-slate-300">
                Relevant skills to feature
              </div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {result.relevant_skills.map((s) => (
                  <span
                    key={s}
                    className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-300"
                  >
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
          {result.ats_keywords.length > 0 && (
            <div>
              <div className="text-sm font-medium text-slate-700 dark:text-slate-300">
                ATS keywords already in your profile — make sure they appear on your resume
              </div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {result.ats_keywords.map((k) => (
                  <span
                    key={k}
                    className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300"
                  >
                    {k}
                  </span>
                ))}
              </div>
            </div>
          )}
          {result.notes.length > 0 && (
            <ul className="list-inside list-disc text-sm text-slate-500 dark:text-slate-400">
              {result.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
          <GeneratedByNote generatedBy={result.generated_by} />
        </div>
      )}
    </Card>
  )
}

function CoverLetterPanel({ jobId }: { jobId: number }) {
  const [result, setResult] = useState<CoverLetterOut | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const generate = async () => {
    setLoading(true)
    setError(null)
    setCopied(false)
    try {
      setResult(await api.coverLetter(jobId))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to generate cover letter.')
    } finally {
      setLoading(false)
    }
  }

  const copy = async () => {
    if (!result) return
    await navigator.clipboard.writeText(result.body)
    setCopied(true)
  }

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">Cover letter</h2>
        <div className="flex gap-2">
          {result && (
            <Button variant="ghost" onClick={copy}>
              {copied ? 'Copied ✓' : 'Copy'}
            </Button>
          )}
          <Button variant="secondary" onClick={generate} disabled={loading}>
            {loading ? 'Generating…' : result ? 'Regenerate' : 'Generate'}
          </Button>
        </div>
      </div>
      {error && <p className="mt-2 text-sm text-rose-600 dark:text-rose-400">{error}</p>}
      {result && (
        <div className="mt-4">
          <p className="whitespace-pre-line text-sm text-slate-700 dark:text-slate-300">
            {result.body}
          </p>
          {result.notes.length > 0 && (
            <ul className="mt-3 list-inside list-disc text-sm text-slate-500 dark:text-slate-400">
              {result.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
          <GeneratedByNote generatedBy={result.generated_by} />
        </div>
      )}
    </Card>
  )
}

function AssistantPanel({ jobId }: { jobId: number }) {
  const [question, setQuestion] = useState('')
  const [answers, setAnswers] = useState<AssistantAnswerOut[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const ask = async () => {
    if (!question.trim()) return
    setLoading(true)
    setError(null)
    try {
      const response = await api.askAssistant(jobId, [question.trim()])
      setAnswers((prev) => [...response.answers, ...prev])
      setQuestion('')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to get an answer.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card className="p-6">
      <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
        Application assistant
      </h2>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        Ask a common application question — answered from your profile, never invented.
      </p>
      <div className="mt-3 flex gap-2">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && ask()}
          placeholder="e.g. What is your expected salary?"
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
        <Button variant="secondary" onClick={ask} disabled={loading || !question.trim()}>
          {loading ? 'Asking…' : 'Ask'}
        </Button>
      </div>
      {error && <p className="mt-2 text-sm text-rose-600 dark:text-rose-400">{error}</p>}
      {answers.length > 0 && (
        <div className="mt-4 space-y-3">
          {answers.map((a, i) => (
            <div
              key={`${a.question}-${i}`}
              className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"
            >
              <div className="text-sm font-medium text-slate-700 dark:text-slate-300">
                {a.question}
              </div>
              {a.requires_human ? (
                <p className="mt-1 text-sm text-amber-600 dark:text-amber-400">
                  Needs your input — Career OS can't answer this from your profile ({a.source}).
                </p>
              ) : (
                <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">{a.answer}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}
