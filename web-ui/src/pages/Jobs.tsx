import { useEffect, useState, type ReactNode } from 'react'
import { api, ApiError } from '../api'
import { JobCard } from '../components/JobCard'
import { JobCompare } from '../components/JobCompare'
import { Button, EmptyState, ErrorBanner, LoadingState } from '../components/ui'
import type { JobListOut } from '../types'

const MAX_COMPARE = 6

const SORTS = [
  { value: 'match', label: 'Best match' },
  { value: 'newest', label: 'Newest' },
  { value: 'salary', label: 'Highest salary' },
  { value: 'company', label: 'Company' },
]

export default function Jobs() {
  const [data, setData] = useState<JobListOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const [minScore, setMinScore] = useState('')
  const [remoteType, setRemoteType] = useState('')
  const [location, setLocation] = useState('')
  const [company, setCompany] = useState('')
  const [sort, setSort] = useState('match')

  const [compareIds, setCompareIds] = useState<number[]>([])
  const [showCompare, setShowCompare] = useState(false)
  const toggleCompare = (id: number) => {
    setCompareIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      if (prev.length >= MAX_COMPARE) return prev
      return [...prev, id]
    })
  }

  const load = () => {
    setLoading(true)
    setError(null)
    api
      .listJobs({
        min_score: minScore || undefined,
        remote_type: remoteType || undefined,
        location: location || undefined,
        company: company || undefined,
        sort,
      })
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load jobs.'))
      .finally(() => setLoading(false))
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [sort])

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">Jobs</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Every job discovered so far, ranked and filterable.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <Field label="Min match score">
          <input
            type="number"
            min={0}
            max={100}
            value={minScore}
            onChange={(e) => setMinScore(e.target.value)}
            className="w-24 rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
            placeholder="0"
          />
        </Field>
        <Field label="Remote type">
          <input
            value={remoteType}
            onChange={(e) => setRemoteType(e.target.value)}
            className="w-32 rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
            placeholder="remote"
          />
        </Field>
        <Field label="Location">
          <input
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            className="w-40 rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
            placeholder="Singapore"
          />
        </Field>
        <Field label="Company">
          <input
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            className="w-40 rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
            placeholder="Acme"
          />
        </Field>
        <Field label="Sort by">
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
          >
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </Field>
        <Button variant="primary" onClick={load}>
          Apply filters
        </Button>
      </div>

      {compareIds.length >= 2 && !showCompare && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm dark:border-indigo-900 dark:bg-indigo-900/20">
          <span className="text-indigo-800 dark:text-indigo-200">
            {compareIds.length} job{compareIds.length === 1 ? '' : 's'} selected to compare
          </span>
          <div className="flex gap-2">
            <Button variant="primary" onClick={() => setShowCompare(true)}>
              Compare
            </Button>
            <Button variant="ghost" onClick={() => setCompareIds([])}>
              Clear
            </Button>
          </div>
        </div>
      )}

      {showCompare && compareIds.length >= 2 && (
        <JobCompare jobIds={compareIds} onClose={() => setShowCompare(false)} />
      )}

      {error && <ErrorBanner message={error} />}
      {loading && <LoadingState />}

      {!loading && data && (
        <>
          <div className="text-sm text-slate-500 dark:text-slate-400">
            {data.total} job{data.total === 1 ? '' : 's'}
          </div>
          {data.items.length === 0 ? (
            <EmptyState
              title="No jobs match your filters"
              description="Try widening your filters, or scan for jobs from the Dashboard if you haven't yet."
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {data.items.map((job) => (
                <JobCard
                  key={job.id}
                  job={job}
                  onSave={() => api.saveJob(job.id).then(load)}
                  compareSelected={compareIds.includes(job.id)}
                  onToggleCompare={toggleCompare}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</span>
      {children}
    </label>
  )
}
