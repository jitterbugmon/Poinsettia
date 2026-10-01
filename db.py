import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'poinsettia.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT    UNIQUE NOT NULL,
            password_hash   TEXT    NOT NULL,
            age_confirmed   INTEGER NOT NULL DEFAULT 0,
            eula_reviewed   INTEGER NOT NULL DEFAULT 0,
            eula_agreed     INTEGER NOT NULL DEFAULT 0,
            eula_version    TEXT,
            consented_at    TEXT,
            privacy_agreed  INTEGER NOT NULL DEFAULT 0,
            privacy_version TEXT,
            privacy_consented_at TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            mode       TEXT    NOT NULL DEFAULT 'p2',
            title      TEXT    NOT NULL DEFAULT 'New chat',
            pinned     INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role            TEXT    NOT NULL,
            content         TEXT    NOT NULL,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS files (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            session_key TEXT,
            name        TEXT    NOT NULL,
            mime_type   TEXT    NOT NULL,
            path        TEXT    NOT NULL,
            size        INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_files_user    ON files(user_id);
        CREATE INDEX IF NOT EXISTS idx_files_session ON files(session_key);
        CREATE INDEX IF NOT EXISTS idx_conv_user_mode ON conversations(user_id, mode);
        CREATE INDEX IF NOT EXISTS idx_messages_conv  ON messages(conversation_id);
    ''')

    # Migrate databases created before consent tracking was introduced.
    existing_user_columns = {
        row[1] for row in c.execute("PRAGMA table_info(users)").fetchall()
    }
    consent_columns = {
        'age_confirmed': 'INTEGER NOT NULL DEFAULT 0',
        'eula_reviewed': 'INTEGER NOT NULL DEFAULT 0',
        'eula_agreed': 'INTEGER NOT NULL DEFAULT 0',
        'eula_version': 'TEXT',
        'consented_at': 'TEXT',
        'privacy_agreed': 'INTEGER NOT NULL DEFAULT 0',
        'privacy_version': 'TEXT',
        'privacy_consented_at': 'TEXT',
    }
    for column, definition in consent_columns.items():
        if column not in existing_user_columns:
            c.execute(f'ALTER TABLE users ADD COLUMN {column} {definition}')

    existing_conversation_columns = {
        row[1] for row in c.execute("PRAGMA table_info(conversations)").fetchall()
    }
    conversation_columns = {
        'title': "TEXT NOT NULL DEFAULT 'New chat'",
        'pinned': 'INTEGER NOT NULL DEFAULT 0',
        # SQLite does not allow ALTER TABLE ... ADD COLUMN with a
        # non-constant CURRENT_TIMESTAMP default.
        'created_at': 'TEXT',
    }
    for column, definition in conversation_columns.items():
        if column not in existing_conversation_columns:
            c.execute(f'ALTER TABLE conversations ADD COLUMN {column} {definition}')

    c.execute(
        'UPDATE conversations SET created_at = COALESCE(created_at, updated_at, CURRENT_TIMESTAMP)'
    )

    # Give legacy conversations a useful title without changing any messages.
    c.execute(
        '''UPDATE conversations
           SET title = trim(substr(replace(replace((
               SELECT content FROM messages
               WHERE messages.conversation_id = conversations.id
                 AND messages.role = 'user'
               ORDER BY messages.id ASC LIMIT 1
           ), char(10), ' '), char(13), ' '), 1, 80))
           WHERE (title IS NULL OR title = 'New chat')
             AND EXISTS (
                 SELECT 1 FROM messages
                 WHERE messages.conversation_id = conversations.id
                   AND messages.role = 'user'
             )'''
    )

    c.execute(
        'CREATE INDEX IF NOT EXISTS idx_conv_user_list ON conversations(user_id, pinned, updated_at)'
    )

    conn.commit()
    conn.close()
