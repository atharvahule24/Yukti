import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileUploader } from '../components/ui/file-uploader'

import {
  getSessions,
  deleteSession,
  getCumulativeLearnerAnalytics,
  getNextLearningAction,
} from '../lib/api'

import type {
Session,
LearnerAnalytics,
NextLearningAction,
} from '../lib/api'

import {
BookOpen,
Flame,
FileText,
Trash2,
Loader2,
Sparkles,
Brain,
Target,
AlertTriangle,
RotateCcw,
LogOut,
} from 'lucide-react'
import { removeToken } from '../lib/auth'

export function Dashboard() {
const navigate = useNavigate()

const [sessions, setSessions] = useState<Session[]>([])
const [loading, setLoading] = useState(true)

const [analytics, setAnalytics] = useState<LearnerAnalytics | null>(null)
const [analyticsLoading, setAnalyticsLoading] = useState(true)
const [nextAction, setNextAction] =
  useState<NextLearningAction | null>(null)

const [nextActionLoading, setNextActionLoading] = useState(true)

const [streak] = useState(() =>
parseInt(localStorage.getItem('sb_streak') || '0', 10)
)

useEffect(() => {
getCumulativeLearnerAnalytics()
  .then(data => {
    setAnalytics(data)
    setAnalyticsLoading(false)
  })
  .catch(err => {
    console.error('Failed to load cumulative analytics:', err)
    setAnalyticsLoading(false)
  })

getSessions()
.then(async data => {
const recentSessions = data.sessions.slice(0, 5)

setSessions(recentSessions)
setLoading(false)

if (recentSessions.length > 0) {
  const sessionId = recentSessions[0].id

try {
  const learnerNextAction = await getNextLearningAction(sessionId)
  setNextAction(learnerNextAction)
} catch (error) {
  console.error(
    'Failed to load next learning action:',
    error
  )
}
}

setNextActionLoading(false)
})
.catch(error => {
console.error('Failed to load sessions:', error)

setLoading(false)
setAnalyticsLoading(false)
})
}, [])

const handleDelete = async (
e: React.MouseEvent,
id: string
) => {
e.stopPropagation()

try {
await deleteSession(id)

setSessions(prev =>
prev.filter(s => s.id !== id)
)
} catch (err) {
console.error(err)
}
}

const handleLogout = () => {
  removeToken()
  navigate('/auth')
}

return (
<div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)] flex flex-col items-center py-12 px-4 relative overflow-hidden">

<button
  onClick={handleLogout}
  className="absolute top-4 right-4 z-50 flex items-center gap-2 px-3 py-1.5 rounded-full bg-[var(--bg-elevated)] border border-[var(--border)] text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-highlight)] transition-all"
>
  <LogOut size={16} />
  <span>Sign out</span>
</button>

{/* Background decoration */}

<div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-[var(--accent-purple-dim)] blur-[120px] pointer-events-none opacity-50" />

<div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-[var(--accent-gold-dim)] blur-[120px] pointer-events-none opacity-30" />

{/* Header */}

<div className="flex flex-col items-center mb-12 relative z-10 text-center">

<div className="flex items-center gap-3 mb-6">

<div className="w-12 h-12 bg-[var(--bg-elevated)] border border-[var(--border)] rounded-full flex items-center justify-center">

<BookOpen
size={24}
className="text-[var(--accent-purple)]"
/>

</div>

<h1 className="text-3xl font-bold tracking-tight">
Yukti
</h1>

</div>

<p className="text-[var(--text-secondary)] text-lg max-w-xl">
Transform your study materials into interactive tutors,
flashcards, and knowledge graphs.
</p>

</div>

{/* Main Upload Zone */}

<div className="w-full max-w-4xl mx-auto relative z-10 mb-16">

<FileUploader
onSuccess={(id) =>
navigate(`/chat/${id}`)
}
/>

</div>

{/* Learner Analytics */}

