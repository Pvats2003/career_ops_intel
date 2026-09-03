import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api'
import { Card, EmptyState, ErrorBanner, LoadingState } from '../components/ui'
import { PIPELINE_STAGES, type PipelineItemOut, type PipelineStage } from '../types'

const STAGE_LABELS: Record<PipelineStage, string> = {
  SAVED: 'Saved',
  SHORTLISTED: 'Shortlisted',
  APPLY: 'Apply',
  APPLIED: 'Applied',
  ASSESSMENT: 'Assessment',
  INTERVIEW: 'Interview',
  OFFER: 'Offer',
  REJECTED: 'Rejected',
}

export default function Pipeline() {
  const [items, setItems] = useState<PipelineItemOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [draggingId, setDraggingId] = useState<number | null>(null)

  const load = () => {
    setError(null)
    api
      .listPipeline()
      .then(setItems)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load pipeline.'))
  }

  useEffect(load, [])

  const moveTo = async (applicationId: number, stage: PipelineStage) => {
    setItems((prev) =>
      prev
        ? prev.map((i) => (i.application_id === applicationId ? { ...i, pipeline_stage: stage } : i))
        : prev,
    )
    try {
      await api.updatePipelineItem(applicationId, { pipeline_stage: stage })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to move item.')
      load()
    }
  }

  if (error && !items) return <ErrorBanner message={error} />
  if (!items) return <LoadingState />

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">
          Applications
        </h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Drag a card between stages, or use the dropdown on each card.
        </p>
      </div>

      {error && <ErrorBanner message={error} />}

      {items.length === 0 ? (
        <EmptyState
          title="Nothing saved yet"
          description="Save a job from the Jobs page to start tracking it through your pipeline."
          action={
            <Link
              to="/jobs"
              className="text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
            >
              Browse jobs →
            </Link>
          }
        />
      ) : (
        <div className="flex gap-4 overflow-x-auto pb-4">
          {PIPELINE_STAGES.map((stage) => {
            const stageItems = items.filter((i) => i.pipeline_stage === stage)
            return (
              <div
                key={stage}
                className="flex w-72 shrink-0 flex-col gap-3 rounded-xl bg-slate-100/70 p-3 dark:bg-slate-900/50"
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => draggingId !== null && moveTo(draggingId, stage)}
              >
                <div className="flex items-center justify-between px-1">
                  <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                    {STAGE_LABELS[stage]}
                  </h3>
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {stageItems.length}
                  </span>
                </div>
                <div className="flex flex-col gap-2">
                  {stageItems.map((item) => (
                    <Card
                      key={item.application_id}
                      className="cursor-grab p-3 active:cursor-grabbing"
                    >
                      <div
                        draggable
                        onDragStart={() => setDraggingId(item.application_id)}
                        onDragEnd={() => setDraggingId(null)}
                      >
                        <Link
                          to={`/jobs/${item.job.id}`}
                          className="block truncate text-sm font-medium text-slate-900 hover:text-indigo-600 dark:text-slate-50 dark:hover:text-indigo-400"
                        >
                          {item.job.title}
                        </Link>
                        <div className="truncate text-xs text-slate-500 dark:text-slate-400">
                          {item.job.company_name}
                        </div>
                        {item.job.match && (
                          <div className="mt-1 text-xs font-medium text-indigo-600 dark:text-indigo-400">
                            {item.job.match.overall_score}% match
                          </div>
                        )}
                      </div>
                      <select
                        value={item.pipeline_stage}
                        onChange={(e) =>
                          moveTo(item.application_id, e.target.value as PipelineStage)
                        }
                        className="mt-2 w-full rounded-md border border-slate-300 px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-800"
                      >
                        {PIPELINE_STAGES.map((s) => (
                          <option key={s} value={s}>
                            {STAGE_LABELS[s]}
                          </option>
                        ))}
                      </select>
                    </Card>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
