import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import { Button, Card, ErrorBanner, LoadingState } from '../components/ui'
import { WATCHLIST_KINDS } from '../types'
import type {
  SearchPreferencesOut,
  WatchlistEntryOut,
  WatchlistEntrySummaryOut,
  WatchlistKind,
} from '../types'

function csvToList(value: string): string[] {
  return value
    .split(',')
    .map((v) => v.trim())
    .filter(Boolean)
}

export default function Settings() {
  const [prefs, setPrefs] = useState<SearchPreferencesOut | null>(null)
  const [countries, setCountries] = useState<string[]>([])
  const [watchlist, setWatchlist] = useState<WatchlistEntryOut[]>([])
  const [watchlistSummary, setWatchlistSummary] = useState<WatchlistEntrySummaryOut[]>([])
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const [newWatchKind, setNewWatchKind] = useState<WatchlistKind>('COMPANY')
  const [newWatchValue, setNewWatchValue] = useState('')

  const load = () => {
    api
      .getSearchPreferences()
      .then(setPrefs)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load settings.'))
    api.supportedCountries().then(setCountries).catch(() => setCountries([]))
    api.listWatchlist().then(setWatchlist).catch(() => setWatchlist([]))
    api.watchlistSummary().then(setWatchlistSummary).catch(() => setWatchlistSummary([]))
  }

  useEffect(load, [])

  if (error && !prefs) return <ErrorBanner message={error} />
  if (!prefs) return <LoadingState />

  const save = async () => {
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const updated = await api.updateSearchPreferences(prefs)
      setPrefs(updated)
      setSaved(true)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to save settings.')
    } finally {
      setSaving(false)
    }
  }

  const addWatchlistEntry = async () => {
    if (!newWatchValue.trim()) return
    const entry = await api.addWatchlistEntry({ kind: newWatchKind, value: newWatchValue.trim() })
    setWatchlist((prev) => [entry, ...prev.filter((e) => e.id !== entry.id)])
    setNewWatchValue('')
    api.watchlistSummary().then(setWatchlistSummary).catch(() => {})
  }

  const removeWatchlistEntry = async (id: number) => {
    await api.removeWatchlistEntry(id)
    setWatchlist((prev) => prev.filter((e) => e.id !== id))
    setWatchlistSummary((prev) => prev.filter((s) => s.entry.id !== id))
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">Settings</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Scope how Career OS searches and alerts you — this overlays your profile files, it
          never replaces them.
        </p>
      </div>

      {error && <ErrorBanner message={error} />}

      <Card className="flex flex-col gap-4 p-6">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
          Search preferences
        </h2>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-slate-700 dark:text-slate-300">
            Target roles (comma-separated)
          </span>
          <input
            type="text"
            defaultValue={prefs.target_roles.join(', ')}
            onBlur={(e) => setPrefs({ ...prefs, target_roles: csvToList(e.target.value) })}
            className="rounded-lg border border-slate-300 px-3 py-2 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-slate-700 dark:text-slate-300">
            Target countries (comma-separated — {countries.join(', ')})
          </span>
          <input
            type="text"
            defaultValue={prefs.target_countries.join(', ')}
            onBlur={(e) => setPrefs({ ...prefs, target_countries: csvToList(e.target.value) })}
            className="rounded-lg border border-slate-300 px-3 py-2 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
          />
        </label>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700 dark:text-slate-300">
              Minimum match score
            </span>
            <input
              type="number"
              min={0}
              max={100}
              value={prefs.min_match_score}
              onChange={(e) => setPrefs({ ...prefs, min_match_score: Number(e.target.value) })}
              className="rounded-lg border border-slate-300 px-3 py-2 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700 dark:text-slate-300">
              Search frequency (hours)
            </span>
            <input
              type="number"
              min={1}
              value={prefs.search_frequency_hours}
              onChange={(e) =>
                setPrefs({ ...prefs, search_frequency_hours: Number(e.target.value) })
              }
              className="rounded-lg border border-slate-300 px-3 py-2 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700 dark:text-slate-300">
              Notification minimum score
            </span>
            <input
              type="number"
              min={0}
              max={100}
              value={prefs.notification_min_score}
              onChange={(e) =>
                setPrefs({ ...prefs, notification_min_score: Number(e.target.value) })
              }
              className="rounded-lg border border-slate-300 px-3 py-2 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700 dark:text-slate-300">
              Notification frequency
            </span>
            <select
              value={prefs.notification_frequency}
              onChange={(e) => setPrefs({ ...prefs, notification_frequency: e.target.value })}
              className="rounded-lg border border-slate-300 px-3 py-2 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            >
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="realtime">Real-time</option>
            </select>
          </label>
        </div>

        <div className="flex items-center gap-3">
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save preferences'}
          </Button>
          {saved && <span className="text-sm text-emerald-600 dark:text-emerald-400">Saved ✓</span>}
        </div>
      </Card>

      <Card className="flex flex-col gap-4 p-6">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">Watchlist</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Get flagged when a new job matches a company, role, or location you're watching for.
        </p>

        <div className="flex flex-wrap gap-2">
          <select
            value={newWatchKind}
            onChange={(e) => setNewWatchKind(e.target.value as WatchlistKind)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
          >
            {WATCHLIST_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <input
            type="text"
            value={newWatchValue}
            onChange={(e) => setNewWatchValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addWatchlistEntry()}
            placeholder="e.g. Stripe, Product Manager, Remote"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
          />
          <Button variant="secondary" onClick={addWatchlistEntry}>
            Add
          </Button>
        </div>

        {watchlist.length === 0 ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            No watchlist entries yet.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {watchlist.map((entry) => {
              const summary = watchlistSummary.find((s) => s.entry.id === entry.id)
              return (
                <li
                  key={entry.id}
                  className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-800"
                >
                  <div>
                    <span>
                      <span className="mr-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                        {entry.kind}
                      </span>
                      {entry.value}
                    </span>
                    {summary && (
                      <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        {summary.matching_count === 0
                          ? 'No matching roles yet'
                          : `${summary.matching_count} matching role${summary.matching_count === 1 ? '' : 's'}`}
                        {summary.new_matching_count > 0 &&
                          ` · ${summary.new_matching_count} new this week`}
                        {summary.highest_match_score !== null &&
                          ` · highest match ${summary.highest_match_score}%`}
                      </div>
                    )}
                  </div>
                  <Button variant="ghost" onClick={() => removeWatchlistEntry(entry.id)}>
                    Remove
                  </Button>
                </li>
              )
            })}
          </ul>
        )}
      </Card>
    </div>
  )
}
