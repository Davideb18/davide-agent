-- 1. TABELLA CONTATTI: Il nostro memory graph locale
CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    timezone TEXT NOT NULL DEFAULT 'Europe/Rome',
    created_at TEXT NOT NULL
);

-- 2. TABELLA SESSIONI: Lo storico delle chiamate e delle note vocali 
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    is_actionable INTEGER NOT NULL DEFAULT 1,
    intent_category TEXT NOT NULL,
    summary TEXT NOT NULL,
    raw_transcript TEXT NOT NULL,
    entities_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

-- 3. TABELLA AZIONI PROPOSTE: Gli eventi Calendar e le bozze Email 
CREATE TABLE IF NOT EXISTS proposed_actions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    status TEXT NOT NULL,
    calendar_data_json TEXT,
    email_data_json TEXT,
    knowledge_data_json TEXT,
    task_data_json TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 4. TABELLA AUDIT LOG: Traccia ogni singola modifica fatta dall'utente
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id TEXT NOT NULL REFERENCES proposed_actions(id) ON DELETE CASCADE,
    old_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    diff_payload_json TEXT,
    executed_at TEXT NOT NULL
);

-- INDICI PER PERFORMANCE FULMINEE
CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(first_name, last_name);
CREATE INDEX IF NOT EXISTS idx_actions_session ON proposed_actions(session_id);
CREATE INDEX IF NOT EXISTS idx_actions_idempotency ON proposed_actions(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action_id);
