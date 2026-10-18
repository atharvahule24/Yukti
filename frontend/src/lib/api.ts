import { getToken } from './auth';

export const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

export class TaskTerminalError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'TaskTerminalError'
  }
}

export function isTransientNetworkError(err: unknown): boolean {
  if (err instanceof TaskTerminalError) {
    return false
  }
  const status = (err as any)?.status
  if (status === 502 || status === 503 || status === 504) {
    return true
  }
  const message = String((err as any)?.message || '')
  if (
    message.includes('Failed to fetch') ||
    message.includes('NetworkError') ||
    message.includes('Load failed') ||
    message.includes('ECONNRESET') ||
    message.includes('Connection terminated')
  ) {
    return true
  }
  if ((err as any)?.name === 'TypeError') {
    return true
  }
  return false
}

async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init?.headers);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  const isIdempotent = !init?.method || init.method.toUpperCase() === 'GET' || init.method.toUpperCase() === 'HEAD';
  try {
    return await fetch(input, { ...init, headers });
  } catch (err: any) {
    if (isIdempotent && isTransientNetworkError(err)) {
      await new Promise(r => setTimeout(r, 600));
      return await fetch(input, { ...init, headers });
    }
    throw err;
  }
}
export interface Node {
  id: string;
  label: string;
  group?: string;
  [key: string]: unknown;
}

export interface Link {
  source: string;
  target: string;
  label?: string;
}

export interface Flashcard {
  id: string;
  front: string;
  back: string;
  explanation?: string;
  hint?: string;
  mastery: number;
  next_review: string;
}

export interface MCQ {
  id: string;
  question: string;
  options: string[];
  answer: number;
  difficulty?: 'easy' | 'medium' | 'hard' | string;
  explanation?: string;
}

export interface ShortAnswer {
  id: string;
  question: string;
  sample_answer: string;
  concept: string;
}

export interface QuizSubmission {
  score: number;
  percentage: number;
  correct_count: number;
  total_questions: number;
  answers: Record<string, number>;
  details?: Array<{
    id: string;
    user_answer: number | null;
    correct_answer: number;
    is_correct: boolean;
    concept: string;
  }>;
  submitted_at?: string;
  already_submitted?: boolean;
}

export interface LearningPath {
  action: string;
  reason: string;
  concept: string | null;
  mastery?: number;
  confidence?: number;
  difficulty: 'easy' | 'medium' | 'hard' | string;
  misconception?: string;
}

export interface GradeCriterion {
  criterion: string;
  max_points: number;
  awarded_points: number;
  status: 'fully_met' | 'partially_met' | 'missing' | string;
  evidence?: string;
}

export interface GradeResult {
  score: number;
  feedback: string;
  correct_concepts: string[];
  missed_concepts: string[];
  study_tip?: string;
  misconception?: string | null;
  learning_path?: LearningPath;
  criteria?: GradeCriterion[];
}

export interface Session {
  id: string;
  title: string;
  original_filename?: string;
  created_at: string;
  chunk_count: number;
  status?: string;
}

export interface NotePoint {
  bullet: string;
  explanation: string;
  example?: string;
  importance?: string;
}

export interface NotesResponse {
  points?: NotePoint[];
  key_points?: string[];
  summary?: string;
  real_world_examples?: string[];
}

export interface Citation {
  source_id?: number;
  text: string;
  page?: number | string | null;
  source?: string;
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = response.statusText;
    let ambiguous_delivery: boolean | undefined = undefined;
    let retry_after: number | undefined = undefined;
    try {
      const errorData = await response.json();
      message = errorData.message || errorData.error || message;
      if (typeof errorData.ambiguous_delivery === 'boolean') {
        ambiguous_delivery = errorData.ambiguous_delivery;
      }
      if (typeof errorData.retry_after === 'number') {
        retry_after = errorData.retry_after;
      }
    } catch {
      // Ignore json parse error
    }
    throw {
      error: 'api_error',
      status: response.status,
      message,
      ...(ambiguous_delivery !== undefined ? { ambiguous_delivery } : {}),
      ...(retry_after !== undefined ? { retry_after } : {}),
    };
  }
  return response.json();
}

export async function checkBackendHealth(): Promise<{
  status: string;
  version?: string;
  message?: string;
}> {
  const response = await apiFetch(`${BASE_URL}/health`);
  return handleResponse(response);
}

