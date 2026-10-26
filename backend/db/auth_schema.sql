-- Development schema source. Replit Publish applies its diff to production.
-- Never run this file from a production build command or application startup.
CREATE TABLE IF NOT EXISTS awi_local_users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    display_name TEXT NOT NULL,
    email TEXT NOT NULL,
    role TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    must_change_pw INTEGER NOT NULL DEFAULT 1 CHECK (must_change_pw IN (0, 1)),
    created_at TEXT NOT NULL,
    last_login TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS awi_users_username_ci ON awi_local_users (LOWER(username));
CREATE UNIQUE INDEX IF NOT EXISTS awi_users_email_ci ON awi_local_users (LOWER(email));
CREATE TABLE IF NOT EXISTS awi_login_attempts (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 0 CHECK (success IN (0, 1)),
    ip_address TEXT,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_username ON awi_login_attempts (LOWER(username), attempted_at);
CREATE TABLE IF NOT EXISTS awi_account_locks (
    username TEXT PRIMARY KEY,
    locked_at TEXT NOT NULL,
    locked_until TEXT NOT NULL,
    reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS awi_locks_username_ci ON awi_account_locks (LOWER(username));
CREATE TABLE IF NOT EXISTS awi_active_tokens (
    jti TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_type TEXT NOT NULL DEFAULT 'access',
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0, 1)),
    ip_address TEXT,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_active_tokens_user ON awi_active_tokens (user_id, revoked);
CREATE TABLE IF NOT EXISTS awi_security_audit (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    username TEXT,
    user_id TEXT,
    ip_address TEXT,
    user_agent TEXT,
    detail TEXT,
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_security_audit_type ON awi_security_audit (event_type, occurred_at);
