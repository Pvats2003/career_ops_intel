import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api'
import { Card, EmptyState, ErrorBanner, LoadingState } from '../components/ui'
import type { CompanyOut } from '../types'

function fitColor(fit: number | null): string {
  if (fit === null) return 'text-slate-400 dark:text-slate-500'
  if (fit >= 70) return 'text-emerald-600 dark:text-emerald-400'
  if (fit >= 40) return 'text-amber-500 dark:text-amber-400'
  return 'text-slate-500 dark:text-slate-400'
}

export default function Companies() {
  const [companies, setCompanies] = useState<CompanyOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .listCompanies()
      .then(setCompanies)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load companies.'))
  }, [])

  if (error) return <ErrorBanner message={error} />
  if (!companies) return <LoadingState />

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">Companies</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Every company with a discovered job posting — fit scores are computed only from your
          own real matches, never a guessed "culture fit".
        </p>
      </div>

      {companies.length === 0 ? (
        <EmptyState
          title="No companies yet"
          description="Scan for jobs to start building a company list from real discovered postings."
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {companies.map((c) => (
            <Link key={c.id} to={`/companies/${c.id}`}>
              <Card className="flex items-center justify-between p-5">
                <div className="min-w-0">
                  <div className="truncate font-semibold text-slate-900 dark:text-slate-50">
                    {c.name}
                  </div>
                  <div className="text-sm text-slate-500 dark:text-slate-400">
                    {c.open_roles} open role{c.open_roles === 1 ? '' : 's'}
                  </div>
                </div>
                <div className={`text-lg font-bold tabular-nums ${fitColor(c.company_fit)}`}>
                  {c.company_fit ?? '—'}
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