export async function uploadFile(file: File): Promise<{
  session_id?: string;
  title?: string;
  chunk_count?: number;
  task_id?: string;
}> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await apiFetch(`${BASE_URL}/upload`, {
    method: 'POST',
    body: formData,
  });

  return handleResponse(response);
}


export async function getTaskStatus(taskId: string): Promise<{
  state: string;
  result?: {
    status?: string
    session_id?: string
    chunk_count?: number
  };
  error?: string;
}> {
  let lastError: unknown
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const response = await apiFetch(`${BASE_URL}/task/${taskId}`)
      if ((response.status === 502 || response.status === 503 || response.status === 504) && attempt === 0) {
        await new Promise(r => setTimeout(r, 500))
        continue
      }
      return await handleResponse(response)
    } catch (err: any) {
      lastError = err
      if (isTransientNetworkError(err) && attempt === 0) {
        await new Promise(r => setTimeout(r, 500))
        continue
      }
      throw err
    }
  }
  throw lastError
}

export async function uploadYouTube(url: string): Promise<{
  task_id?: string;
  session_id?: string;
  title?: string;
  chunk_count?: number;
}> {
  const response = await apiFetch(`${BASE_URL}/upload`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ youtube_url: url }),
  });

  return handleResponse(response);
}

export function streamChat(
  message: string,
  sessionId: string,
  mode: 'socratic' | 'feynman' | 'simple' | 'exam',
  onToken: (token: string) => void,
  onDone: () => void,
  onError: (err: string) => void,
  onCitations?: (citations: Citation[]) => void
): void {
  const url = new URL(`${BASE_URL}/chat`, window.location.href)

  url.searchParams.append('message', message)
  url.searchParams.append('session_id', sessionId)
  url.searchParams.append('mode', mode)

  const token = getToken();
  if (token) {
    url.searchParams.append('token', token);
  }

  console.log('STREAM CHAT START')
  console.log('BASE_URL:', BASE_URL)
  console.log('CHAT URL:', url.toString())

  let eventSource: EventSource

  try {
    eventSource = new EventSource(url.toString())
    console.log('EVENTSOURCE CREATED')
  } catch (error) {
    console.error('EVENTSOURCE CREATION FAILED:', error)
    onError('Failed to create chat connection')
    return
  }

  eventSource.onopen = () => {
    console.log('EVENTSOURCE OPENED')
  }

  eventSource.onmessage = (event) => {
    console.log('SSE MESSAGE:', event.data)

    try {
      const data = JSON.parse(event.data)

      if (data.error) {
        console.error('SSE ERROR:', data.error)
        onError(data.error)
        eventSource.close()
        return
      }

      if (data.done) {
        console.log('SSE DONE')
        onDone()
        eventSource.close()
      } else if (data.token) {
        onToken(data.token)
      }
    } catch (error) {
      console.error('SSE PARSE ERROR:', error)
      onError('Failed to parse SSE data')
      eventSource.close()
    }
  }

  eventSource.onerror = (error) => {
    console.error('EVENTSOURCE ERROR:', error)
    onError('Connection lost')
    eventSource.close()
  }

  eventSource.addEventListener('citations', (event) => {
    console.log(
  'SSE CITATIONS DATA:',
  (event as MessageEvent).data
)

    try {
      onCitations?.(JSON.parse((event as MessageEvent).data))
    } catch {
      onCitations?.([])
    }
  })
}

export async function getChatHistory(sessionId: string): Promise<{
  messages: Array<{
    id: string
    role: 'user' | 'assistant'
    content: string
  }>
}> {
  const response = await apiFetch(`${BASE_URL}/chat/history/${sessionId}`)
  return handleResponse(response)
}

export async function getGraph(sessionId: string): Promise<{nodes: Node[], links: Link[]}> {
  const response = await apiFetch(`${BASE_URL}/graph/${sessionId}`);
  return handleResponse(response);
}

export async function generateGraph(sessionId: string, force = false): Promise<{nodes: Node[], links: Link[], task_id?: string, status?: string}> {
  const response = await apiFetch(`${BASE_URL}/graph/generate/${sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ force })
  });
  return handleResponse(response);
}

export async function getFlashcards(sessionId: string): Promise<{cards: Flashcard[]}> {
  const response = await apiFetch(`${BASE_URL}/flashcards/${sessionId}`);
  return handleResponse(response);
}

export async function generateFlashcards(sessionId: string): Promise<{cards: Flashcard[]}> {
  const response = await apiFetch(`${BASE_URL}/flashcards/generate/${sessionId}`, { method: 'POST' });
  return handleResponse(response);
}

export async function rateFlashcard(cardId: string, sessionId: string, mastery: number): Promise<{next_review: string}> {
  const response = await apiFetch(`${BASE_URL}/flashcards/rate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ card_id: cardId, session_id: sessionId, mastery }),
  });
  return handleResponse(response);
}

