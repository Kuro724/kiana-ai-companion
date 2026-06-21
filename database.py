import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'kiana.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Long-term key/value memories
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS memories (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 2. Conversation history
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            message TEXT NOT NULL,
            emotional_state TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 3. Relationship profile
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS companion_profile (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    # 4. Session summaries (NEW)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS session_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            summary_text TEXT NOT NULL,
            message_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Default profile values
    cursor.execute("INSERT OR IGNORE INTO companion_profile (key, value) VALUES ('familiarity', '0')")
    cursor.execute("INSERT OR IGNORE INTO companion_profile (key, value) VALUES ('first_seen', ?)",
                   (datetime.now().isoformat(),))
    cursor.execute("INSERT OR IGNORE INTO companion_profile (key, value) VALUES ('interaction_count', '0')")

    conn.commit()
    conn.close()

# ── Conversations ─────────────────────────────────────────────────────────────

def save_message(sender, message, emotional_state=None):
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO conversations (sender, message, emotional_state) VALUES (?, ?, ?)",
        (sender, message, emotional_state)
    )
    conn.commit()
    conn.close()

def get_history(limit=15):
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT sender, message, emotional_state, timestamp FROM conversations ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]

# ── Memories ──────────────────────────────────────────────────────────────────

def save_memory(key, value):
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO memories (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
        (key.strip().lower(), value.strip())
    )
    conn.commit()
    conn.close()

def get_memories():
    conn = get_db_connection()
    rows = conn.execute("SELECT key, value FROM memories").fetchall()
    conn.close()
    return {r['key']: r['value'] for r in rows}

# ── Session Summaries ─────────────────────────────────────────────────────────

def save_session_summary(summary_text: str, message_count: int = 0):
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO session_summaries (summary_text, message_count) VALUES (?, ?)",
        (summary_text.strip(), message_count)
    )
    conn.commit()
    conn.close()

def get_session_summaries(limit: int = 3):
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, summary_text, message_count, created_at "
        "FROM session_summaries ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]

# ── Relationship Stats ────────────────────────────────────────────────────────

def get_relationship_stats():
    conn = get_db_connection()
    rows = conn.execute("SELECT key, value FROM companion_profile").fetchall()
    conn.close()
    stats = {r['key']: r['value'] for r in rows}
    stats['familiarity'] = int(stats.get('familiarity', 0))
    stats['interaction_count'] = int(stats.get('interaction_count', 0))
    return stats

def update_relationship_stats(familiarity_gain=1):
    conn = get_db_connection()

    conn.execute(
        "INSERT OR REPLACE INTO companion_profile (key, value) VALUES ('last_seen', ?)",
        (datetime.now().isoformat(),)
    )

    row = conn.execute("SELECT value FROM companion_profile WHERE key='interaction_count'").fetchone()
    interaction_count = int(row['value']) + 1 if row else 1
    conn.execute("INSERT OR REPLACE INTO companion_profile (key, value) VALUES ('interaction_count', ?)",
                 (str(interaction_count),))

    row = conn.execute("SELECT value FROM companion_profile WHERE key='familiarity'").fetchone()
    new_fam = (int(row['value']) if row else 0) + familiarity_gain
    conn.execute("INSERT OR REPLACE INTO companion_profile (key, value) VALUES ('familiarity', ?)",
                 (str(new_fam),))

    conn.commit()
    conn.close()
    return {"familiarity": new_fam, "interaction_count": interaction_count}

if __name__ == '__main__':
    init_db()
    print("Database initialised successfully.")