{!analyticsLoading && analytics && (
<div className="w-full max-w-4xl relative z-10 mb-16">

<div className="flex items-center justify-between mb-6 border-b border-[var(--border)] pb-4">

<h2 className="text-xl font-bold flex items-center gap-2">

<Brain
size={20}
className="text-[var(--accent-purple)]"
/>

Learner Progress

</h2>

<span className="text-xs text-[var(--text-secondary)]">
Cumulative across all sessions
</span>

</div>

{/* Summary cards */}

<div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">

<div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] p-5">

<div className="flex items-center gap-2 text-[var(--text-secondary)] text-sm mb-2">

<Target size={16} />

Overall Mastery

</div>

<div className="text-2xl font-bold">
{analytics.overall_mastery.toFixed(0)}%
</div>

</div>

<div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] p-5">

<div className="text-[var(--text-secondary)] text-sm mb-2">
Confidence
</div>

<div className="text-2xl font-bold">
{analytics.average_confidence.toFixed(2)}
</div>

</div>

<div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] p-5">

<div className="text-[var(--text-secondary)] text-sm mb-2">
Weak Concepts
</div>

<div className="text-2xl font-bold">
{analytics.weak_concepts}
</div>

</div>

<div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] p-5">

<div className="flex items-center gap-2 text-[var(--text-secondary)] text-sm mb-2">

<AlertTriangle size={16} />

Active Misc.

</div>

<div className="text-2xl font-bold">
{analytics.active_misconceptions}
</div>

</div>

<div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] p-5">

<div className="flex items-center gap-2 text-[var(--text-secondary)] text-sm mb-2">
Resolved
</div>

<div className="text-2xl font-bold text-[var(--accent-purple)]">
{analytics.resolved_misconceptions}
</div>

</div>

</div>

{/* Concept mastery */}

{analytics.concepts.length > 0 && (
<div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] p-6 mb-6">

<h3 className="font-semibold mb-5">
Concept Mastery
</h3>

<div className="space-y-4">

{analytics.concepts.map(concept => (

<div key={concept.concept}>

<div className="flex justify-between text-sm mb-2">

<span className="font-medium">
{concept.concept}
</span>

<span className="text-[var(--text-secondary)]">
{concept.mastery.toFixed(0)}%
</span>

</div>

<div className="h-2 bg-[var(--bg-elevated)] rounded-full overflow-hidden">

<div
className="h-full bg-[var(--accent-purple)] rounded-full transition-all"
style={{
width: `${Math.min(
100,
Math.max(0, concept.mastery)
)}%`,
}}
/>

</div>

</div>

))}

</div>

</div>
)}

{/* Active misconceptions */}

{analytics.misconceptions.length > 0 && (

<div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] p-6">

<div className="flex items-center gap-2 mb-5">

<AlertTriangle
size={18}
className="text-[var(--accent-gold)]"
/>

<h3 className="font-semibold">
Active Misconceptions
</h3>

</div>

<div className="space-y-4">

{analytics.misconceptions.map(
(item, index) => (

<div
key={`${item.concept}-${index}`}
className="border border-[var(--border)] rounded-lg p-4"
>

<div className="flex items-center justify-between mb-2">

<span className="font-medium">
{item.concept}
</span>

<span className="text-xs px-2 py-1 rounded-full bg-[var(--accent-gold-dim)] text-[var(--accent-gold)]">
{item.severity}
</span>

</div>

<p className="text-sm text-[var(--text-secondary)]">
{item.misconception}
</p>

{item.occurrences > 1 && (
<div className="flex items-center gap-2 text-xs text-[var(--text-muted)] mt-2">

<RotateCcw size={13} />

Detected {item.occurrences} times

</div>
)}

</div>

)
)}

</div>

</div>

)}

</div>
)}

{/* Next Learning Action */}

