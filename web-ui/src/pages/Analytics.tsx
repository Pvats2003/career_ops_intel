import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import { Card, EmptyState, ErrorBanner, LoadingState, StatTile } from '../components/ui'
import type { AnalyticsOut } from '../types'

export default function Analytics() {
  const [data, setData] = useState<AnalyticsOut | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .analytics()
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load analytics.'))
  }, [])

  if (error) return <ErrorBanner message={error} />
  if (!data) return <LoadingState />

  const maxCount = Math.max(1, ...data.stage_breakdown.map((s) => s.count))

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">Analytics</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          How your search is actually performing.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatTile label="Applied" value={data.total_applied} />
        <StatTile label="Interviews" value={data.total_interviews} />
        <StatTile label="Offers" value={data.total_offers} />
        <StatTile label="Interview rate" value={`${data.interview_rate}%`} accent />
      </div>

      <Card className="p-6">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          Pipeline breakdown
        </h2>
        <div className="mt-4 flex flex-col gap-2">
          {data.stage_breakdown.map((row) => (
            <div key={row.stage} className="flex items-center gap-3">
              <div className="w-24 shrink-0 text-xs text-slate-500 dark:text-slate-400">
                {row.stage}
              </div>
              <div className="h-4 flex-1 rounded-full bg-slate-100 dark:bg-slate-800">
                <div
                  className="h-4 rounded-full bg-indigo-500"
                  style={{ width: `${(row.count / maxCount) * 100}%` }}
                />
              </div>
              <div className="w-6 shrink-0 text-right text-xs font-medium text-slate-700 dark:text-slate-300">
                {row.count}
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card className="p-6">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">By company</h2>
        {data.by_company.length === 0 ? (
          <div className="mt-3">
            <EmptyState
              title="No applications yet"
              description="Once you apply to jobs and move them through your pipeline, per-company stats will show up here."
            />
          </div>
        ) : (
          <table className="mt-3 w-full text-left text-sm">
            <thead>
              <tr className="text-xs text-slate-500 dark:text-slate-400">
                <th className="pb-2 font-medium">Company</th>
                <th className="pb-2 font-medium">Applications</th>
                <th className="pb-2 font-medium">Interviews</th>
                <th className="pb-2 font-medium">Offers</th>
                <th className="pb-2 font-medium">Interview rate</th>
              </tr>
            </thead>
            <tbody>
              {data.by_company.map((row) => (
                <tr key={row.label} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="py-2 text-slate-800 dark:text-slate-200">{row.label}</td>
                  <td className="py-2 text-slate-600 dark:text-slate-400">{row.applications}</td>
                  <td className="py-2 text-slate-600 dark:text-slate-400">{row.interviews}</td>
                  <td className="py-2 text-slate-600 dark:text-slate-400">{row.offers}</td>
                  <td className="py-2 font-medium text-indigo-600 dark:text-indigo-400">
                    {row.interview_rate}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}
