import { useState, useEffect } from 'react'
import { getSessions, deleteSession, getProgress } from '../../lib/api'
import type { Session } from '../../lib/api'
import { Plus, Trash2, Loader2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

export function ChatSidebar({ activeSessionId }: { activeSessionId?: string }) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [progressBySession, setProgressBySession] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  const fetchSessions = () => {
    getSessions()
      .then(data => {
        setSessions(data.sessions)
        Promise.all(
          data.sessions.map(session =>
            getProgress(session.id)
              .then(progress => [session.id, progress.mastery_pct] as const)
              .catch(() => [session.id, 0] as const)
          )
        ).then(entries => {
          setProgressBySession(Object.fromEntries(entries))
        })
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }

  useEffect(() => {
    fetchSessions()
  }, [])

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    try {
      await deleteSession(id)
      setSessions(prev => prev.filter(s => s.id !== id))
      if (activeSessionId === id) {
        navigate('/')
      }
    } catch (err) {
      console.error(err)
    }
  }

  return (
    <div className="w-64 h-full bg-[var(--bg-base)] border-r border-[var(--border)] flex flex-col">
      <div className="p-4 border-b border-[var(--border)]">
        <button 
          onClick={() => navigate('/')}
          className="w-full flex items-center justify-center gap-2 bg-[var(--accent-purple)] text-white py-2 px-4 rounded-[var(--radius)] font-medium hover:opacity-90 transition-opacity"
        >
          <Plus size={16} /> New Study Session
        </button>
      </div>
      
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {loading ? (
          <div className="flex justify-center p-4"><Loader2 className="animate-spin text-[var(--text-secondary)]" size={20} /></div>
        ) : sessions.length === 0 ? (
          <p className="text-center text-xs text-[var(--text-muted)] p-4">No recent sessions</p>
        ) : (
          <>
            <div className="px-4 py-2 mt-4 mb-1 text-xs font-bold text-[var(--text-muted)] tracking-widest uppercase">
               Recent
            </div>
            {sessions.map((s, i) => {
              const dots = ['bg-purple-500', 'bg-teal-500', 'bg-blue-500', 'bg-pink-500', 'bg-amber-500'];
              const dotColor = dots[i % dots.length];
              
              return (
              <div 
                key={s.id}
                onClick={() => navigate(`/chat/${s.id}`)}
                className={`group flex items-center justify-between p-3 mx-2 rounded-[var(--radius)] cursor-pointer transition-colors
                  ${s.id === activeSessionId 
                    ? 'bg-[var(--accent-purple-dim)] border border-[var(--accent-purple-border)] text-white' 
                    : 'border border-transparent text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]'}
                `}
              >
                <div className="flex items-center gap-3 overflow-hidden">
                  <div className={`w-2.5 h-2.5 rounded-sm ${dotColor} shrink-0 opacity-80`} />
                  <div className="truncate">
                    <p className="text-sm font-medium truncate">{s.title}</p>
                    <p className="text-[11px] opacity-60 truncate mt-0.5">
                      {new Date(s.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                    </p>
                    <div className="mt-1.5 h-1 w-full bg-white/10 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-purple-400 rounded-full transition-all"
                        style={{ width: `${progressBySession[s.id] ?? 0}%` }}
                      />
                    </div>
                  </div>
                </div>
              <button 
                onClick={(e) => handleDelete(e, s.id)}
                className="opacity-0 group-hover:opacity-100 p-1.5 hover:bg-[var(--danger-dim)] hover:text-[var(--danger)] rounded-[var(--radius)] transition-all"
              >
                <Trash2 size={14} />
              </button>
            </div>
            )})}
          </>
        )}
      </div>
    </div>
  )
}
