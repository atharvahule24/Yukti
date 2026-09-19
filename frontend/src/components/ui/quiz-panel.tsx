import { useState, useEffect } from 'react'
import { getQuiz, generateQuiz, getFact, gradeAnswer } from '../../lib/api'
import type { GradeResult, MCQ, ShortAnswer } from '../../lib/api'
import { Loader2, CheckCircle2, XCircle, ChevronRight, HelpCircle, MessageSquare } from 'lucide-react'

export function QuizPanel({ sessionId }: { sessionId: string }) {
const [mcq, setMcq] = useState<MCQ[]>([])
const [sa, setSa] = useState<ShortAnswer[]>([])
const [loading, setLoading] = useState(true)

// MCQ State
const [mcqAnswers, setMcqAnswers] = useState<Record<string, number>>({})
const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0)
const [showHint, setShowHint] = useState(false)
const [shortAnswers, setShortAnswers] = useState<Record<string, string>>({})
const [gradingResults, setGradingResults] = useState<Record<string, GradeResult>>({})
const [gradingQuestionId, setGradingQuestionId] = useState<string | null>(null)

// Generation State
const [generating, setGenerating] = useState(false)
const [fact, setFact] = useState<string>('')
const [options, setOptions] = useState({ difficulty: 'medium', count: 5 })

useEffect(() => {
if (!sessionId) return
setLoading(true)
getQuiz(sessionId)
.then(data => {
setMcq(data.mcq || [])
setSa(data.short_answer || [])
setLoading(false)
})
.catch(() => setLoading(false))
}, [sessionId])

const handleGenerate = async () => {
if (!sessionId) return
setGenerating(true)
try {
// Get fact first to show while generating
getFact(sessionId).then(res => setFact(res.fact)).catch(() => {})

const data = await generateQuiz(sessionId, options)
setMcq(data.mcq || [])
setSa(data.short_answer || [])
setCurrentQuestionIndex(0)
setMcqAnswers({})
setShortAnswers({})
setGradingResults({})
setShowHint(false)
} catch (e) {
console.error(e)
} finally {
setGenerating(false)
}
}

const askDetailedExplanation = (q: MCQ) => {
const question = `Can you give me a detailed explanation for the question: "${q.question}"?`
window.dispatchEvent(new CustomEvent('yukti:ask', { detail: question }))
}

const handleGradeShortAnswer = async (question: ShortAnswer) => {
const answer = shortAnswers[question.id]?.trim()
if (!answer) return

setGradingQuestionId(question.id)
try {
const result = await gradeAnswer(question.question, answer, question.sample_answer, sessionId, question.concept)
setGradingResults(prev => ({ ...prev, [question.id]: result }))
} catch (e) {
console.error(e)
} finally {
setGradingQuestionId(null)
}
}

if (loading) return <div className="flex justify-center p-8"><Loader2 className="animate-spin text-[var(--accent-purple)]" /></div>