export async function getQuiz(sessionId: string): Promise<{mcq: MCQ[], short_answer: ShortAnswer[], submission?: QuizSubmission}> {
  const response = await apiFetch(`${BASE_URL}/quiz/${sessionId}`);
  return handleResponse(response);
}

export async function submitQuiz(sessionId: string, answers: Record<string, number>): Promise<QuizSubmission> {
  const response = await apiFetch(`${BASE_URL}/quiz/submit/${sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ answers }),
  });
  return handleResponse(response);
}

export async function generateQuiz(sessionId: string, options: { difficulty: string, count: number }): Promise<{mcq: MCQ[], short_answer: ShortAnswer[]}> {
  const response = await apiFetch(`${BASE_URL}/quiz/generate/${sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options),
  });
  return handleResponse(response);
}

export async function generateReassessment(
  sessionId: string,
  concept: string
): Promise<ShortAnswer> {
  const response = await apiFetch(`${BASE_URL}/quiz/reassess/${sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ concept }),
  });

  return handleResponse(response);
}

export async function gradeAnswer(question: string, userAnswer: string, sampleAnswer: string, sessionId?: string, concept?: string, confidenceRating?: number, isReassessment?: boolean): Promise<GradeResult> {  const response = await apiFetch(`${BASE_URL}/quiz/grade`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
body: JSON.stringify({ question, user_answer: userAnswer, sample_answer: sampleAnswer, session_id: sessionId, concept, confidence_rating: confidenceRating, is_reassessment: isReassessment }),  });
  return handleResponse(response);
}



export async function gradeInterventionAnswer(
  sessionId: string,
  concept: string,
  question: string,
  userAnswer: string,
): Promise<GradeResult & {
  resolved?: boolean
  misconception?: string | null
}> {
  const response = await apiFetch(`${BASE_URL}/quiz/intervention-grade`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      session_id: sessionId,
      concept,
      question,
      user_answer: userAnswer,
    }),
  })

  return handleResponse(response)
}

export async function recordMetacognitiveCheckin(
  sessionId: string,
  concept: string,
  confidenceRating: number
): Promise<{ learning_path: LearningPath }> {
  const response = await apiFetch(`${BASE_URL}/quiz/metacognitive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      concept,
      confidence_rating: confidenceRating,
    }),
  });

  return handleResponse(response);
}

export async function getNotes(sessionId: string): Promise<NotesResponse> {
  const response = await apiFetch(`${BASE_URL}/notes/${sessionId}`);
  return handleResponse(response);
}

export async function generateNotes(sessionId: string): Promise<{
  task_id: string
  status: string
}> {
  const response = await apiFetch(`${BASE_URL}/notes/generate/${sessionId}`, {
    method: 'POST',
  })

  return handleResponse(response)
}

export async function getSessions(): Promise<{sessions: Session[]}> {
  const response = await apiFetch(`${BASE_URL}/sessions`);
  return handleResponse(response);
}

export interface LearnerAnalytics {
  overall_mastery: number
  average_confidence: number
  total_concepts: number
  mastered_concepts: number
  weak_concepts: number
  due_reviews: number
  active_misconceptions: number
  resolved_misconceptions: number

  concepts: Array<{
    concept: string
    mastery: number
    confidence: number
    attempts: number
    correct_attempts: number
    recent_score: number
    needs_examples: number
    needs_step_by_step: number
    next_review_at: string | null
    review_interval_days?: number
  }>

  weak_concept_details: Array<{
    concept: string
    mastery: number
    confidence: number
  }>

  due_review_details: Array<{
    concept: string
    mastery: number
    confidence: number
    next_review_at: string | null
  }>

  misconceptions: Array<{
    id: number
    concept: string
    misconception: string
    severity: string
    occurrences: number
    resolved: number
    suggested_intervention: string | null
  }>
}

export async function getLearnerAnalytics(
  sessionId: string
): Promise<LearnerAnalytics> {
  const response = await apiFetch(
    `${BASE_URL}/learner/analytics/${sessionId}`
  )

  return handleResponse(response)
}

export async function getCumulativeLearnerAnalytics(): Promise<LearnerAnalytics> {
  const response = await apiFetch(
    `${BASE_URL}/learner/analytics/me`
  )

  return handleResponse(response)
}

