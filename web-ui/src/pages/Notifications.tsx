import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api'
import { Card, EmptyState, ErrorBanner, LoadingState } from '../components/ui'
import type { NotificationOut } from '../types'

const EVENT_LABELS: Record<string, string> = {
  HIGH_MATCH: '🎯 High match',
  DREAM_COMPANY: '⭐ Watchlist company',
  FRESH_JOB: '🆕 New posting',
}

export default function Notifications() {
  const [notifications, setNotifications] = useState<NotificationOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    api
      .listNotifications()
      .then(setNotifications)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load notifications.'))
  }

  useEffect(load, [])

  const markRead = async (id: number) => {
    await api.markNotificationRead(id)
    load()
  }

  if (error) return <ErrorBanner message={error} />
  if (!notifications) return <LoadingState />

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">
          Notifications
        </h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          High-match alerts, watchlist matches, and fresh postings — generated once per search
          run, never spammed.
        </p>
      </div>

      {notifications.length === 0 ? (
        <EmptyState
          title="No notifications yet"
          description="Run a full search to generate alerts for high-confidence matches and watchlist hits."
        />
      ) : (
        <div className="flex flex-col gap-2">
          {notifications.map((n) => (
            <Card
              key={n.id}
              className={`flex items-start justify-between gap-4 p-4 ${n.read_at ? 'opacity-60' : ''}`}
            >
              <div>
                <div className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  {EVENT_LABELS[n.event_type] ?? n.event_type}
                </div>
                <div className="mt-1 font-medium text-slate-900 dark:text-slate-50">
                  {n.related_job_id ? (
                    <Link
                      to={`/jobs/${n.related_job_id}`}
                      className="hover:text-indigo-600 dark:hover:text-indigo-400"
                    >
                      {n.title}
                    </Link>
                  ) : (
                    n.title
                  )}
                </div>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{n.message}</p>
              </div>
              {!n.read_at && (
                <button
                  onClick={() => markRead(n.id)}
                  className="whitespace-nowrap text-xs text-indigo-600 hover:underline dark:text-indigo-400"
                >
                  Mark read
                </button>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
