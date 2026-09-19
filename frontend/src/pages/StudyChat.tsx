import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ChatSidebar } from '../components/ui/chat-sidebar'
import { ChatInterface } from '../components/ui/bolt-style-chat'
import { SmartNotes } from '../components/ui/smart-notes'
import { QuizPanel } from '../components/ui/quiz-panel'
import { FlashcardDecks } from '../components/ui/flashcard-decks'
import { KnowledgeGraph } from '../components/ui/knowledge-graph'
import { FileText, Sparkles, Layers, Share2, Menu } from 'lucide-react'

export function StudyChat() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<'notes'|'quiz'|'flashcards'|'graph'>('notes')
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  if (!sessionId) {
    navigate('/')
    return null
  }

  const tabs = [
    { id: 'notes', label: 'Notes', icon: FileText },
    { id: 'quiz', label: 'Quiz', icon: Sparkles },
    { id: 'flashcards', label: 'Flashcards', icon: Layers },
    { id: 'graph', label: 'Mind Map', icon: Share2 },
  ] as const;

  return (
    <div className="flex h-screen bg-[var(--bg-base)] text-[var(--text-primary)] overflow-hidden">
      
      {/* Mobile Sidebar Overlay */}
      {mobileMenuOpen && (
        <div className="md:hidden fixed inset-0 z-50 bg-black/50" onClick={() => setMobileMenuOpen(false)}>
           <div className="w-64 h-full" onClick={e => e.stopPropagation()}>
             <ChatSidebar activeSessionId={sessionId} />
           </div>
        </div>
      )}

      {/* Desktop Sidebar */}
      <div className="hidden md:block">
        <ChatSidebar activeSessionId={sessionId} />
      </div>

      <div className="flex-1 flex flex-col h-full min-w-0">
        
        {/* Mobile Header */}
        <div className="md:hidden flex items-center justify-between p-4 border-b border-[var(--border)] bg-[var(--bg-elevated)] shrink-0">
           <button onClick={() => setMobileMenuOpen(true)} className="p-2 -ml-2 text-[var(--text-secondary)] hover:text-white">
             <Menu size={20} />
           </button>
           <div className="font-bold">Shadow<span className="text-[var(--accent-purple)]">Byte</span></div>
           <div className="w-8"></div>
        </div>

        {/* Main Content Area */}
        <div className="flex-1 flex flex-col lg:flex-row overflow-hidden p-4 gap-4">
          
          {/* Chat Column (Left) */}
          <div className="flex-1 flex flex-col h-full min-w-0">
            <ChatInterface sessionId={sessionId} />
          </div>

          {/* Tools Column (Right) */}
          <div className="flex-1 lg:max-w-[40%] flex flex-col h-full min-w-0 bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] overflow-hidden">
            
            {/* Tabs Header */}
            <div className="flex items-center gap-1 p-2 border-b border-[var(--border)] bg-[var(--bg-elevated)] shrink-0 overflow-x-auto scrollbar-hide">
              {tabs.map(tab => {
                const Icon = tab.icon;
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex items-center gap-2 px-4 py-2 rounded-[var(--radius)] text-sm font-medium transition-colors whitespace-nowrap
                      ${isActive 
                        ? 'bg-[var(--accent-purple-dim)] text-[var(--accent-purple)]' 
                        : 'text-[var(--text-secondary)] hover:bg-[var(--bg-base)] hover:text-[var(--text-primary)]'}
                    `}
                  >
                    <Icon size={16} />
                    {tab.label}
                  </button>
                )
              })}
            </div>

            {/* Tab Content */}
            <div className="flex-1 overflow-y-auto p-4 smooth-scroll">
              {activeTab === 'notes' && <SmartNotes sessionId={sessionId} />}
              {activeTab === 'quiz' && <QuizPanel sessionId={sessionId} />}
              {activeTab === 'flashcards' && <FlashcardDecks sessionId={sessionId} />}
              {activeTab === 'graph' && <div className="h-[600px] w-full"><KnowledgeGraph sessionId={sessionId} /></div>}
            </div>

          </div>
        </div>

      </div>
    </div>
  )
}
