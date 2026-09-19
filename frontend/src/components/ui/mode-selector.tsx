export interface ModeSelectorProps {
  mode: string;
  onChange: (mode: 'socratic' | 'feynman' | 'simple' | 'exam') => void;
}

export function ModeSelector({ mode, onChange }: ModeSelectorProps) {
  const tabClass = (active: boolean) =>
    active
      ? 'whitespace-nowrap px-4 py-1.5 rounded-full text-sm text-purple-300 bg-purple-500/15 border border-purple-500/35 cursor-pointer'
      : 'whitespace-nowrap px-4 py-1.5 rounded-full text-sm text-white/40 border border-transparent hover:text-white/60 cursor-pointer transition-colors'

  const modes = [
    { id: 'socratic', label: 'Socratic', description: 'Guides with questions' },
    { id: 'feynman', label: 'Feynman', description: 'Learn by teaching' },
    { id: 'simple', label: 'Simple', description: 'Explain like I am 12' },
    { id: 'exam', label: 'Exam Prep', description: 'High-yield focus' },
  ] as const;

  return (
    <div className="flex flex-row gap-4 overflow-x-auto pb-2 scrollbar-hide w-full max-w-full">
      {modes.map((m) => {
        const isActive = mode === m.id;
        
        return (
          <button
            key={m.id}
            onClick={() => onChange(m.id)}
            title={m.description}
            className={tabClass(isActive)}
          >
            {m.label}
          </button>
        );
      })}
    </div>
  );
}
