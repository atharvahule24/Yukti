import { useState, useRef } from 'react'
import { UploadCloud, Video as Youtube, File as FileIcon, X } from 'lucide-react'
import { uploadFile, uploadYouTube } from '../../lib/api'
import { toast } from 'sonner'
import { motion } from 'framer-motion'

export function FileUploader({ onSuccess }: { onSuccess: (sessionId: string) => void }) {
  const [tab, setTab] = useState<'file'|'youtube'>('file')
  const [file, setFile] = useState<File | null>(null)
  const [youtubeUrl, setYoutubeUrl] = useState('')
  const [isDragging, setIsDragging] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setIsDragging(true)
    } else if (e.type === 'dragleave') {
      setIsDragging(false)
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const droppedFile = e.dataTransfer.files[0]
      validateAndSetFile(droppedFile)
    }
  }

  const validateAndSetFile = (f: File) => {
    const validTypes = ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain', 'application/vnd.openxmlformats-officedocument.presentationml.presentation']
    if (!validTypes.includes(f.type) && !f.name.match(/\.(pdf|docx|txt|pptx)$/i)) {
      toast.error('Invalid file type. Only PDF, DOCX, TXT, PPTX allowed.')
      return
    }
    if (f.size > 50 * 1024 * 1024) {
      toast.error('File size exceeds 50MB limit.')
      return
    }
    setFile(f)
  }

  const simulateProgress = () => {
    setProgress(0)
    const interval = setInterval(() => {
      setProgress(p => {
        if (p >= 90) {
          clearInterval(interval)
          return 90
        }
        return p + 10
      })
    }, 500)
    return interval
  }

  const handleUpload = async () => {
    if (tab === 'file' && !file) return
    if (tab === 'youtube' && !youtubeUrl) return

    setIsUploading(true)
    const progInt = simulateProgress()
    
    try {
      let res
      if (tab === 'file') {
        res = await uploadFile(file!)
      } else {
        res = await uploadYouTube(youtubeUrl)
      }
      clearInterval(progInt)
      setProgress(100)
      toast.success('Ready to study!')
      
      setTimeout(() => onSuccess(res.session_id), 500)
    } catch (err: unknown) {
      clearInterval(progInt)
      setProgress(0)
      const message = err instanceof Error ? err.message : 'Upload failed'
      toast.error(message)
      setIsUploading(false)
    }
  }

  return (
    <div className="w-full max-w-2xl mx-auto rounded-[var(--radius-lg)] bg-[var(--bg-surface)] border border-[var(--border)] overflow-hidden">
      
      {/* Tabs */}
      <div className="flex border-b border-[var(--border)]">
        <button
          onClick={() => setTab('file')}
          className={`flex-1 py-4 flex items-center justify-center gap-2 text-sm font-medium transition-colors
            ${tab === 'file' ? 'bg-[var(--accent-purple-dim)] text-[var(--accent-purple)] border-b-2 border-[var(--accent-purple)]' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)]'}
          `}
        >
          <UploadCloud size={18} /> Upload File
        </button>
        <button
          onClick={() => setTab('youtube')}
          className={`flex-1 py-4 flex items-center justify-center gap-2 text-sm font-medium transition-colors
            ${tab === 'youtube' ? 'bg-[var(--accent-purple-dim)] text-[var(--accent-purple)] border-b-2 border-[var(--accent-purple)]' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)]'}
          `}
        >
          <Youtube size={18} /> YouTube URL
        </button>
      </div>

      <div className="p-8">
        {tab === 'file' && (
          <div
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            className={`border-2 border-dashed rounded-[var(--radius)] p-12 text-center transition-colors cursor-pointer
              ${isDragging ? 'border-[var(--accent-purple)] bg-[var(--accent-purple-dim)]' : 'border-[var(--border)] bg-[var(--bg-elevated)] hover:border-[var(--border-hover)]'}
            `}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              type="file"
              ref={fileInputRef}
              className="hidden"
              accept=".pdf,.docx,.txt,.pptx"
              onChange={(e) => {
                if (e.target.files && e.target.files[0]) {
                  validateAndSetFile(e.target.files[0])
                }
              }}
            />
            
            {file ? (
              <div className="flex flex-col items-center gap-3">
                <FileIcon size={48} className="text-[var(--accent-purple)]" />
                <p className="text-[var(--text-primary)] font-medium">{file.name}</p>
                <p className="text-[var(--text-secondary)] text-sm">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                <button 
                  onClick={(e) => { e.stopPropagation(); setFile(null) }}
                  className="mt-2 p-2 rounded-full hover:bg-[var(--danger-dim)] text-[var(--danger)] transition-colors"
                >
                  <X size={20} />
                </button>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-4">
                <div className="w-16 h-16 rounded-full bg-[var(--bg-surface)] border border-[var(--border)] flex items-center justify-center">
                  <UploadCloud size={24} className="text-[var(--accent-purple)]" />
                </div>
                <div>
                  <p className="text-[var(--text-primary)] font-medium text-lg">Click or drag file to this area to upload</p>
                  <p className="text-[var(--text-secondary)] text-sm mt-1">Support for a single or bulk upload. Strictly prohibited from uploading company data or other banned files.</p>
                </div>
                <div className="flex gap-4 mt-2">
                   <span className="px-3 py-1 rounded-full bg-[var(--bg-surface)] border border-[var(--border)] text-[var(--text-muted)] text-xs">PDF</span>
                   <span className="px-3 py-1 rounded-full bg-[var(--bg-surface)] border border-[var(--border)] text-[var(--text-muted)] text-xs">DOCX</span>
                   <span className="px-3 py-1 rounded-full bg-[var(--bg-surface)] border border-[var(--border)] text-[var(--text-muted)] text-xs">TXT</span>
                </div>
              </div>
            )}
          </div>
        )}

        {tab === 'youtube' && (
          <div className="flex flex-col gap-4 py-8">
             <div className="flex flex-col items-center gap-4 text-center mb-4">
                <div className="w-16 h-16 rounded-full bg-[var(--bg-surface)] border border-[var(--border)] flex items-center justify-center">
                  <Youtube size={24} className="text-[var(--danger)]" />
                </div>
                <div>
                  <p className="text-[var(--text-primary)] font-medium text-lg">Import from YouTube</p>
                  <p className="text-[var(--text-secondary)] text-sm mt-1">Paste a YouTube URL to automatically transcribe and study from the video.</p>
                </div>
             </div>
             <input
               type="text"
               value={youtubeUrl}
               onChange={(e) => setYoutubeUrl(e.target.value)}
               placeholder="https://youtube.com/watch?v=..."
               className="w-full bg-[var(--bg-elevated)] border border-[var(--border)] text-[var(--text-primary)] rounded-[var(--radius)] p-4 outline-none focus:border-[var(--accent-purple)] transition-colors"
             />
          </div>
        )}

        {/* Action Area */}
        <div className="mt-8 flex flex-col gap-4">
           {isUploading && (
             <div className="w-full h-2 bg-[var(--bg-elevated)] rounded-full overflow-hidden">
               <motion.div 
                 className="h-full bg-[var(--accent-purple)]"
                 initial={{ width: 0 }}
                 animate={{ width: `${progress}%` }}
               />
             </div>
           )}
           <button
             onClick={handleUpload}
             disabled={isUploading || (tab === 'file' && !file) || (tab === 'youtube' && !youtubeUrl)}
             className={`w-full py-3 rounded-[var(--radius)] font-medium transition-colors
               ${isUploading || (tab === 'file' && !file) || (tab === 'youtube' && !youtubeUrl)
                 ? 'bg-[var(--bg-elevated)] text-[var(--text-muted)] cursor-not-allowed'
                 : 'bg-[var(--accent-purple)] text-white hover:opacity-90'}
             `}
           >
             {isUploading ? 'Processing...' : 'Start Studying'}
           </button>
        </div>
      </div>
    </div>
  )
}