if (mcq.length === 0 && sa.length === 0) {
if (generating) {
return (
<div className="flex flex-col items-center justify-center p-12 bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] text-center h-[500px]">
<Loader2 className="animate-spin text-[var(--accent-purple)] mb-6" size={48} />
<h3 className="text-xl font-bold mb-4 text-[var(--text-primary)]">Generating your Quiz...</h3>
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
<h3 className="text-xl font-bold mb-4 text-[var(--text-primary)]">Custom Quiz</h3>
<p className="text-sm text-[var(--text-secondary)] mb-6 text-center">Generate a customized quiz from your study material.</p>

<div className="w-full max-w-sm space-y-4 mb-8">
<div>
<label className="block text-sm font-medium text-[var(--text-secondary)] mb-2">Difficulty</label>
<select 
value={options.difficulty}
onChange={e => setOptions({...options, difficulty: e.target.value})}
className="w-full p-2 bg-[var(--bg-base)] border border-[var(--border)] rounded-[var(--radius)] text-[var(--text-primary)] outline-none focus:border-[var(--accent-purple)]"
>
<option value="easy">Easy</option>
<option value="medium">Medium</option>
<option value="hard">Hard</option>
</select>
</div>
<div>
<label className="block text-sm font-medium text-[var(--text-secondary)] mb-2">Number of Questions</label>
<input 
type="number" 
min="1" 
max="20"
value={options.count}
onChange={e => setOptions({...options, count: parseInt(e.target.value)})}
className="w-full p-2 bg-[var(--bg-base)] border border-[var(--border)] rounded-[var(--radius)] text-[var(--text-primary)] outline-none focus:border-[var(--accent-purple)]"
/>
</div>
</div>

<button
onClick={handleGenerate}
className="w-full max-w-sm flex items-center justify-center gap-2 bg-[var(--accent-purple)] text-white py-3 rounded-[var(--radius)] font-bold hover:opacity-90 transition-all"
>
Generate Quiz
</button>
</div>
)
}

// Active Quiz View (One by One)
const allQuestions = mcq // focusing on MCQ for this smooth interactive UI
const q = allQuestions[currentQuestionIndex]
if (!q && sa.length === 0) return null

const answered = q ? mcqAnswers[q.id] !== undefined : false

const isCorrect = q
? answered && mcqAnswers[q.id] === q.answer
: false
const difficultyStyles: Record<string, string> = {
easy: 'bg-green-500/15 text-green-300',
medium: 'bg-amber-500/15 text-amber-300',
hard: 'bg-red-500/15 text-red-300',
}

if (!q) {
return (
<div className="flex flex-col gap-6 w-full max-w-2xl mx-auto py-6">
{sa.length > 0 && (
<div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] p-6 shadow-sm">
<h3 className="text-lg font-semibold text-[var(--text-primary)] mb-4">
Short Answer Practice
</h3>

<div className="space-y-5">
{sa.map(question => {
const result = gradingResults[question.id]

return (
<div
key={question.id}
className="border border-[var(--border)] rounded-[var(--radius)] p-4 bg-[var(--bg-base)]"
>
<p className="text-sm font-medium text-[var(--text-primary)] mb-3">
{question.question}
</p>

<textarea
value={shortAnswers[question.id] || ''}
onChange={e =>
setShortAnswers(prev => ({
...prev,
[question.id]: e.target.value
}))
}
className="w-full min-h-24 resize-y bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius)] p-3 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent-purple)]"
placeholder="Write your answer..."
/>

<button
onClick={() => handleGradeShortAnswer(question)}
disabled={
!shortAnswers[question.id]?.trim() ||
gradingQuestionId === question.id
}
className="mt-3 px-4 py-2 bg-[var(--accent-purple)] text-white rounded-[var(--radius)] text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
>
{gradingQuestionId === question.id
? 'Grading...'
: 'Grade Answer'}
</button>

{result && (
<div className="mt-4 p-4 rounded-[var(--radius)] bg-[var(--bg-elevated)] border border-[var(--border)]">
<p className="text-sm font-semibold text-[var(--text-primary)] mb-2">
Score: {result.score}/10
</p>

<p className="text-sm text-[var(--text-secondary)] leading-relaxed">
{result.feedback}
</p>
</div>
)}
</div>
)
})}
</div>
</div>
)}
</div>
)
}

