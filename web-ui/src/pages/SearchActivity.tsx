import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import { JobCard } from '../components/JobCard'
import { Button, Card, EmptyState, ErrorBanner, LoadingState } from '../components/ui'
import type { SchedulerStatusOut, SearchRunOut } from '../types'

const STATUS_STYLES: Record<string, string> = {
  COMPLETED: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
  PARTIAL: 'bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  RUNNING: 'bg-indigo-50 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300',
  FAILED: 'bg-rose-50 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300',
}

function formatRelative(iso: string | null): string {
  if (!iso) return 'unknown'
  const diffMs = new Date(iso).getTime() - Date.now()
  const diffHours = Math.round(diffMs / (1000 * 60 * 60))
  if (diffHours <= 0) return 'due now'
  if (diffHours < 24) return `in ${diffHours}h`
  return `in ${Math.round(diffHours / 24)}d`
}

export default function SearchActivity() {
  const [runs, setRuns] = useState<SearchRunOut[] | null>(null)
  const [scheduler, setScheduler] = useState<SchedulerStatusOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const load = () => {
    api
      .listSearchRuns()
      .then(setRuns)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load search runs.'))
    api.schedulerStatus().then(setScheduler).catch(() => setScheduler(null))
  }

  useEffect(load, [])

  if (error) return <ErrorBanner message={error} />
  if (!runs) return <LoadingState />

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">
          Search activity
        </h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Every discovery run Career OS has executed — what it searched, what it found, and what
          qualified.
        </p>
      </div>

      {scheduler && (
        <Card className="p-4 text-sm text-slate-600 dark:text-slate-400">
          Autonomous search runs every {scheduler.frequency_hours}h.{' '}
          {scheduler.last_run_completed_at
            ? `Last completed ${new Date(scheduler.last_run_completed_at).toLocaleString()}.`
            : 'No completed run yet.'}{' '}
          Next run {formatRelative(scheduler.next_run_due_at)}.
        </Card>
      )}

      {runs.length === 0 ? (
        <EmptyState
          title="No search runs yet"
          description="Run a search from the Dashboard to see activity here — sources searched, listings found, duplicates removed, and what qualified."
        />
      ) : (
        <div className="flex flex-col gap-3">
          {runs.map((run) => (
            <Card key={run.id} className="p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-slate-900 dark:text-slate-50">
                    {new Date(run.started_at).toLocaleString()}
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {run.sources.length === 0
                      ? 'No sources searched'
                      : run.sources.join(', ')}
                  </div>
                </div>
                <span
                  className={`rounded-full px-2.5 py-1 text-xs font-semibold ${STATUS_STYLES[run.status] ?? 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'}`}
                >
                  {run.status}
                </span>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
                <Stat label="Found" value={run.jobs_found} />
                <Stat label="Duplicates" value={run.duplicates_removed} />
                <Stat label="Invalid/expired" value={run.expired_removed} />
                <Stat label="Qualified" value={run.qualified} highlight />
                <Stat label="Errors" value={run.errors.length} danger={run.errors.length > 0} />
              </div>

              {run.errors.length > 0 && (
                <ul className="mt-3 list-inside list-disc text-xs text-rose-600 dark:text-rose-400">
                  {run.errors.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              )}

              {run.top_matches.length > 0 && (
                <div className="mt-4">
                  <Button
                    variant="ghost"
                    onClick={() => setExpandedId((prev) => (prev === run.id ? null : run.id))}
                  >
                    {expandedId === run.id
                      ? 'Hide top matches'
                      : `Show top matches (${run.top_matches.length})`}
                  </Button>
                  {expandedId === run.id && (
                    <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                      {run.top_matches.map((job) => (
                        <JobCard key={job.id} job={job} />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

function Stat({
  label,
  value,
  highlight,
  danger,
}: {
  label: string
  value: number
  highlight?: boolean
  danger?: boolean
}) {
  return (
    <div>
      <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
      <div
        className={`text-lg font-semibold ${
          danger
            ? 'text-rose-600 dark:text-rose-400'
            : highlight
              ? 'text-indigo-600 dark:text-indigo-400'
              : 'text-slate-900 dark:text-slate-50'
        }`}
      >
        {value}
      </div>
    </div>
  )
}
