import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileUploader } from '../components/ui/file-uploader'
import { getSessions, deleteSession } from '../lib/api'
import type { Session } from '../lib/api'
import { Ghost, Flame, FileText, Trash2, Loader2, Sparkles } from 'lucide-react'

export function Dashboard() {
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [streak] = useState(() => parseInt(localStorage.getItem('sb_streak') || '0', 10))

  useEffect(() => {
    // Load sessions
    getSessions()
      .then(data => {
        setSessions(data.sessions.slice(0, 5))
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    try {
      await deleteSession(id)
      setSessions(prev => prev.filter(s => s.id !== id))
    } catch (err) {
      console.error(err)
    }
  }

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)] flex flex-col items-center py-12 px-4 relative overflow-hidden">
      
      {/* Background decoration */}
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-[var(--accent-purple-dim)] blur-[120px] pointer-events-none opacity-50" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-[var(--accent-gold-dim)] blur-[120px] pointer-events-none opacity-30" />

      {/* Header */}
      <div className="flex flex-col items-center mb-12 relative z-10 text-center">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-12 h-12 bg-[var(--bg-elevated)] border border-[var(--border)] rounded-full flex items-center justify-center">
            <Ghost size={24} className="text-[var(--accent-purple)]" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight">Shadow<span className="text-[var(--accent-purple)]">Byte</span></h1>
        </div>
        <p className="text-[var(--text-secondary)] text-lg max-w-xl">
          Transform your study materials into interactive tutors, flashcards, and knowledge graphs.
        </p>
      </div>

      {/* Main Upload Zone */}
      <div className="w-full relative z-10 mb-16">
        <FileUploader onSuccess={(id) => navigate(`/chat/${id}`)} />
      </div>

      {/* Recent Sessions */}
      <div className="w-full max-w-4xl relative z-10">
        <div className="flex items-center justify-between mb-6 border-b border-[var(--border)] pb-4">
          <h2 className="text-xl font-bold flex items-center gap-2"><FileText size={20} className="text-[var(--accent-purple)]" /> Recent Study Sessions</h2>
          <div className="flex items-center gap-2 px-4 py-1.5 bg-[var(--accent-gold-dim)] border border-[var(--accent-gold)] rounded-full text-[var(--accent-gold)]">
             <Flame size={16} />
             <span className="font-bold text-sm">{streak} Day Streak</span>
          </div>
        </div>

        {loading ? (
          <div className="flex justify-center p-8"><Loader2 className="animate-spin text-[var(--text-secondary)]" /></div>
        ) : sessions.length === 0 ? (
          <div className="text-center p-12 border border-[var(--border)] border-dashed rounded-[var(--radius-lg)] bg-[var(--bg-surface)] text-[var(--text-secondary)]">
            <Sparkles size={32} className="mx-auto mb-4 opacity-50" />
            <p>Upload a file or paste a YouTube link to start your first session.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {sessions.map(s => (
              <div 
                key={s.id}
                onClick={() => navigate(`/chat/${s.id}`)}
                className="group bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] p-5 hover:border-[var(--accent-purple-border)] hover:bg-[var(--accent-purple-dim)] transition-all cursor-pointer relative"
              >
                <div className="pr-8">
                   <h3 className="font-medium text-[var(--text-primary)] truncate mb-1" title={s.title}>{s.title}</h3>
                   <div className="flex items-center gap-3 text-xs text-[var(--text-secondary)]">
                      <span>{new Date(s.created_at).toLocaleDateString()}</span>
                      <span>•</span>
                      <span>{s.chunk_count} chunks</span>
                   </div>
                </div>
                <button 
                  onClick={(e) => handleDelete(e, s.id)}
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
