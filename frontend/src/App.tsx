import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'sonner'
import { Dashboard } from './pages/Dashboard'
import { StudyChat } from './pages/StudyChat'
import { Auth } from './pages/Auth'
import { isAuthenticated } from './lib/auth'
import { KnowledgeGraph } from './components/ui/knowledge-graph'
import { FlashcardDecks } from './components/ui/flashcard-decks'
import { QuizPanel } from './components/ui/quiz-panel'
import { useParams } from 'react-router-dom'

function PrivateRoute({ children }: { children: React.ReactNode }) {
  return isAuthenticated() ? <>{children}</> : <Navigate to="/auth" />
}

// Wrapper components for standalone pages
function GraphPage() {
const { sessionId } = useParams<{ sessionId: string }>()
if (!sessionId) return <Navigate to="/" />
return (
<div className="h-screen bg-[var(--bg-base)] p-4 flex flex-col">
<h2 className="text-xl font-bold text-[var(--text-primary)] mb-4">Knowledge Graph</h2>
<div className="flex-1 rounded-[var(--radius-lg)] overflow-hidden border border-[var(--border)]">
<KnowledgeGraph sessionId={sessionId} />
</div>
</div>
)
}

function FlashcardsPage() {
const { sessionId } = useParams<{ sessionId: string }>()
if (!sessionId) return <Navigate to="/" />
return (
<div className="min-h-screen bg-[var(--bg-base)] p-4 flex flex-col items-center pt-12">
<h2 className="text-2xl font-bold text-[var(--text-primary)] mb-8">Flashcards Review</h2>
<FlashcardDecks sessionId={sessionId} />
</div>
)
}

function QuizPage() {
const { sessionId } = useParams<{ sessionId: string }>()
if (!sessionId) return <Navigate to="/" />
return (
<div className="min-h-screen bg-[var(--bg-base)] p-4 flex flex-col items-center pt-12">
<h2 className="text-2xl font-bold text-[var(--text-primary)] mb-8">Quiz</h2>
<div className="w-full max-w-3xl">
<QuizPanel sessionId={sessionId} />
</div>
</div>
)
}

function App() {

return (
<>
<Toaster
theme="dark"
position="bottom-right"
toastOptions={{
style: {
background: 'var(--bg-elevated)',
borderColor: 'var(--border)',
color: 'var(--text-primary)',
},
}}
/>

<BrowserRouter>
<Routes>
<Route path="/auth" element={<Auth />} />
<Route path="/" element={<PrivateRoute><Dashboard /></PrivateRoute>} />
<Route path="/chat/:sessionId" element={<PrivateRoute><StudyChat /></PrivateRoute>} />
<Route path="/graph/:sessionId" element={<PrivateRoute><GraphPage /></PrivateRoute>} />
<Route path="/flashcards/:sessionId" element={<PrivateRoute><FlashcardsPage /></PrivateRoute>} />
<Route path="/quiz/:sessionId" element={<PrivateRoute><QuizPage /></PrivateRoute>} />
<Route path="*" element={<Navigate to="/" />} />
</Routes>
</BrowserRouter>
</>
)
}

export default App