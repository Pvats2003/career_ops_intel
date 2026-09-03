import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import { JobCard } from '../components/JobCard'
import { Button, EmptyState, ErrorBanner, LoadingState, StatTile } from '../components/ui'
import type { DashboardSummaryOut } from '../types'

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummaryOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'scan' | 'match' | null>(null)

  const load = () => {
    setError(null)
    api
      .dashboardSummary()
      .then(setSummary)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load dashboard.'))
  }

  useEffect(load, [])

  const runScan = async () => {
    setBusy('scan')
    setError(null)
    try {
      const result = await api.scanJobs()
      if (result.enabled_sources === 0) {
        setError(
          'No job source is enabled yet in config/sources.yaml — add a real Greenhouse/Lever board token and set enabled: true to start discovering jobs.',
        )
      }
      load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Scan failed.')
    } finally {
      setBusy(null)
    }
  }

  const runMatch = async () => {
    setBusy('match')
    setError(null)
    try {
      await api.matchJobs()
      load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Matching failed.')
    } finally {
      setBusy(null)
    }
  }

  if (!summary && !error) return <LoadingState label="Loading your dashboard…" />

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">
            Good to see you
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Here's what's worth your attention right now.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={runScan} disabled={busy !== null}>
            {busy === 'scan' ? 'Scanning…' : 'Scan for jobs'}
          </Button>
          <Button variant="primary" onClick={runMatch} disabled={busy !== null}>
            {busy === 'match' ? 'Matching…' : 'Re-run matching'}
          </Button>
        </div>
      </div>

      {error && <ErrorBanner message={error} />}

      {summary && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <StatTile label="Jobs discovered" value={summary.total_jobs_discovered} />
            <StatTile label="Job matches" value={summary.job_matches} />
            <StatTile label="Apply priority" value={summary.apply_priority_count} accent />
            <StatTile label="Shortlisted" value={summary.shortlisted} />
            <StatTile label="Applied" value={summary.applied} />
            <StatTile label="Interviewing" value={summary.interviewing} />
            <StatTile label="Offers" value={summary.offers} />
            <StatTile
              label="Resume status"
              value={summary.resume_validation_status ?? '—'}
            />
          </div>

          <section>
            <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-slate-50">
              🔥 Top opportunities
            </h2>
            {summary.top_opportunities.length === 0 ? (
              <EmptyState
                title="No scored jobs yet"
                description="Scan for jobs from your configured sources, then run matching to see your best opportunities ranked here."
                action={
                  <Button variant="primary" onClick={runScan} disabled={busy !== null}>
                    Scan for jobs
                  </Button>
                }
              />
            ) : (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {summary.top_opportunities.map((job) => (
                  <JobCard key={job.id} job={job} onSave={() => api.saveJob(job.id).then(load)} />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
