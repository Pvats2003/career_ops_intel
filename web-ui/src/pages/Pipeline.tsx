import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api'
import { Card, EmptyState, ErrorBanner, LoadingState } from '../components/ui'
import {
  PIPELINE_STAGES,
  type ApplicationHistoryEventOut,
  type PipelineItemOut,
  type PipelineStage,
} from '../types'

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
  const [expandedId, setExpandedId] = useState<number | null>(null)

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

  const toggleChecklistItem = async (
    applicationId: number,
    field: 'cover_letter_ready' | 'questions_prepared',
    value: boolean,
  ) => {
    setItems((prev) =>
      prev
        ? prev.map((i) =>
            i.application_id === applicationId
              ? { ...i, checklist: { ...i.checklist, [field]: value } }
              : i,
          )
        : prev,
    )
    try {
      await api.updatePipelineItem(applicationId, { [field]: value })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to update checklist.')
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
                      <div className="mt-2 flex items-center justify-between gap-2">
                        <select
                          value={item.pipeline_stage}
                          onChange={(e) =>
                            moveTo(item.application_id, e.target.value as PipelineStage)
                          }
                          className="w-full rounded-md border border-slate-300 px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-800"
                        >
                          {PIPELINE_STAGES.map((s) => (
                            <option key={s} value={s}>
                              {STAGE_LABELS[s]}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedId((prev) =>
                              prev === item.application_id ? null : item.application_id,
                            )
                          }
                          className="shrink-0 text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                        >
                          {expandedId === item.application_id ? 'Hide' : 'Details'}
                        </button>
                      </div>
                      {expandedId === item.application_id && (
                        <ApplicationDetail
                          item={item}
                          onToggleChecklist={toggleChecklistItem}
                        />
                      )}
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

function CheckRow({
  label,
  checked,
  editable,
  onChange,
}: {
  label: string
  checked: boolean
  editable?: boolean
  onChange?: (value: boolean) => void
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-slate-700 dark:text-slate-300">
      <input
        type="checkbox"
        checked={checked}
        disabled={!editable}
        onChange={(e) => onChange?.(e.target.checked)}
        className="h-3.5 w-3.5 rounded border-slate-300 text-indigo-600 disabled:opacity-60 dark:border-slate-600"
      />
      {label}
    </label>
  )
}

function ApplicationDetail({
  item,
  onToggleChecklist,
}: {
  item: PipelineItemOut
  onToggleChecklist: (
    applicationId: number,
    field: 'cover_letter_ready' | 'questions_prepared',
    value: boolean,
  ) => void
}) {
  const [history, setHistory] = useState<ApplicationHistoryEventOut[] | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const s = item.scorecard
  const c = item.checklist

  const loadHistory = () => {
    api
      .applicationHistory(item.application_id)
      .then(setHistory)
      .catch((e) =>
        setHistoryError(e instanceof ApiError ? e.message : 'Failed to load history.'),
      )
  }

  return (
    <div className="mt-3 space-y-3 border-t border-slate-200 pt-3 text-xs dark:border-slate-800">
      <div>
        <div className="mb-1 flex items-center justify-between font-medium text-slate-700 dark:text-slate-300">
          <span>Scorecard</span>
          <span className="font-semibold text-indigo-600 dark:text-indigo-400">
            {s.overall_score}/100
          </span>
        </div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-slate-500 dark:text-slate-400">
          <span>Candidate fit: {s.candidate_fit}</span>
          <span>Job quality: {s.job_quality}</span>
          <span>Career value: {s.career_value}</span>
          <span>Viability: {s.application_viability}</span>
        </div>
        <p className="mt-1 text-slate-600 dark:text-slate-400">{s.overall_recommendation}</p>
      </div>

      <div>
        <div className="mb-1 font-medium text-slate-700 dark:text-slate-300">Checklist</div>
        <div className="grid grid-cols-2 gap-1.5">
          <CheckRow label="Resume selected" checked={c.resume_selected} />
          <CheckRow label="Resume tailored" checked={c.resume_tailored} />
          <CheckRow
            label="Cover letter ready"
            checked={c.cover_letter_ready}
            editable
            onChange={(v) => onToggleChecklist(item.application_id, 'cover_letter_ready', v)}
          />
          <CheckRow
            label="Questions prepared"
            checked={c.questions_prepared}
            editable
            onChange={(v) => onToggleChecklist(item.application_id, 'questions_prepared', v)}
          />
          <CheckRow label="Submitted" checked={c.submitted} />
          <CheckRow label="Confirmation received" checked={c.confirmation_received} />
        </div>
      </div>

      <div>
        {history === null ? (
          <button
            type="button"
            onClick={loadHistory}
            className="font-medium text-indigo-600 hover:underline dark:text-indigo-400"
          >
            View history
          </button>
        ) : (
          <>
            <div className="mb-1 font-medium text-slate-700 dark:text-slate-300">History</div>
            {historyError && <p className="text-rose-600 dark:text-rose-400">{historyError}</p>}
            <ul className="space-y-1 text-slate-500 dark:text-slate-400">
              {history.map((e, i) => (
                <li key={i}>
                  <span className="font-mono">{new Date(e.created_at).toLocaleString()}</span> —{' '}
                  {e.event_type}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  )
}
