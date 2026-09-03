import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api'
import { JobCard } from '../components/JobCard'
import { Button, Card, EmptyState, ErrorBanner, LoadingState, StatTile } from '../components/ui'
import type {
  DashboardSummaryOut,
  FollowUpRecommendationOut,
  InsightsOut,
  RankedJobOut,
} from '../types'

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummaryOut | null>(null)
  const [applyNow, setApplyNow] = useState<RankedJobOut[]>([])
  const [top10, setTop10] = useState<RankedJobOut[]>([])
  const [followUps, setFollowUps] = useState<FollowUpRecommendationOut[]>([])
  const [insights, setInsights] = useState<InsightsOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'scan' | 'match' | 'search' | null>(null)

  const load = () => {
    setError(null)
    api
      .dashboardSummary()
      .then(setSummary)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load dashboard.'))
    api.applyNowQueue().then(setApplyNow).catch(() => setApplyNow([]))
    api.top10().then(setTop10).catch(() => setTop10([]))
    api.followUps().then(setFollowUps).catch(() => setFollowUps([]))
    api.insights().then(setInsights).catch(() => setInsights(null))
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

  const runSearch = async () => {
    setBusy('search')
    setError(null)
    try {
      await api.runSearch()
      load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Search run failed.')
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
            Good morning
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {summary
              ? `${summary.apply_priority_count} job${summary.apply_priority_count === 1 ? '' : 's'} worth applying to today, out of ${summary.job_matches} matched.`
              : "Here's what's worth your attention right now."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={runScan} disabled={busy !== null}>
            {busy === 'scan' ? 'Scanning…' : 'Scan for jobs'}
          </Button>
          <Button variant="secondary" onClick={runMatch} disabled={busy !== null}>
            {busy === 'match' ? 'Matching…' : 'Re-run matching'}
          </Button>
          <Button variant="primary" onClick={runSearch} disabled={busy !== null}>
            {busy === 'search' ? 'Running full search…' : 'Run full search'}
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
            <StatTile label="Resume status" value={summary.resume_validation_status ?? '—'} />
          </div>

          <section>
            <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-slate-50">
              🚀 Apply now
            </h2>
            {applyNow.length === 0 ? (
              <EmptyState
                title="Nothing at APPLY confidence yet"
                description="High-confidence matches ready to apply to today will show up here once a search/match run finds them."
              />
            ) : (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {applyNow.map((r) => (
                  <div key={r.job.id} className="flex flex-col gap-1.5">
                    <JobCard job={r.job} onSave={() => api.saveJob(r.job.id).then(load)} />
                    <p className="px-1 text-xs text-slate-500 dark:text-slate-400">
                      {r.recommendation}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section>
            <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-slate-50">
              🔥 Today's top 10
            </h2>
            {top10.length === 0 ? (
              <EmptyState
                title="No ranked jobs yet"
                description="Scan for jobs from your configured sources, then run matching to see your best opportunities ranked here."
                action={
                  <Button variant="primary" onClick={runScan} disabled={busy !== null}>
                    Scan for jobs
                  </Button>
                }
              />
            ) : (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {top10.map((r) => (
                  <JobCard key={r.job.id} job={r.job} onSave={() => api.saveJob(r.job.id).then(load)} />
                ))}
              </div>
            )}
          </section>

          {followUps.length > 0 && (
            <section>
              <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-slate-50">
                ⏰ Follow-ups recommended
              </h2>
              <div className="flex flex-col gap-2">
                {followUps.map((f) => (
                  <Card key={f.application_id} className="flex items-center justify-between p-4">
                    <div>
                      <Link
                        to={`/jobs/${f.job.id}`}
                        className="font-medium text-slate-900 hover:text-indigo-600 dark:text-slate-50 dark:hover:text-indigo-400"
                      >
                        {f.job.title} at {f.job.company_name}
                      </Link>
                      <p className="text-sm text-slate-500 dark:text-slate-400">
                        {f.suggested_action}
                      </p>
                    </div>
                    <span className="whitespace-nowrap text-xs text-slate-400 dark:text-slate-500">
                      {f.applied_days_ago}d since last update
                    </span>
                  </Card>
                ))}
              </div>
            </section>
          )}

          {insights && insights.summary.length > 0 && (
            <section>
              <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-slate-50">
                💡 Career insights
              </h2>
              <Card className="p-4">
                <ul className="list-inside list-disc space-y-1 text-sm text-slate-700 dark:text-slate-300">
                  {insights.summary.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              </Card>
            </section>
          )}
        </>
      )}
    </div>
  )
}
