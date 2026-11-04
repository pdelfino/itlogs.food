-- The landing page's waitlist (#24).
CREATE TABLE IF NOT EXISTS waitlist (
  email TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL
);
