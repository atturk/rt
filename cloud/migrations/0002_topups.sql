-- Ricariche extra: credito separato da quello dell'abbonamento, valido 12 mesi.
-- Il conteggio avviene a ogni evento (rinnovo, ricarica, scadenza, disdetta): si legge quanto è stato
-- speso dall'ultimo conteggio, si scala prima dal credito dell'abbonamento e poi dalle ricariche
-- (la più vicina alla scadenza per prima), poi il tetto della chiave diventa speso + credito residuo.
ALTER TABLE users ADD COLUMN sub_remaining_usd REAL NOT NULL DEFAULT 0;   -- credito abbonamento non ancora speso
ALTER TABLE users ADD COLUMN accounted_usage_usd REAL NOT NULL DEFAULT 0; -- spesa della chiave all'ultimo conteggio

CREATE TABLE topups (
  order_id TEXT PRIMARY KEY,           -- ordine Polar della ricarica
  user_id TEXT NOT NULL REFERENCES users(id),
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  amount_usd REAL NOT NULL,
  remaining_usd REAL NOT NULL
);
CREATE INDEX topups_user ON topups(user_id, expires_at);
