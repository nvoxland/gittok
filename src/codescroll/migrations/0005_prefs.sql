-- Viewer preferences the client reads (GET /api/prefs) and the agent sets through MCP.
CREATE TABLE prefs (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
