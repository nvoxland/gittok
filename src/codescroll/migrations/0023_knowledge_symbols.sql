-- What the reader already knows, per symbol (docs/learning.md section 14). Same counts as the
-- dir table `knowledge`; the symbol is the fact_defines.symbol of the repo's syntax facts.
CREATE TABLE knowledge_symbols (
    repo            TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    seen            INTEGER NOT NULL DEFAULT 0,
    explains_opened INTEGER NOT NULL DEFAULT 0,
    quiz_right      INTEGER NOT NULL DEFAULT 0,
    quiz_wrong      INTEGER NOT NULL DEFAULT 0,
    knew_it         INTEGER NOT NULL DEFAULT 0,
    teach_more      INTEGER NOT NULL DEFAULT 0,
    last_seen       INTEGER,
    PRIMARY KEY (repo, symbol)
);
