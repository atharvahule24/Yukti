import { useState, useCallback } from 'react'
import { toast } from 'sonner'
import { streamChat } from '../lib/api'
import type { Citation } from '../lib/api'
import { v4 as uuidv4 } from 'uuid'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  error?: boolean
  citations?: Citation[]
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [currentMode, setCurrentMode] = useState<'socratic' | 'feynman' | 'simple' | 'exam'>('socratic')

  const sendMessage = useCallback((text: string, sessionId: string, mode: 'socratic' | 'feynman' | 'simple' | 'exam') => {
    if (!text.trim()) return

    const userMsgId = uuidv4()
    const astMsgId = uuidv4()

    setMessages(prev => [
      ...prev,
      { id: userMsgId, role: 'user', content: text },
      { id: astMsgId, role: 'assistant', content: '', streaming: true }
    ])

    setIsLoading(true)

    streamChat(
      text,
      sessionId,
      mode,
      (token) => {
        setMessages(prev => prev.map(msg => 
          msg.id === astMsgId 
            ? { ...msg, content: msg.content + token }
            : msg
        ))
      },
      () => {
        setMessages(prev => prev.map(msg => 
          msg.id === astMsgId 
            ? { ...msg, streaming: false }
            : msg
        ))
        setIsLoading(false)
      },
      (err) => {
        toast.error(err)
        setMessages(prev => prev.map(msg => 
          msg.id === astMsgId 
            ? { ...msg, error: true, streaming: false }
            : msg
        ))
        setIsLoading(false)
      },
      (citations) => {
        setMessages(prev => prev.map(msg =>
          msg.id === astMsgId
            ? { ...msg, citations }
            : msg
        ))
      }
    )
  }, [])

  return {
    messages,
    isLoading,
    currentMode,
    setCurrentMode,
    sendMessage,
    setMessages
  }
}