return (
<div className="flex flex-col gap-6 w-full max-w-2xl mx-auto py-6">
<div className="flex justify-between items-center text-sm font-medium text-[var(--text-secondary)] mb-2">
<span>Question {currentQuestionIndex + 1} of {allQuestions.length}</span>
<span className="px-3 py-1 bg-[var(--bg-elevated)] rounded-full border border-[var(--border)]">
Score: {Object.keys(mcqAnswers).filter(k => {
const qObj = allQuestions.find(qq => qq.id === k);
return qObj && mcqAnswers[k] === qObj.answer;
}).length}/{allQuestions.length}
</span>
</div>

<div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] p-8 shadow-sm">
<div className="flex items-start justify-between gap-4 mb-8">
<h3 className="text-xl font-medium text-[var(--text-primary)] leading-relaxed">{q.question}</h3>
{q.difficulty && (
<span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${difficultyStyles[q.difficulty] ?? ''}`}>
{q.difficulty}
</span>
)}
</div>

<div className="space-y-3 mb-6">
{q.options.map((opt, i) => {
let btnClass = "w-full text-left p-4 rounded-[var(--radius)] border transition-all text-sm font-medium flex items-center "
if (!answered) {
btnClass += "border-[var(--border)] hover:border-[var(--accent-purple)] hover:bg-[var(--accent-purple-dim)] bg-[var(--bg-base)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
} else {
if (i === q.answer) {
btnClass += "border-[var(--success)] bg-[var(--success-dim)] text-[var(--success)]"
} else if (i === mcqAnswers[q.id]) {
btnClass += "border-[var(--danger)] bg-[var(--danger-dim)] text-[var(--danger)]"
} else {
btnClass += "border-[var(--border)] bg-[var(--bg-base)] text-[var(--text-muted)] opacity-50"
}
}

return (
<button
key={i}
disabled={answered}
onClick={() => setMcqAnswers(prev => ({ ...prev, [q.id]: i }))}
className={btnClass}
>
<span className="inline-flex flex-shrink-0 items-center justify-center w-7 h-7 rounded-full border border-current mr-4 text-xs opacity-70">
{String.fromCharCode(65 + i)}
</span>
<span>{opt}</span>
</button>
)
})}
</div>

{!answered && (
<div className="flex justify-end">
<button onClick={() => setShowHint(!showHint)} className="text-sm text-[var(--accent-purple)] hover:underline flex items-center gap-1">
<HelpCircle size={14} /> {showHint ? 'Hide Hint' : 'Show Hint'}
</button>
</div>
)}

{showHint && !answered && q.explanation && (
<div className="mt-4 p-4 text-sm bg-[var(--bg-elevated)] border border-[var(--border)] rounded-[var(--radius)] text-[var(--text-secondary)] italic border-l-4 border-l-[var(--accent-purple)]">
<span className="font-bold text-[var(--text-primary)] block mb-1">Hint:</span>
{q.explanation.split('.')[0]}.
</div>
)}

{answered && (
<div className={`mt-6 p-5 rounded-[var(--radius)] flex flex-col gap-4 text-sm border ${isCorrect ? 'bg-[var(--success-dim)] border-[var(--success)]' : 'bg-[var(--danger-dim)] border-[var(--danger)]'}`}>
<div className="flex items-start gap-3">
{isCorrect ? <CheckCircle2 size={24} className="shrink-0 text-[var(--success)]" /> : <XCircle size={24} className="shrink-0 text-[var(--danger)]" />}
<div>
<span className={`font-bold text-base ${isCorrect ? 'text-[var(--success)]' : 'text-[var(--danger)]'}`}>
{isCorrect ? 'Correct!' : 'Incorrect.'}
</span>
<p className="mt-2 text-[var(--text-primary)] leading-relaxed">{q.explanation}</p>
</div>
</div>

<button 
onClick={() => askDetailedExplanation(q)}
className="self-start mt-2 px-4 py-2 bg-[var(--bg-surface)] border border-[var(--border)] rounded text-[var(--text-secondary)] hover:text-[var(--accent-purple)] transition-colors flex items-center gap-2 shadow-sm"
>
<MessageSquare size={14} /> Ask Tutor for Detailed Explanation
</button>
</div>
)}
</div>

<div className="flex justify-end mt-4">
<button 
disabled={!answered || currentQuestionIndex === allQuestions.length - 1}
onClick={() => {
setCurrentQuestionIndex(prev => prev + 1)
setShowHint(false)
}}
className="px-6 py-3 bg-[var(--accent-purple)] text-white rounded-[var(--radius)] font-bold flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90 transition-opacity"
>
Next Question <ChevronRight size={18} />
</button>
</div>

{sa.length > 0 && (
<div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] p-6 shadow-sm">
<h3 className="text-lg font-semibold text-[var(--text-primary)] mb-4">Short Answer Practice</h3>
<div className="space-y-5">
{sa.map(question => {
const result = gradingResults[question.id]
return (
<div key={question.id} className="border border-[var(--border)] rounded-[var(--radius)] p-4 bg-[var(--bg-base)]">
<p className="text-sm font-medium text-[var(--text-primary)] mb-3">{question.question}</p>
<textarea
value={shortAnswers[question.id] || ''}
onChange={e => setShortAnswers(prev => ({ ...prev, [question.id]: e.target.value }))}
className="w-full min-h-24 resize-y bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius)] p-3 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent-purple)]"
placeholder="Write your answer..."
/>
<button
onClick={() => handleGradeShortAnswer(question)}
disabled={!shortAnswers[question.id]?.trim() || gradingQuestionId === question.id}
className="mt-3 px-4 py-2 bg-[var(--accent-purple)] text-white rounded-[var(--radius)] text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
>
{gradingQuestionId === question.id ? 'Grading...' : 'Grade Answer'}
</button>

{result && (
<div className="mt-4 p-4 rounded-[var(--radius)] bg-[var(--bg-elevated)] border border-[var(--border)]">
<div className="flex items-center justify-between gap-3 mb-2">
<p className="text-sm font-semibold text-[var(--text-primary)]">Score: {result.score}/10</p>
</div>
<p className="text-sm text-[var(--text-secondary)] leading-relaxed">{result.feedback}</p>
{result.study_tip && (
<div className="mt-3 p-3 rounded-lg bg-purple-500/10 border border-purple-500/20">
<p className="text-xs text-purple-300/80 font-medium mb-1">Study tip</p>
<p className="text-sm text-white/70">{result.study_tip}</p>
</div>
)}
</div>
)}
</div>
)
})}
</div>
</div>
)}
</div>
)
}
