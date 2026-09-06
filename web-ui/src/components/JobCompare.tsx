import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import { Button, Card, ErrorBanner, LoadingState } from './ui'
import type { JobDetailOut } from '../types'

const VIABILITY_STYLES: Record<string, string> = {
  VIABLE: 'text-emerald-600 dark:text-emerald-400',
  CAUTION: 'text-amber-600 dark:text-amber-400',
  BLOCKED: 'text-rose-600 dark:text-rose-400',
}

export function JobCompare({ jobIds, onClose }: { jobIds: number[]; onClose: () => void }) {
  const [jobs, setJobs] = useState<JobDetailOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .compareJobs(jobIds)
      .then(setJobs)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to compare jobs.'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobIds.join(',')])

  return (
    <Card className="overflow-x-auto p-6">
      <div className="mb-4 flex items-center justify-between gap-4">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
          Comparing {jobIds.length} jobs
        </h2>
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>

      {error && <ErrorBanner message={error} />}
      {!error && !jobs && <LoadingState />}

      {jobs && (
        <table className="w-full min-w-[720px] text-sm">
          <tbody>
            <Row label="Title" cells={jobs.map((j) => j.title)} strong />
            <Row label="Company" cells={jobs.map((j) => j.company_name)} />
            <Row label="Location" cells={jobs.map((j) => j.location ?? '—')} />
            <Row
              label="Match score"
              cells={jobs.map((j) => (j.match ? `${j.match.overall_score}/100` : '—'))}
            />
            <Row label="Decision" cells={jobs.map((j) => j.match?.decision ?? '—')} />
            <Row
              label="Salary"
              cells={jobs.map((j) =>
                j.salary_min || j.salary_max
                  ? `${j.currency ?? ''} ${j.salary_min ?? '?'} – ${j.salary_max ?? '?'}`.trim()
                  : 'Not listed'
              )}
            />
            <Row label="Posted" cells={jobs.map((j) => j.freshness_label)} />
            <Row label="Data confidence" cells={jobs.map((j) => j.data_confidence.level)} />
            <Row
              label="Application viability"
              cells={jobs.map((j) => j.viability.overall)}
              colorize={(v) => VIABILITY_STYLES[v] ?? ''}
            />
            <Row
              label="Missing requirements"
              cells={jobs.map((j) => j.match?.missing_requirements.join(', ') || 'None noted')}
            />
            <Row label="Visa info" cells={jobs.map((j) => (j.viability.visa_info_available ? 'Provided' : 'Not provided'))} />
          </tbody>
        </table>
      )}
    </Card>
  )
}

function Row({
  label,
  cells,
  strong,
  colorize,
}: {
  label: string
  cells: string[]
  strong?: boolean
  colorize?: (value: string) => string
}) {
  return (
    <tr className="border-b border-slate-100 last:border-0 dark:border-slate-800">
      <th className="w-40 shrink-0 py-2.5 pr-4 text-left text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </th>
      {cells.map((c, i) => (
        <td
          key={i}
          className={`py-2.5 pr-6 ${strong ? 'font-semibold text-slate-900 dark:text-slate-50' : 'text-slate-700 dark:text-slate-300'} ${colorize ? colorize(c) : ''}`}
        >
          {c}
        </td>
      ))}
    </tr>
  )
}
