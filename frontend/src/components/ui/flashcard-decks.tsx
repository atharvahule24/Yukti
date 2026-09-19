import { useState, useEffect } from 'react'
import { getFlashcards, generateFlashcards, rateFlashcard, getFact } from '../../lib/api'
import type { Flashcard } from '../../lib/api'
import { Loader2, RotateCw, Check, X, SkipForward, BrainCircuit } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

export function FlashcardDecks({ sessionId }: { sessionId: string }) {
  const [cards, setCards] = useState<Flashcard[]>([])
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [fact, setFact] = useState<string>('')
  
  // Review State
  const [currentIndex, setCurrentIndex] = useState(0)
  const [isFlipped, setIsFlipped] = useState(false)
  const [correctCount, setCorrectCount] = useState(0)
  const [hintVisible, setHintVisible] = useState(false)

  useEffect(() => {
    if (!sessionId) return
    setLoading(true)
    getFlashcards(sessionId)
      .then(data => {
        setCards(data.cards || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [sessionId])

  useEffect(() => {
    setHintVisible(false)
  }, [currentIndex])

  const handleGenerate = async () => {
    if (!sessionId) return
    setGenerating(true)
    try {
      getFact(sessionId).then(res => setFact(res.fact)).catch(() => {})
      const data = await generateFlashcards(sessionId)
      setCards(data.cards || [])
      setCurrentIndex(0)
      setCorrectCount(0)
      setHintVisible(false)
    } catch (e) {
      console.error(e)
    } finally {
      setGenerating(false)
    }
  }

  const handleRate = async (mastery: number) => {
    if (!cards[currentIndex]) return
    
    if (mastery >= 2) {
      setCorrectCount(prev => prev + 1)
    }
    
    // Optimistically move to next card
    setIsFlipped(false)
    setHintVisible(false)
    
    // Let animation run
    setTimeout(() => {
      setCurrentIndex(prev => prev + 1)
    }, 150)
    
    try {
      await rateFlashcard(cards[currentIndex].id, sessionId, mastery)
    } catch (e) {
      console.error(e)
    }
  }

  const handleSkip = () => {
    setIsFlipped(false)
    setHintVisible(false)
    setTimeout(() => {
      setCurrentIndex(prev => prev + 1)
    }, 150)
  }

  if (loading) return <div className="flex justify-center p-8"><Loader2 className="animate-spin text-[var(--accent-purple)]" /></div>

  if (cards.length === 0) {
    if (generating) {
       return (
         <div className="flex flex-col items-center justify-center p-12 bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] text-center h-[500px]">
            <Loader2 className="animate-spin text-[var(--accent-purple)] mb-6" size={48} />
            <h3 className="text-xl font-bold mb-4 text-[var(--text-primary)]">Building Flashcard Deck...</h3>
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
      <div className="flex flex-col items-center justify-center p-8 bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] w-full h-[500px]">
        <h3 className="text-xl font-bold mb-4 text-[var(--text-primary)]">Flashcard Deck</h3>
        <p className="text-sm text-[var(--text-secondary)] mb-6 text-center max-w-sm">We'll generate a deck of about 20 intelligent flashcards to test your active recall on this material.</p>
        <button
          onClick={handleGenerate}
          className="w-full max-w-sm flex items-center justify-center gap-2 bg-[var(--accent-purple)] text-white py-3 rounded-[var(--radius)] font-bold hover:opacity-90 transition-all"
        >
          <BrainCircuit size={18} /> Generate Flashcards
        </button>
      </div>
    )
  }

  if (currentIndex >= cards.length) {
    return (
      <div className="flex flex-col items-center justify-center p-12 bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] text-center h-[500px]">
        <div className="w-20 h-20 bg-[var(--success-dim)] text-[var(--success)] rounded-full flex items-center justify-center mb-6">
          <Check size={40} />
        </div>
        <h3 className="text-2xl font-bold mb-2 text-[var(--text-primary)]">Deck Complete!</h3>
        <p className="text-[var(--text-secondary)] mb-8">You got {correctCount} out of {cards.length} correct.</p>
        <button
          onClick={() => {
            setCurrentIndex(0)
            setCorrectCount(0)
            setIsFlipped(false)
            setHintVisible(false)
          }}
          className="px-6 py-3 bg-[var(--accent-purple)] text-white rounded-[var(--radius)] font-bold hover:opacity-90 transition-all flex items-center gap-2"
        >
          <RotateCw size={18} /> Review Again
        </button>
      </div>
    )
  }

  const currentCard = cards[currentIndex]

  return (
    <div className="flex flex-col items-center w-full max-w-2xl mx-auto py-4">
      {/* Progress Header */}
      <div className="w-full flex justify-between items-center mb-6">
        <span className="text-sm font-medium text-[var(--text-secondary)]">Card {currentIndex + 1} of {cards.length}</span>
        <div className="flex items-center gap-4 text-sm">
           <span className="text-[var(--success)] font-medium flex items-center gap-1"><Check size={14} /> {correctCount} Correct</span>
           <button onClick={handleSkip} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] flex items-center gap-1 transition-colors">
              Skip <SkipForward size={14} />
           </button>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="w-full h-1 bg-[var(--bg-elevated)] rounded-full mb-8 overflow-hidden">
        <div 
          className="h-full bg-[var(--accent-purple)] transition-all duration-300"
          style={{ width: `${(currentIndex / cards.length) * 100}%` }}
        />
      </div>

      {/* Card Container */}
      <div className="relative w-full h-[350px] perspective-1000">
        <AnimatePresence mode="wait">
          <motion.div
            key={currentIndex + (isFlipped ? '-flipped' : '')}
            initial={{ opacity: 0, rotateX: isFlipped ? -90 : 90 }}
            animate={{ opacity: 1, rotateX: 0 }}
            exit={{ opacity: 0, rotateX: isFlipped ? 90 : -90 }}
            transition={{ duration: 0.3 }}
            className={`absolute inset-0 w-full h-full cursor-pointer bg-[var(--bg-surface)] border border-[var(--border)] rounded-2xl shadow-sm hover:border-[var(--accent-purple)] transition-colors flex flex-col`}
            onClick={() => !isFlipped && setIsFlipped(true)}
          >
            {!isFlipped ? (
              <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
                <span className="text-xs uppercase tracking-wider text-[var(--accent-purple)] font-bold mb-6">Question</span>
                <h3 className="text-2xl font-medium text-[var(--text-primary)] leading-tight">{currentCard.front}</h3>
                {currentCard.hint && (
                  <>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        setHintVisible(v => !v)
                      }}
                      className="text-xs text-purple-400/70 hover:text-purple-300 transition-colors mt-3"
                    >
                      {hintVisible ? 'Hide hint' : 'Show hint'}
                    </button>
                    {hintVisible && (
                      <p className="text-sm text-white/50 italic mt-1">{currentCard.hint}</p>
                    )}
                  </>
                )}
                <p className="mt-8 text-sm text-[var(--text-muted)] flex items-center gap-2">
                  <RotateCw size={14} /> Click to reveal answer
                </p>
              </div>
            ) : (
              <div className="flex-1 flex flex-col p-8">
                <div className="flex-1 flex flex-col items-center justify-center text-center">
                  <span className="text-xs uppercase tracking-wider text-[var(--success)] font-bold mb-4">Answer</span>
                  <h3 className="text-xl font-medium text-[var(--text-primary)] mb-4">{currentCard.back}</h3>
                  {currentCard.explanation && (
                    <div className="text-sm text-[var(--text-secondary)] bg-[var(--bg-elevated)] p-4 rounded-lg w-full">
                      {currentCard.explanation}
                    </div>
                  )}
                </div>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Controls */}
      <div className="w-full flex justify-center mt-8 h-14">
        {isFlipped && (
          <motion.div 
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex gap-4 w-full justify-center"
          >
            <button
              onClick={(e) => { e.stopPropagation(); handleRate(1); }}
              className="flex-1 max-w-[140px] flex items-center justify-center gap-2 bg-[var(--danger-dim)] text-[var(--danger)] border border-[var(--danger)] py-3 rounded-[var(--radius)] font-bold hover:bg-[var(--danger)] hover:text-white transition-all"
            >
              <X size={18} /> Incorrect
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); handleRate(3); }}
              className="flex-1 max-w-[140px] flex items-center justify-center gap-2 bg-[var(--success-dim)] text-[var(--success)] border border-[var(--success)] py-3 rounded-[var(--radius)] font-bold hover:bg-[var(--success)] hover:text-white transition-all"
            >
              <Check size={18} /> Correct
            </button>
          </motion.div>
        )}
      </div>
    </div>
  )
}
