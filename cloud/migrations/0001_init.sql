-- Nessun contenuto delle lezioni viene mai salvato qui: solo account, abbonamento e chiave.
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL,
  polar_customer_id TEXT,
  subscription_id TEXT,
  subscription_status TEXT,          -- active, canceled (finisce a fine periodo), revoked
  plan_id TEXT,
  current_period_end TEXT,
  or_key_hash TEXT,                  -- hash pubblico della chiave OpenRouter
  or_key_enc TEXT,                   -- chiave OpenRouter cifrata (AES-GCM)
  monthly_quota_usd REAL NOT NULL DEFAULT 0
);

CREATE TABLE login_codes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  used INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX login_codes_email ON login_codes(email, created_at);

CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  created_at INTEGER NOT NULL,
  last_used_at INTEGER NOT NULL
);

-- Ogni pagamento ricevuto: serve per l'idempotenza e per vedere i margini reali.
CREATE TABLE orders (
  order_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  created_at INTEGER NOT NULL,
  total_cents INTEGER NOT NULL,
  tax_cents INTEGER NOT NULL,
  currency TEXT NOT NULL,
  quota_usd REAL NOT NULL,
  usage_before_usd REAL NOT NULL
);

CREATE TABLE webhook_events (
  webhook_id TEXT PRIMARY KEY,
  received_at INTEGER NOT NULL
);