export interface NextLearningAction {
  learning_path: {
    action: string
    reason: string
    concept?: string | null
    mastery?: number
    confidence?: number
    difficulty?: string
    next_review_at?: string | null
    review_interval_days?: number
  }

  question_plan: {
    concept?: string | null
    difficulty: string
    target: string
    question_type: string
    reason: string
    misconception?: string
    severity?: string
    suggested_intervention?: string | null
  }

  next_action: string
  concept?: string | null
  difficulty: string
  question_type: string
  reason: string
}


export async function getNextLearningAction(
  sessionId: string
): Promise<NextLearningAction> {
  const response = await apiFetch(
    `${BASE_URL}/learner/next-action/${sessionId}`
  )

  return handleResponse(response)
}

export async function deleteSession(sessionId: string): Promise<{deleted: boolean}> {
  const response = await apiFetch(`${BASE_URL}/sessions/${sessionId}`, {
    method: 'DELETE',
  });
  return handleResponse(response);
}

export async function getFact(sessionId: string): Promise<{ fact: string }> {
  const res = await apiFetch(`${BASE_URL}/fact/${sessionId}`)
  if (!res.ok) throw new Error('Failed to fetch fact')
  return res.json()
}

export async function getProgress(sessionId: string): Promise<{ quiz_avg: number, mastery_pct: number }> {
  const response = await apiFetch(`${BASE_URL}/progress/${sessionId}`);
  return handleResponse(response);
}

export interface VideoRecommendation {
  type: string
  query: string
  url: string
  concept: string
  difficulty: string
  action: string
  topic?: string
  base_concept?: string
}

export interface VideoRecommendationParams {
  concept?: string
  question?: string
  feedback?: string
  study_tip?: string
}

export async function getVideoRecommendation(
  sessionId: string,
  params?: VideoRecommendationParams
): Promise<{
  learning_path: any
  video: VideoRecommendation
}> {
  const queryParams = new URLSearchParams()
  if (params?.concept) queryParams.set('concept', params.concept)
  if (params?.question) queryParams.set('question', params.question)
  if (params?.feedback) queryParams.set('feedback', params.feedback)
  if (params?.study_tip) queryParams.set('study_tip', params.study_tip)

  const queryString = queryParams.toString()
  const url = `${BASE_URL}/learner/video-recommendation/${sessionId}${
    queryString ? `?${queryString}` : ''
  }`

  const response = await apiFetch(url)

  return handleResponse(response)
}

export async function sendOtp(
  target: string,
  type: 'email' | 'phone'
): Promise<{ success: boolean; message: string; retry_after?: number; expires_in?: number; ambiguous_delivery?: boolean }> {
  const response = await fetch(`${BASE_URL}/auth/otp/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target, type }),
  })
  return handleResponse(response)
}

export async function verifyOtp(
  target: string,
  type: 'email' | 'phone',
  otp: string
): Promise<{ success: boolean; token: string; user: { id: number; username: string } }> {
  const response = await fetch(`${BASE_URL}/auth/otp/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target, type, otp }),
  })
  return handleResponse(response)
}

export async function requestPasswordReset(
  email: string
): Promise<{ success: boolean; message: string; retry_after?: number }> {
  const response = await fetch(`${BASE_URL}/auth/password-reset/request`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  return handleResponse(response)
}

export async function verifyPasswordResetOtp(
  email: string,
  otp: string
): Promise<{ success: boolean; message: string; reset_token: string }> {
  const response = await fetch(`${BASE_URL}/auth/password-reset/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, otp }),
  })
  return handleResponse(response)
}

export async function confirmPasswordReset(
  reset_token: string,
  new_password: string,
  confirm_password: string
): Promise<{ success: boolean; message: string }> {
  const response = await fetch(`${BASE_URL}/auth/password-reset/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reset_token, new_password, confirm_password }),
  })
  return handleResponse(response)
}

export async function requestUsernameRecovery(
  email: string
): Promise<{ success: boolean; message: string; retry_after?: number }> {
  const response = await fetch(`${BASE_URL}/auth/username-recovery/request`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  return handleResponse(response)
}

export async function verifyUsernameRecoveryOtp(
  email: string,
  otp: string
): Promise<{ success: boolean; username: string; message: string }> {
  const response = await fetch(`${BASE_URL}/auth/username-recovery/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, otp }),
  })
  return handleResponse(response)
}
