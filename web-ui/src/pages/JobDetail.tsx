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
import type { JobDetailOut } from '../types'

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
    try {
      const updated = await api.saveJob(job.id)
      setJob(updated)
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
            <Button variant="secondary" onClick={save} disabled={saving}>
              {saving ? 'Saving…' : 'Save to pipeline'}
            </Button>
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
