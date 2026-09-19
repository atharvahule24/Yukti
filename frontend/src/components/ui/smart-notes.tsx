import { useState, useEffect } from 'react'
import { getNotes, generateNotes, getFact } from '../../lib/api'
import { Loader2, FileText, ChevronRight, X } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

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

  useEffect(() => {
    if (!sessionId) return
    setLoading(true)
    getNotes(sessionId)
      .then(data => {
        // Handle array or object wrapper
        const pts = Array.isArray(data) ? data : data.points || []
        setNotes(pts)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [sessionId])

  const handleGenerate = async () => {
    if (!sessionId) return
    setGenerating(true)
    try {
      getFact(sessionId).then(res => setFact(res.fact)).catch(() => {})
      const data = await generateNotes(sessionId)
      const pts = Array.isArray(data) ? data : data.points || []
      setNotes(pts)
    } catch (e) {
      console.error(e)
    } finally {
      setGenerating(false)
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
        <button
          onClick={handleGenerate}
          className="w-full max-w-sm flex items-center justify-center gap-2 bg-[var(--accent-purple)] text-white py-3 rounded-[var(--radius)] font-bold hover:opacity-90 transition-all"
        >
          <FileText size={18} /> Generate Notes
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
      <div className="grid grid-cols-2 gap-4 px-4 pb-4">
        {notes.map((note, idx) => {
          const colorClass = colors[idx % colors.length]
          return (
            <motion.div
              key={idx}
              whileHover={{ scale: 1.02 }}
              onClick={() => setSelectedNote(note)}
              className={`cursor-pointer ${colorClass} p-4 rounded-[var(--radius-lg)] shadow-sm hover:shadow-md transition-shadow aspect-square flex flex-col relative overflow-hidden`}
            >
              {/* AI Badge on specific cards to add contextual signal */}
              {idx % 3 === 2 && (
                <div className="absolute top-4 left-4 bg-[var(--bg-elevated)] bg-opacity-50 text-white text-[10px] px-2 py-0.5 rounded-full font-bold">
                  AI
                </div>
              )}
              
              <div className={`flex items-start justify-between gap-2 mb-2 ${idx % 3 === 2 ? 'mt-6' : ''}`}>
                <h4 className="font-bold text-lg leading-tight line-clamp-4">{note.bullet}</h4>
                {note.importance && (
                  <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${importanceStyles[note.importance] ?? importanceStyles.low}`}>
                    {note.importance}
                  </span>
                )}
              </div>
              <div className="flex-1" />
              <div className="flex items-center justify-between mt-auto border-t border-black/10 pt-2">
                <span className="text-xs opacity-70 font-medium">Click for details</span>
                <ChevronRight size={16} className="opacity-70" />
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