{!nextActionLoading && nextAction && (
  <button
    type="button"
    onClick={() => {
      const targetSessionId = sessions[0]?.id
      if (targetSessionId) navigate(`/chat/${targetSessionId}`)
    }}
    disabled={!sessions[0]?.id}
    className="w-full max-w-4xl mx-auto text-left bg-[var(--bg-surface)] border border-[var(--accent-purple-border)] rounded-[var(--radius-lg)] p-6 mb-6 transition-all hover:border-[var(--accent-purple)] hover:bg-[var(--accent-purple-dim)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-purple)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-base)] disabled:cursor-default"
    aria-label="Start your next learning step"
  >

    <div className="flex items-center gap-2 mb-4">

      <Target
        size={18}
        className="text-[var(--accent-purple)]"
      />

      <h3 className="font-semibold">
        Next Learning Step
      </h3>

    </div>

    <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">

      <div>

        <div className="text-lg font-bold capitalize">
          {nextAction.next_action.replaceAll('_', ' ')}
        </div>

        {nextAction.concept && (
          <div className="text-sm text-[var(--accent-purple)] mt-1">
            Concept: {nextAction.concept}
          </div>
        )}

        <p className="text-sm text-[var(--text-secondary)] mt-2">
          {nextAction.reason}
        </p>

      </div>

      <div className="flex gap-2 shrink-0">

        <span className="text-xs px-3 py-1.5 rounded-full bg-[var(--accent-purple-dim)] text-[var(--accent-purple)]">
          {nextAction.difficulty}
        </span>

        <span className="text-xs px-3 py-1.5 rounded-full bg-[var(--bg-elevated)] text-[var(--text-secondary)]">
          {nextAction.question_type}
        </span>

      </div>

      <span className="inline-flex items-center justify-center shrink-0 px-4 py-2 rounded-lg bg-[var(--accent-purple)] text-white text-sm font-semibold">
        Start Review →
      </span>

    </div>

  </button>
)}

{/* Recent Sessions */}

<div className="w-full max-w-4xl relative z-10">

<div className="flex items-center justify-between mb-6 border-b border-[var(--border)] pb-4">

<h2 className="text-xl font-bold flex items-center gap-2">

<FileText
size={20}
className="text-[var(--accent-purple)]"
/>

Recent Study Sessions

</h2>

<div className="flex items-center gap-2 px-4 py-1.5 bg-[var(--accent-gold-dim)] border border-[var(--accent-gold)] rounded-full text-[var(--accent-gold)]">

<Flame size={16} />

<span className="font-bold text-sm">
{streak} Day Streak
</span>

</div>

</div>

{loading ? (

<div className="flex justify-center p-8">

<Loader2
className="animate-spin text-[var(--text-secondary)]"
/>

</div>

) : sessions.length === 0 ? (

<div className="text-center p-12 border border-[var(--border)] border-dashed rounded-[var(--radius-lg)] bg-[var(--bg-surface)] text-[var(--text-secondary)]">

<Sparkles
size={32}
className="mx-auto mb-4 opacity-50"
/>

<p>
Upload a file or paste a YouTube link to start
your first session.
</p>

</div>

) : (

<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">

{sessions.map(s => (

<div
key={s.id}
onClick={() =>
navigate(`/chat/${s.id}`)
}
className="group bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] p-5 hover:border-[var(--accent-purple-border)] hover:bg-[var(--accent-purple-dim)] transition-all cursor-pointer relative"
>

<div className="pr-8">

<h3
className="font-medium text-[var(--text-primary)] truncate mb-1"
title={s.title}
>
{s.title}
</h3>

<div className="flex items-center gap-3 text-xs text-[var(--text-secondary)]">

<span>
{new Date(
s.created_at
).toLocaleDateString()}
</span>

<span>•</span>

<span>
{s.chunk_count} chunks
</span>

</div>

</div>

<button
onClick={(e) =>
handleDelete(e, s.id)
}
className="absolute top-4 right-4 p-2 text-[var(--text-muted)] hover:text-[var(--danger)] hover:bg-[var(--danger-dim)] rounded-full opacity-0 group-hover:opacity-100 transition-all"
>

<Trash2 size={16} />

</button>

</div>

))}

</div>

)}

</div>

</div>
)
}