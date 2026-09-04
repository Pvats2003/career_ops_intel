import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import { CareerChat } from '../components/CareerChat'
import { Card, ErrorBanner, LoadingState } from '../components/ui'
import type { CareerPathComparisonRowOut, CareerProfileOut, SkillGapEntryOut } from '../types'

function Bar({ pct }: { pct: number }) {
  return (
    <div className="h-2 w-full rounded-full bg-slate-100 dark:bg-slate-800">
      <div
        className="h-2 rounded-full bg-indigo-500"
        style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
      />
    </div>
  )
}

export default function Career() {
  const [profile, setProfile] = useState<CareerProfileOut | null>(null)
  const [comparison, setComparison] = useState<CareerPathComparisonRowOut[]>([])
  const [skillGaps, setSkillGaps] = useState<SkillGapEntryOut[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .careerProfile()
      .then(setProfile)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load career data.'))
    api.careerPathComparison().then(setComparison).catch(() => setComparison([]))
    api.skillGaps().then(setSkillGaps).catch(() => setSkillGaps([]))
  }, [])

  if (error) return <ErrorBanner message={error} />
  if (!profile) return <LoadingState />

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">
          Career profile
        </h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          What kind of career you're building, derived from your discovered career paths — never
          a separate guess about you.
        </p>
      </div>

      <CareerChat />

      <Card className="p-6">
        {profile.primary_direction ? (
          <>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Primary direction
            </div>
            <div className="mt-1 text-xl font-semibold text-slate-900 dark:text-slate-50">
              {profile.primary_direction}
            </div>

            {profile.strengths.length > 0 && (
              <div className="mt-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  Strengths
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {profile.strengths.map((s) => (
                    <span
                      key={s}
                      className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {profile.growing_area && (
              <div className="mt-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  Growing area
                </div>
                <div className="mt-1 text-sm text-slate-700 dark:text-slate-300">
                  {profile.growing_area}
                </div>
              </div>
            )}

            {profile.skill_gaps.length > 0 && (
              <div className="mt-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  Skill gap
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {profile.skill_gaps.map((s) => (
                    <span
                      key={s}
                      className="rounded-full bg-amber-50 px-2.5 py-0.5 text-xs text-amber-700 dark:bg-amber-900/30 dark:text-amber-300"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </>
        ) : (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Not enough profile/skill data yet to identify a primary career direction.
          </p>
        )}

        {profile.best_locations.length > 0 && (
          <div className="mt-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Best locations
            </div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {profile.best_locations.map((l) => (
                <span
                  key={l}
                  className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-300"
                >
                  {l}
                </span>
              ))}
            </div>
          </div>
        )}
      </Card>

      {comparison.length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-slate-50">
            Compare career paths
          </h2>
          <Card className="overflow-x-auto p-0">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:text-slate-400">
                  <th className="px-4 py-3">Path</th>
                  <th className="px-4 py-3">Current fit</th>
                  <th className="px-4 py-3">Job volume</th>
                  <th className="px-4 py-3">Career upside</th>
                  <th className="px-4 py-3">Skill gap</th>
                  <th className="px-4 py-3">Your interview rate</th>
                  <th className="px-4 py-3">Overall</th>
                </tr>
              </thead>
              <tbody>
                {comparison.map((row) => (
                  <tr
                    key={row.label}
                    className="border-b border-slate-100 last:border-0 dark:border-slate-800"
                  >
                    <td className="px-4 py-3 font-medium text-slate-900 dark:text-slate-50">
                      {row.label}
                    </td>
                    <td className="px-4 py-3">{row.current_fit}</td>
                    <td className="px-4 py-3">{row.job_volume}</td>
                    <td className="px-4 py-3">{row.career_upside}</td>
                    <td className="px-4 py-3">{row.skill_gap}</td>
                    <td className="px-4 py-3">
                      {row.interview_rate === null
                        ? 'Insufficient data'
                        : `${Math.round(row.interview_rate * 100)}%`}
                    </td>
                    <td className="px-4 py-3 font-semibold text-indigo-600 dark:text-indigo-400">
                      {row.overall}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </section>
      )}

      {skillGaps.length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-slate-50">
            Skills to learn
          </h2>
          <Card className="flex flex-col gap-4 p-6">
            {skillGaps.map((s) => (
              <div key={s.skill}>
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium text-slate-900 dark:text-slate-50">{s.skill}</span>
                  <span className="text-slate-500 dark:text-slate-400">{s.frequency_pct}%</span>
                </div>
                <div className="mt-1">
                  <Bar pct={s.frequency_pct} />
                </div>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  Appears in {s.frequency_pct}% of your strongest matches.
                  {s.unlocks_count > 0 &&
                    ` Learning this could unlock approximately ${s.unlocks_count} additional ${s.unlocks_count === 1 ? 'opportunity' : 'opportunities'}.`}
                  {s.relevant_career_paths.length > 0 &&
                    ` Relevant to: ${s.relevant_career_paths.join(', ')}.`}
                </p>
              </div>
            ))}
          </Card>
        </section>
      )}
    </div>
  )
}
