import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import { Card, EmptyState, ErrorBanner, LoadingState } from '../components/ui'
import type { SourceHealthOut } from '../types'

const STATUS_ICON: Record<string, string> = {
  HEALTHY: '🟢',
  UNHEALTHY: '🟡',
  UNKNOWN: '⚪',
}

function formatTime(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : 'never'
}

export default function SourceHealth() {
  const [sources, setSources] = useState<SourceHealthOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .sourceHealth()
      .then(setSources)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load source health.'))
  }, [])

  if (error) return <ErrorBanner message={error} />
  if (!sources) return <LoadingState />

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">
          Source health
        </h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Whether each job source is actually reachable — derived from the last real scan, never a
          separate probe.
        </p>
      </div>

      {sources.length === 0 ? (
        <EmptyState
          title="No sources configured"
          description="Enable a job source in config/sources.yaml to see its health here."
        />
      ) : (
        <div className="flex flex-col gap-3">
          {sources.map((s) => (
            <Card key={s.name} className="p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-slate-900 dark:text-slate-50">
                    {STATUS_ICON[s.status]} {s.name}
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {s.kind} · {s.enabled ? 'enabled' : 'disabled'}
                  </div>
                </div>
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  Last checked: {formatTime(s.last_checked_at)}
                </span>
              </div>

              <div className="mt-3 text-sm text-slate-700 dark:text-slate-300">
                {s.status === 'UNKNOWN' && "Hasn't been checked yet — run a search to find out."}
                {s.status === 'HEALTHY' && `Last successful run: ${formatTime(s.last_success_at)}`}
                {s.status === 'UNHEALTHY' && (
                  <>
                    <span className="text-rose-600 dark:text-rose-400">
                      Last error: {s.last_error}
                    </span>
                    {s.last_success_at && (
                      <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        Last worked: {formatTime(s.last_success_at)}
                      </div>
                    )}
                  </>
                )}
              </div>

              {s.suggested_action && (
                <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
                  Suggested: {s.suggested_action}
                </p>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
