import { useState } from 'react'
import { api, ApiError } from '../api'
import { Button, Card } from './ui'

interface ChatTurn {
  question: string
  answer: string
  generatedBy: 'llm' | 'deterministic'
  groundedIn: string[]
}

const SUGGESTIONS = [
  'What are the best jobs for me today?',
  'What skills should I focus on learning?',
  'Should I follow up on any applications?',
]

export function CareerChat() {
  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const ask = async (q: string) => {
    if (!q.trim()) return
    setLoading(true)
    setError(null)
    try {
      const response = await api.careerChat({ question: q.trim() })
      setTurns((prev) => [
        {
          question: q.trim(),
          answer: response.answer,
          generatedBy: response.generated_by,
          groundedIn: response.grounded_in,
        },
        ...prev,
      ])
      setQuestion('')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to get an answer.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card className="p-6">
      <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">Career chat</h2>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        Ask about your job search — answered from your actual Career OS data, never generic
        advice.
      </p>

      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && ask(question)}
          placeholder="e.g. What are the best jobs for me today?"
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
        <Button
          variant="secondary"
          onClick={() => ask(question)}
          disabled={loading || !question.trim()}
        >
          {loading ? 'Thinking…' : 'Ask'}
        </Button>
      </div>

      {turns.length === 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => ask(s)}
              className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 hover:border-indigo-300 hover:text-indigo-600 dark:border-slate-700 dark:text-slate-300 dark:hover:text-indigo-400"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {error && <p className="mt-2 text-sm text-rose-600 dark:text-rose-400">{error}</p>}

      {turns.length > 0 && (
        <div className="mt-4 space-y-4">
          {turns.map((t, i) => (
            <div key={i} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
              <div className="text-sm font-medium text-slate-700 dark:text-slate-300">
                {t.question}
              </div>
              <p className="mt-1 whitespace-pre-line text-sm text-slate-700 dark:text-slate-300">
                {t.answer}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500">
                {t.generatedBy === 'deterministic' && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">
                    No AI configured — showing your real data
                  </span>
                )}
                {t.groundedIn.map((g) => (
                  <span key={g} className="rounded-full bg-indigo-50 px-2 py-0.5 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-300">
                    {g}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}
