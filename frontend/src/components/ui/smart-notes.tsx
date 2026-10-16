import { useState, useEffect, useRef } from 'react'
import { getNotes, generateNotes, getFact, getTaskStatus, TaskTerminalError, isTransientNetworkError } from '../../lib/api'
import { Loader2, FileText, ChevronRight, X, AlertCircle } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { toast } from 'sonner'

type Note = {
bullet: string
explanation: string
example?: string
importance?: string
}

export function SmartNotes({ sessionId }: { sessionId: string }) {
const [notes, setNotes] = useState<Note[]>([])
const [loading, setLoading] = useState(true)
const [generating, setGenerating] = useState(false)
const [fact, setFact] = useState('')
const [selectedNote, setSelectedNote] = useState<Note | null>(null)
const [errorMessage, setErrorMessage] = useState<string | null>(null)
const isMountedRef = useRef(true)

useEffect(() => {
isMountedRef.current = true
return () => {
isMountedRef.current = false
}
}, [])

useEffect(() => {
if (!sessionId) return

let cancelled = false

const loadNotes = async () => {
try {
const data = await getNotes(sessionId)
const pts = Array.isArray(data) ? data : data.points || []

if (!cancelled && isMountedRef.current) {
setNotes(pts)
setLoading(false)
}
} catch (error) {
console.error('Notes loading error:', error)

if (!cancelled && isMountedRef.current) {
setLoading(false)
}
}
}

loadNotes()

return () => {
cancelled = true
}
}, [sessionId])

const handleGenerate = async () => {
if (!sessionId || generating) return

setGenerating(true)
setErrorMessage(null)

try {
getFact(sessionId)
.then(res => {
  if (isMountedRef.current) setFact(res.fact)
})
.catch(() => {})

const task = await generateNotes(sessionId)

let attempts = 0
const maxAttempts = 60
let consecutiveErrors = 0
const maxConsecutiveErrors = 3

while (attempts < maxAttempts) {
  if (!isMountedRef.current) break

  try {
    const status = await getTaskStatus(task.task_id)
    consecutiveErrors = 0

    if (status.state === 'SUCCESS' || status.state === 'success') {
      const data = await getNotes(sessionId)
      const pts = Array.isArray(data) ? data : data.points || []

      if (isMountedRef.current) {
        setNotes(pts)
        setLoading(false)
      }
      break
    }

    if (status.state === 'FAILURE' || status.state === 'failure' || status.state === 'REVOKED' || status.state === 'revoked') {
      throw new TaskTerminalError(status.error || 'Notes generation failed')
    }
  } catch (pollErr: unknown) {
    if (pollErr instanceof TaskTerminalError || !isTransientNetworkError(pollErr)) {
      throw pollErr
    }
    consecutiveErrors++
    if (consecutiveErrors >= maxConsecutiveErrors) {
      throw new Error('Server connection interrupted. Please try again.')
    }
    await new Promise(r => setTimeout(r, 1000))
  }

  await new Promise(resolve => setTimeout(resolve, 2000))
  attempts++
}

if (attempts >= maxAttempts) {
throw new Error('Notes generation timed out. Please try again.')
}

} catch (e: any) {
console.error('Notes generation error:', e)
const rawMsg = e?.message || (typeof e === 'string' ? e : 'Notes generation failed. Please try again.')

let displayMsg = rawMsg
if (
  rawMsg.includes('429') ||
  rawMsg.toLowerCase().includes('rate limit') ||
  rawMsg.toLowerCase().includes('token limit') ||
  rawMsg.toLowerCase().includes('quota')
) {
  displayMsg = rawMsg.includes('Groq API rate limit reached')
    ? rawMsg
    : 'AI daily token rate limit reached. Please wait a few minutes before retrying.'
  toast.error(displayMsg, {
    duration: 8000,
    description: 'The AI service has reached its daily free quota limit. Please avoid repeated retries to allow the cooldown to complete.',
  })
} else {
  toast.error(displayMsg)
}

if (isMountedRef.current) {
  setErrorMessage(displayMsg)
}
} finally {
if (isMountedRef.current) {
  setGenerating(false)
}
}
}

if (loading) return <div className="flex justify-center p-8"><Loader2 className="animate-spin text-[var(--accent-purple)]" /></div>

if (notes.length === 0) {
if (generating) {
return (
<div className="flex flex-col items-center justify-center p-12 bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] text-center h-[500px]">
<Loader2 className="animate-spin text-[var(--accent-purple)] mb-6" size={48} />
<h3 className="text-xl font-bold mb-4 text-[var(--text-primary)]">Crafting Smart Notes...</h3>
{fact && (
<div className="max-w-md bg-[var(--accent-purple-dim)] p-4 rounded-[var(--radius-lg)] border border-[var(--accent-purple-border)] mt-4">
<p className="text-xs font-bold text-[var(--accent-purple)] uppercase mb-1">Did you know?</p>
<p className="text-sm text-[var(--text-primary)] italic">"{fact}"</p>
</div>
)}
</div>
)
}
return (
<div className="flex flex-col items-center justify-center p-8 bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] h-[500px]">
<h3 className="text-xl font-bold mb-4 text-[var(--text-primary)]">Smart Notes</h3>
<p className="text-sm text-[var(--text-secondary)] mb-6 text-center max-w-sm">Generate bite-sized, sticky-note style summaries of the key concepts from your material.</p>
{errorMessage && (
<div className="max-w-sm w-full mb-6 p-3 bg-red-500/10 border border-red-500/30 rounded-[var(--radius)] flex items-start gap-2.5 text-left">
<AlertCircle size={18} className="text-red-400 shrink-0 mt-0.5" />
<p className="text-xs text-red-200 leading-relaxed">{errorMessage}</p>
</div>
)}
<button
onClick={handleGenerate}
disabled={generating}
className="w-full max-w-sm flex items-center justify-center gap-2 bg-[var(--accent-purple)] text-white py-3 rounded-[var(--radius)] font-bold hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
>
<FileText size={18} /> {errorMessage ? 'Retry Generating Notes' : 'Generate Notes'}
</button>
</div>
)
}

// Richer dark-tinted colors for dark UI
const colors = [
'bg-[#2d2a1b] border border-[#4a4521] text-[#eab308]', // Dark yellow/amber
'bg-[#1a2d24] border border-[#224835] text-[#22c55e]', // Dark green/teal
'bg-[#1e2330] border border-[#28385e] text-[#60a5fa]', // Dark blue
'bg-[#301a24] border border-[#5e2846] text-[#f472b6]', // Dark pink
'bg-[#271d30] border border-[#4a2b66] text-[#c084fc]'  // Dark purple
]

const importanceStyles: Record<string, string> = {
high: 'bg-red-500/15 text-red-300 border border-red-500/25',
medium: 'bg-amber-500/15 text-amber-300 border border-amber-500/25',
low: 'bg-white/5 text-white/40 border border-white/10',
}

return (
<div className="w-full h-full relative">
<div className="px-4 pt-4 pb-2">
<h4 className="text-sm font-medium text-[var(--text-secondary)]">Key topics from your material</h4>
</div>
<div className="grid grid-cols-1 xl:grid-cols-2 gap-3.5 px-3 sm:px-4 pb-4">
{notes.map((note, idx) => {
const colorClass = colors[idx % colors.length]
return (
<motion.div
key={idx}
whileHover={{ scale: 1.01 }}
onClick={() => setSelectedNote(note)}
className={`cursor-pointer ${colorClass} p-3.5 sm:p-4 rounded-[var(--radius-lg)] shadow-sm hover:shadow-md transition-all min-h-[140px] flex flex-col justify-between relative overflow-hidden`}
>
<div>
<div className="flex items-center justify-between gap-2 mb-2">
<div className="flex items-center gap-1.5">
{idx % 3 === 2 && (
<span className="bg-white/10 text-white/90 text-[10px] px-1.5 py-0.5 rounded font-bold uppercase tracking-wider">
AI
</span>
)}
{note.importance && (
<span className={`text-[11px] px-2 py-0.5 rounded-full font-medium shrink-0 ${importanceStyles[note.importance] ?? importanceStyles.low}`}>
{note.importance}
</span>
)}
</div>
</div>

<h4 className="font-semibold text-sm sm:text-base leading-snug break-words line-clamp-3 mb-1.5">
{note.bullet}
</h4>

{note.explanation && (
<p className="text-xs opacity-75 line-clamp-2 leading-relaxed mb-2">
{note.explanation}
</p>
)}
</div>

<div className="flex items-center justify-between mt-auto border-t border-white/10 pt-2 text-xs opacity-70 font-medium">
<span>Click for details</span>
<ChevronRight size={14} className="opacity-70" />
</div>
</motion.div>
)
})}
</div>

<AnimatePresence>
{selectedNote && (
<>
<motion.div 
initial={{ opacity: 0 }}
animate={{ opacity: 1 }}
exit={{ opacity: 0 }}
onClick={() => setSelectedNote(null)}
className="fixed inset-0 bg-black/60 z-40 backdrop-blur-sm"
/>
<motion.div
initial={{ opacity: 0, scale: 0.9, y: 20 }}
animate={{ opacity: 1, scale: 1, y: 0 }}
exit={{ opacity: 0, scale: 0.9, y: 20 }}
className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-lg bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-2xl z-50 overflow-hidden"
>
<div className="p-6">
<div className="flex justify-between items-start mb-6">
<div className="pr-8">
<div className="flex items-center gap-3 flex-wrap">
<h3 className="text-2xl font-bold text-[var(--text-primary)]">{selectedNote.bullet}</h3>
{selectedNote.importance && (
<span className={`text-xs px-2 py-0.5 rounded-full ${importanceStyles[selectedNote.importance] ?? importanceStyles.low}`}>
{selectedNote.importance}
</span>
)}
</div>
</div>
<button 
onClick={() => setSelectedNote(null)}
className="p-1 rounded-full hover:bg-[var(--bg-elevated)] transition-colors absolute top-4 right-4"
>
<X size={20} className="text-[var(--text-secondary)]" />
</button>
</div>

<div className="space-y-6">
<div>
<h4 className="text-xs uppercase tracking-wider text-[var(--accent-purple)] font-bold mb-2">Explanation</h4>
<p className="text-[var(--text-secondary)] leading-relaxed text-sm bg-[var(--bg-elevated)] p-4 rounded-[var(--radius)]">
{selectedNote.explanation}
</p>
</div>

{selectedNote.example && (
<div>
<h4 className="text-xs uppercase tracking-wider text-[var(--accent-gold)] font-bold mb-2">Example</h4>
<p className="text-[var(--text-secondary)] leading-relaxed text-sm bg-[var(--bg-elevated)] p-4 rounded-[var(--radius)] italic">
"{selectedNote.example}"
</p>
</div>
)}
</div>

<div className="mt-8 pt-4 border-t border-[var(--border)] flex justify-end">
<button 
onClick={() => {
const question = `Can you explain more about: "${selectedNote.bullet}"?`
window.dispatchEvent(new CustomEvent('yukti:ask', { detail: question }))
setSelectedNote(null)
}}
className="text-sm text-[var(--accent-purple)] hover:underline font-medium"
>
Discuss with Tutor &rarr;
</button>
</div>
</div>
</motion.div>
</>
)}
</AnimatePresence>
</div>
)
}
