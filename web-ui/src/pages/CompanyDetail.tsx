import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { JobCard } from '../components/JobCard'
import { Card, ErrorBanner, LoadingState } from '../components/ui'
import type { CompanyOut } from '../types'

export default function CompanyDetail() {
  const { id } = useParams()
  const [company, setCompany] = useState<CompanyOut | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    api
      .getCompany(Number(id))
      .then(setCompany)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load company.'))
  }, [id])

  if (error) return <ErrorBanner message={error} />
  if (!company) return <LoadingState />

  return (
    <div className="flex flex-col gap-6">
      <Link
        to="/companies"
        className="text-sm text-indigo-600 hover:underline dark:text-indigo-400"
      >
        ← Back to companies
      </Link>

      <Card className="p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">
              {company.name}
            </h1>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {company.open_roles} open role{company.open_roles === 1 ? '' : 's'} discovered
              {company.website && (
                <>
                  {' · '}
                  <a
                    href={company.website}
                    target="_blank"
                    rel="noreferrer"
                    className="text-indigo-600 hover:underline dark:text-indigo-400"
                  >
                    website
                  </a>
                </>
              )}
            </p>
          </div>
          <div className="text-3xl font-bold tabular-nums text-slate-900 dark:text-slate-50">
            {company.company_fit ?? '—'}
          </div>
        </div>

        {company.company_fit_reasons.length > 0 && (
          <ul className="mt-4 list-inside list-disc text-sm text-slate-600 dark:text-slate-400">
            {company.company_fit_reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}

        {!company.industry && !company.size && (
          <p className="mt-3 text-xs text-slate-400 dark:text-slate-500">
            Industry, size, and other company details are unknown — never guessed.
          </p>
        )}
      </Card>

      {company.best_role && (
        <section>
          <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-slate-50">
            Best role for you at {company.name}
          </h2>
          <JobCard job={company.best_role} />
        </section>
      )}

      <section>
        <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-slate-50">
          {company.best_role ? 'Other opportunities' : `Open roles at ${company.name}`}
        </h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {company.matching_jobs
            .filter((job) => job.id !== company.best_role?.id)
            .map((job) => (
              <JobCard key={job.id} job={job} />
            ))}
        </div>
      </section>
    </div>
  )
}
