import { Link } from 'react-router-dom'
import type { JobOut } from '../types'
import { Button, Card, DecisionBadge, PipelineStageBadge, ScoreRing } from './ui'

function formatSalary(job: JobOut): string | null {
  if (!job.salary_min && !job.salary_max) return null
  const currency = job.currency ?? ''
  const fmt = (n: number) => `${currency} ${Math.round(n / 1000)}k`.trim()
  if (job.salary_min && job.salary_max) return `${fmt(job.salary_min)} – ${fmt(job.salary_max)}`
  return fmt((job.salary_min ?? job.salary_max)!)
}

export function JobCard({
  job,
  onSave,
  saving,
}: {
  job: JobOut
  onSave?: (id: number) => void
  saving?: boolean
}) {
  const salary = formatSalary(job)
  return (
    <Card className="flex flex-col gap-3 p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <Link
            to={`/jobs/${job.id}`}
            className="block truncate text-base font-semibold text-slate-900 hover:text-indigo-600 dark:text-slate-50 dark:hover:text-indigo-400"
          >
            {job.title}
          </Link>
          <div className="mt-0.5 truncate text-sm text-slate-600 dark:text-slate-400">
            {job.company_name}
            {job.location ? ` · ${job.location}` : ''}
            {job.remote_type ? ` · ${job.remote_type}` : ''}
          </div>
        </div>
        {job.match && <ScoreRing score={job.match.overall_score} />}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {job.match && <DecisionBadge decision={job.match.decision} />}
        {job.pipeline_stage && <PipelineStageBadge stage={job.pipeline_stage} />}
        <span className="text-xs text-slate-500 dark:text-slate-400">{job.freshness_label}</span>
        {salary && (
          <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{salary}</span>
        )}
      </div>

      {job.match && job.match.reasoning && (
        <p className="line-clamp-2 text-sm text-slate-600 dark:text-slate-400">
          {job.match.reasoning}
        </p>
      )}

      <div className="mt-1 flex items-center gap-2">
        <Link to={`/jobs/${job.id}`}>
          <Button variant="secondary">View</Button>
        </Link>
        {job.application_url && (
          <a href={job.application_url} target="_blank" rel="noreferrer">
            <Button variant="primary">Apply</Button>
          </a>
        )}
        {onSave && !job.application_id && (
          <Button variant="ghost" onClick={() => onSave(job.id)} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        )}
      </div>
    </Card>
  )
}
