-- =====================================================================================
-- 1. EXTENSIONS
-- =====================================================================================

-- Enable pgvector for vector embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- =====================================================================================
-- 2. APPLICATION TABLES (Translated exactly from SQLite)
-- =====================================================================================

-- We do NOT use Supabase Auth to preserve the current backend/frontend logic.
-- Therefore, users and auth_tokens remain standard application tables.

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL  -- Preserving TEXT to match exact SQLite format, though TIMESTAMPTZ is native
);
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS auth_tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);
ALTER TABLE auth_tokens ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    created_at TEXT NOT NULL,
    text TEXT NOT NULL,
    data TEXT NOT NULL,  -- Preserved as TEXT for exact JSON serialization compatibility
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
);
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS metacognitive_checkins (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    concept TEXT NOT NULL,
    confidence_rating INTEGER NOT NULL,
    reflection TEXT,
    created_at TEXT NOT NULL
);
ALTER TABLE metacognitive_checkins ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS progress (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
    quiz_attempts INTEGER DEFAULT 0,
    quiz_score_total INTEGER DEFAULT 0,
    flashcards_total INTEGER DEFAULT 0,
    flashcards_mastered INTEGER DEFAULT 0,
    updated_at TEXT
);
ALTER TABLE progress ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS learner_state (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    concept TEXT NOT NULL,
    mastery DOUBLE PRECISION DEFAULT 0.0,
    confidence DOUBLE PRECISION DEFAULT 0.5,
    attempts INTEGER DEFAULT 0,
    correct_attempts INTEGER DEFAULT 0,
    recent_score DOUBLE PRECISION DEFAULT 0.0,
    needs_examples INTEGER DEFAULT 0,
    needs_step_by_step INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL,
    last_reviewed_at TEXT,
    next_review_at TEXT,
    review_interval_days DOUBLE PRECISION DEFAULT 1.0,
    UNIQUE(session_id, concept)
);
ALTER TABLE learner_state ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS card_schedule (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    front TEXT NOT NULL,
    easiness DOUBLE PRECISION DEFAULT 2.5,
    interval INTEGER DEFAULT 1,
    repetitions INTEGER DEFAULT 0,
    next_review TEXT
);
ALTER TABLE card_schedule ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS learner_profiles (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
    learning_style TEXT DEFAULT 'adaptive',
    preferred_difficulty TEXT DEFAULT 'medium',
    strengths TEXT DEFAULT '[]', -- Preserved as TEXT for exact JSON serialization compatibility
    weaknesses TEXT DEFAULT '[]', -- Preserved as TEXT for exact JSON serialization compatibility
    updated_at TEXT
);
ALTER TABLE learner_profiles ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS misconceptions (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    concept TEXT NOT NULL,
    misconception TEXT NOT NULL,
    evidence TEXT,
    severity TEXT NOT NULL DEFAULT 'medium',
    suggested_intervention TEXT,
    occurrences INTEGER NOT NULL DEFAULT 1,
    resolved INTEGER NOT NULL DEFAULT 0,
    first_detected TEXT NOT NULL,
    last_detected TEXT NOT NULL
);
ALTER TABLE misconceptions ENABLE ROW LEVEL SECURITY;

-- =====================================================================================
-- 3. VECTOR DATABASE (SupabaseVectorStore 0.3.14 Compatible)
-- =====================================================================================

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT,
    metadata JSONB,
    embedding VECTOR(384) -- Fixed for sentence-transformers/all-MiniLM-L6-v2
);

-- =====================================================================================
-- 4. VECTOR MATCHING RPC (SupabaseVectorStore 0.3.14 Compatible)
-- =====================================================================================

-- This exact function signature and return type is required by Langchain 0.3.14.
-- The RPC enables similarity search pushed down to Postgres, with metadata filtering.

CREATE OR REPLACE FUNCTION match_documents (
    query_embedding VECTOR(384),
    match_count INT DEFAULT NULL,
    filter JSONB DEFAULT '{}'
) RETURNS TABLE (
    id UUID,
    content TEXT,
    metadata JSONB,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        documents.id,
        documents.content,
        documents.metadata,
        1 - (documents.embedding <=> query_embedding) AS similarity
    FROM documents
    WHERE documents.metadata @> filter
    ORDER BY documents.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- =====================================================================================
-- 5. STORAGE BUCKET
-- =====================================================================================

-- The 'uploads' bucket will store the PDF files uploaded by users.
-- Note: Supabase provides a dedicated Storage API for creating buckets programmatically.
-- The underlying SQL for bucket creation in Supabase looks like this:

INSERT INTO storage.buckets (id, name, public)
VALUES ('uploads', 'uploads', false)
ON CONFLICT (id) DO NOTHING;

-- =====================================================================================
-- 6. SECURITY & RLS
-- =====================================================================================

-- All application tables have ROW LEVEL SECURITY explicitly enabled.
-- No permissive anon policies are created. 
-- The backend relies on the Supabase service-role key which physically bypasses RLS.
