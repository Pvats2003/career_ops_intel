import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api'
import { JobCard } from '../components/JobCard'
import { Button, Card, EmptyState, ErrorBanner, LoadingState, StatTile } from '../components/ui'
import type {
  DashboardSummaryOut,
  FollowUpRecommendationOut,
  InsightsOut,
  MorningBriefingOut,
  NewSinceLastVisitOut,
  RankedJobOut,
} from '../types'

const TIER_ICON: Record<string, string> = { exceptional: '🔥', strong: '🟢', possible: '🟡' }

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummaryOut | null>(null)
  const [briefing, setBriefing] = useState<MorningBriefingOut | null>(null)
  const [applyNow, setApplyNow] = useState<RankedJobOut[]>([])
  const [newSinceVisit, setNewSinceVisit] = useState<NewSinceLastVisitOut | null>(null)
  const [top10, setTop10] = useState<RankedJobOut[]>([])
  const [followUps, setFollowUps] = useState<FollowUpRecommendationOut[]>([])
  const [insights, setInsights] = useState<InsightsOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'scan' | 'match' | 'search' | null>(null)
  const [expandedFollowUpId, setExpandedFollowUpId] = useState<number | null>(null)
  const [copiedFollowUpId, setCopiedFollowUpId] = useState<number | null>(null)

  const load = () => {
    setError(null)
    api
      .dashboardSummary()
      .then(setSummary)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load dashboard.'))
    api.morningBriefing().then(setBriefing).catch(() => setBriefing(null))
    api.applyNowQueue().then(setApplyNow).catch(() => setApplyNow([]))
    api.top10().then(setTop10).catch(() => setTop10([]))
    api.followUps().then(setFollowUps).catch(() => setFollowUps([]))
    api.insights().then(setInsights).catch(() => setInsights(null))
  }

  // Separate from `load()`: this call advances the server's "last visited"
  // marker, so it must fire exactly once per real page visit, never as
  // part of a refresh triggered by scan/match/search actions below.
  useEffect(() => {
    api.newSinceLastVisit().then(setNewSinceVisit).catch(() => setNewSinceVisit(null))
  }, [])

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
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">
          Good morning 👋
        </h1>
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

      {briefing && (
        <Card className="p-6">
          {briefing.total_opportunities === 0 ? (
            <p className="text-sm text-slate-600 dark:text-slate-400">
              Career OS hasn't found any opportunities worth your attention yet — run a search to
              get started.
            </p>
          ) : (
            <>
              <p className="text-sm text-slate-700 dark:text-slate-300">
                Career OS found{' '}
                <span className="font-semibold text-slate-900 dark:text-slate-50">
                  {briefing.total_opportunities}
                </span>{' '}
                opportunit{briefing.total_opportunities === 1 ? 'y' : 'ies'} worth your attention.
              </p>
              <div className="mt-2 flex flex-wrap gap-4 text-sm">
                <span>
                  {TIER_ICON.exceptional} {briefing.exceptional_count} exceptional match
                  {briefing.exceptional_count === 1 ? '' : 'es'}
                </span>
                <span>
                  {TIER_ICON.strong} {briefing.strong_count} strong match
                  {briefing.strong_count === 1 ? '' : 'es'}
                </span>
                <span>
                  {TIER_ICON.possible} {briefing.possible_count} possible match
                  {briefing.possible_count === 1 ? '' : 'es'}
                </span>
              </div>
            </>
          )}

          {briefing.top_highlights.length > 0 && (
            <div className="mt-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Your top {briefing.top_highlights.length}
              </div>
              <ol className="mt-2 flex flex-col gap-2">
                {briefing.top_highlights.map((h, i) => (
                  <li key={h.job_id} className="text-sm">
                    <Link
                      to={`/jobs/${h.job_id}`}
                      className="font-medium text-slate-900 hover:text-indigo-600 dark:text-slate-50 dark:hover:text-indigo-400"
                    >
                      {i + 1}. {h.rank_score.toFixed(0)}% — {h.title}
                    </Link>
                    <span className="text-slate-500 dark:text-slate-400">
                      {' '}
                      · {h.company}
                      {h.location ? ` · ${h.location}` : ''} · {h.freshness_label}
                    </span>
                    {h.why && (
                      <p className="text-slate-500 dark:text-slate-400">Why: {h.why}</p>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {briefing.follow_up_summaries.length > 0 && (
            <div className="mt-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Application follow-ups
              </div>
              <ul className="mt-1 list-inside list-disc text-sm text-slate-600 dark:text-slate-400">
                {briefing.follow_up_summaries.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
          )}

          {briefing.career_insight && (
            <div className="mt-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Career insight
              </div>
              <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
                {briefing.career_insight}
              </p>
            </div>
          )}

          {briefing.recommendation && (
            <div className="mt-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Recommendation
              </div>
              <p className="mt-1 text-sm font-medium text-indigo-700 dark:text-indigo-400">
                {briefing.recommendation}
              </p>
            </div>
          )}
        </Card>
      )}

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

          {newSinceVisit && newSinceVisit.previous_visit_at !== null && (
            <section>
              <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-slate-50">
                🆕 New since last visit
              </h2>
              {newSinceVisit.jobs.length === 0 ? (
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  Nothing new since your last visit.
                </p>
              ) : (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {newSinceVisit.jobs.map((r) => (
                    <JobCard key={r.job.id} job={r.job} onSave={() => api.saveJob(r.job.id).then(load)} />
                  ))}
                </div>
              )}
            </section>
          )}

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
                  <Card key={f.application_id} className="p-4">
                    <div className="flex items-center justify-between gap-4">
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
                      <div className="flex shrink-0 items-center gap-3">
                        <span className="whitespace-nowrap text-xs text-slate-400 dark:text-slate-500">
                          {f.applied_days_ago}d since last update
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedFollowUpId((prev) =>
                              prev === f.application_id ? null : f.application_id,
                            )
                          }
                          className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                        >
                          {expandedFollowUpId === f.application_id ? 'Hide message' : 'Draft message'}
                        </button>
                      </div>
                    </div>
                    {expandedFollowUpId === f.application_id && (
                      <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-800 dark:bg-slate-800/50">
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          A draft to review and send yourself — Career OS never contacts anyone
                          automatically.
                        </p>
                        <div className="mt-2 font-medium text-slate-800 dark:text-slate-200">
                          {f.message.subject}
                        </div>
                        <p className="mt-1 whitespace-pre-line text-slate-700 dark:text-slate-300">
                          {f.message.body}
                        </p>
                        <button
                          type="button"
                          onClick={async () => {
                            await navigator.clipboard.writeText(f.message.body)
                            setCopiedFollowUpId(f.application_id)
                          }}
                          className="mt-2 text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                        >
                          {copiedFollowUpId === f.application_id ? 'Copied ✓' : 'Copy message'}
                        </button>
                      </div>
                    )}
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
