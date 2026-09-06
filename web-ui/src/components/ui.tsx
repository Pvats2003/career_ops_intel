import type { ReactNode } from 'react'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900 ${className}`}
    >
      {children}
    </div>
  )
}

export function StatTile({
  label,
  value,
  accent = false,
}: {
  label: string
  value: string | number
  accent?: boolean
}) {
  return (
    <Card className="px-5 py-4">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </div>
      <div
        className={`mt-1 text-3xl font-semibold tabular-nums ${accent ? 'text-indigo-600 dark:text-indigo-400' : 'text-slate-900 dark:text-slate-50'}`}
      >
        {value}
      </div>
    </Card>
  )
}

const DECISION_STYLES: Record<string, string> = {
  APPLY: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
  REVIEW: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  SAVE: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300',
  SKIP: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400',
  HUMAN_REQUIRED: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300',
}

const DECISION_LABELS: Record<string, string> = {
  APPLY: '🔥 Apply immediately',
  REVIEW: '🟢 Strong match',
  SAVE: '🟡 Possible match',
  SKIP: '🔴 Weak match',
  HUMAN_REQUIRED: '⚠️ Needs review',
}

export function DecisionBadge({ decision }: { decision: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${
        DECISION_STYLES[decision] ?? DECISION_STYLES.SKIP
      }`}
    >
      {DECISION_LABELS[decision] ?? decision}
    </span>
  )
}

export function ScoreRing({ score }: { score: number }) {
  const color =
    score >= 85
      ? 'text-emerald-600 dark:text-emerald-400'
      : score >= 65
        ? 'text-amber-500 dark:text-amber-400'
        : 'text-slate-400 dark:text-slate-500'
  return (
    <div className={`flex flex-col items-center justify-center ${color}`}>
      <span className="text-2xl font-bold tabular-nums leading-none">{score}</span>
      <span className="text-[10px] font-medium uppercase tracking-wide text-slate-400 dark:text-slate-500">
        match
      </span>
    </div>
  )
}

export function PipelineStageBadge({ stage }: { stage: string }) {
  const styles: Record<string, string> = {
    SAVED: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
    SHORTLISTED: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300',
    APPLY: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
    APPLIED: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300',
    ASSESSMENT: 'bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300',
    INTERVIEW: 'bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300',
    OFFER: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
    REJECTED: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300',
  }
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${styles[stage] ?? styles.SAVED}`}
    >
      {stage.charAt(0) + stage.slice(1).toLowerCase()}
    </span>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 px-6 py-16 text-center dark:border-slate-700">
      <h3 className="text-base font-semibold text-slate-800 dark:text-slate-100">{title}</h3>
      <p className="mt-1.5 max-w-md text-sm text-slate-500 dark:text-slate-400">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function Spinner({ className = '' }: { className?: string }) {
  return (
    <svg
      className={`animate-spin ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      aria-label="Loading"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  )
}

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-slate-500 dark:text-slate-400">
      <Spinner className="h-5 w-5" />
      <span className="text-sm">{label}</span>
    </div>
  )
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-900/50 dark:bg-rose-900/20 dark:text-rose-300">
      {message}
    </div>
  )
}

export function Button({
  children,
  onClick,
  variant = 'primary',
  disabled,
  type = 'button',
  className = '',
}: {
  children: ReactNode
  onClick?: () => void
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  disabled?: boolean
  type?: 'button' | 'submit'
  className?: string
}) {
  const styles: Record<string, string> = {
    primary:
      'bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-indigo-300 dark:disabled:bg-indigo-900',
    secondary:
      'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 dark:bg-slate-900 dark:text-slate-200 dark:border-slate-700 dark:hover:bg-slate-800',
    ghost:
      'bg-transparent text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800',
    danger: 'bg-rose-600 text-white hover:bg-rose-500 disabled:bg-rose-300',
  }
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed ${styles[variant]} ${className}`}
    >
      {children}
    </button>
  )
}
