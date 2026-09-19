import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'sonner'
import { Dashboard } from './pages/Dashboard'
import { StudyChat } from './pages/StudyChat'
import { KnowledgeGraph } from './components/ui/knowledge-graph'
import { FlashcardDecks } from './components/ui/flashcard-decks'
import { QuizPanel } from './components/ui/quiz-panel'
import { useParams } from 'react-router-dom'

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
          style: { background: 'var(--bg-elevated)', borderColor: 'var(--border)', color: 'var(--text-primary)' } 
        }} 
      />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/chat/:sessionId" element={<StudyChat />} />
          <Route path="/graph/:sessionId" element={<GraphPage />} />
          <Route path="/flashcards/:sessionId" element={<FlashcardsPage />} />
          <Route path="/quiz/:sessionId" element={<QuizPage />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </BrowserRouter>
    </>
  )
}

export default App
