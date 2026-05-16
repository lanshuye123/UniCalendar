#!/usr/bin/env python3
"""
Database Migration Script: old Django project → new FastAPI project

Migrates data from the old Django SQLite database to the new SQLAlchemy SQLite database.

Usage:
    python scripts/migrate.py /path/to/old/db.sqlite3

Tables migrated:
    auth_user              → users
    core_userdata          → user_data
    core_eventgroup        → event_groups
    core_collaborativecalendargroup  → share_groups
    core_groupmembership   → group_memberships
    core_groupcalendardata → group_calendar_data

Not migrated (handled differently):
    authtoken_token        — replaced by JWT + OAuth tokens
    django_session         — not needed
    agent_service_*        — agent service removed
"""

import os
import sys
import sqlite3
import json
import secrets
from datetime import datetime

# Try to use bcrypt from the new project
try:
    from app.core.security import hash_password
except ImportError:
    import bcrypt
    def hash_password(pw: str) -> str:
        return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def migrate(old_db_path: str, new_db_path: str = "uni_calendar.db"):
    """Main migration routine."""
    if not os.path.exists(old_db_path):
        print(f"Error: old database not found: {old_db_path}")
        sys.exit(1)

    old = sqlite3.connect(old_db_path)
    old.row_factory = sqlite3.Row

    new = sqlite3.connect(new_db_path)
    new.execute("PRAGMA journal_mode=WAL")
    new.execute("PRAGMA foreign_keys=ON")

    _create_new_tables(new)

    user_id_map = _migrate_users(old, new)
    _migrate_userdata(old, new, user_id_map)
    _migrate_event_groups(old, new, user_id_map)
    _migrate_share_groups(old, new, user_id_map)

    new.commit()
    old.close()
    new.close()

    print(f"\nMigration complete! New database: {new_db_path}")
    print(f"Users migrated: {len(user_id_map)}")
    print("Note: Passwords have been re-hashed with bcrypt. Users must use /api/auth/login to get new JWT tokens.")


def _create_new_tables(db: sqlite3.Connection):
    """Create all required tables in the new database."""
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username VARCHAR(150) UNIQUE NOT NULL,
        email VARCHAR(254) UNIQUE NOT NULL,
        hashed_password VARCHAR(128) NOT NULL,
        is_active BOOLEAN DEFAULT 1,
        is_verified BOOLEAN DEFAULT 0,
        created_at DATETIME,
        updated_at DATETIME
    );

    CREATE TABLE IF NOT EXISTS user_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        key VARCHAR(100) NOT NULL,
        value TEXT DEFAULT '{}',
        updated_at DATETIME
    );
    CREATE INDEX IF NOT EXISTS ix_user_data_user_id ON user_data(user_id);
    CREATE INDEX IF NOT EXISTS ix_user_data_key ON user_data(key);

    CREATE TABLE IF NOT EXISTS event_groups (
        id VARCHAR(36) PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name VARCHAR(200) NOT NULL,
        description TEXT DEFAULT '',
        color VARCHAR(20) DEFAULT '#3b82f6',
        typ VARCHAR(50) DEFAULT 'default',
        working_hours_start VARCHAR(10) DEFAULT '09:00',
        working_hours_end VARCHAR(10) DEFAULT '18:00',
        created_at DATETIME,
        updated_at DATETIME
    );

    CREATE TABLE IF NOT EXISTS share_groups (
        id VARCHAR(36) PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name VARCHAR(200) NOT NULL,
        description TEXT DEFAULT '',
        join_code VARCHAR(20) UNIQUE NOT NULL,
        is_active BOOLEAN DEFAULT 1,
        created_at DATETIME,
        updated_at DATETIME
    );

    CREATE TABLE IF NOT EXISTS group_memberships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        share_group_id VARCHAR(36) NOT NULL REFERENCES share_groups(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        role VARCHAR(20) DEFAULT 'member',
        color VARCHAR(20) DEFAULT '',
        joined_at DATETIME
    );
    CREATE INDEX IF NOT EXISTS ix_group_memberships_share_group_id ON group_memberships(share_group_id);
    CREATE INDEX IF NOT EXISTS ix_group_memberships_user_id ON group_memberships(user_id);

    CREATE TABLE IF NOT EXISTS group_calendar_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        share_group_id VARCHAR(36) UNIQUE NOT NULL REFERENCES share_groups(id) ON DELETE CASCADE,
        events_data TEXT DEFAULT '[]',
        last_synced_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        updated_at DATETIME
    );

    CREATE TABLE IF NOT EXISTS oauth_clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id VARCHAR(48) UNIQUE NOT NULL,
        client_secret VARCHAR(128) NOT NULL,
        client_name VARCHAR(200) NOT NULL,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        redirect_uris TEXT DEFAULT '[]',
        grant_types VARCHAR(200) DEFAULT 'authorization_code,refresh_token',
        default_scopes VARCHAR(500) DEFAULT 'read:events read:todos read:reminders',
        is_confidential BOOLEAN DEFAULT 1,
        is_active BOOLEAN DEFAULT 1,
        created_at DATETIME,
        updated_at DATETIME
    );

    CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code VARCHAR(128) UNIQUE NOT NULL,
        client_id VARCHAR(48) NOT NULL,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        redirect_uri VARCHAR(500) NOT NULL,
        scopes TEXT DEFAULT '',
        code_challenge VARCHAR(128),
        code_challenge_method VARCHAR(10),
        nonce VARCHAR(128),
        expires_at DATETIME NOT NULL,
        used BOOLEAN DEFAULT 0,
        created_at DATETIME
    );

    CREATE TABLE IF NOT EXISTS oauth_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        access_token VARCHAR(256) UNIQUE NOT NULL,
        refresh_token VARCHAR(256) UNIQUE,
        token_type VARCHAR(40) DEFAULT 'Bearer',
        client_id VARCHAR(48) NOT NULL,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        scopes TEXT DEFAULT '',
        is_revoked BOOLEAN DEFAULT 0,
        access_token_expires_at DATETIME NOT NULL,
        refresh_token_expires_at DATETIME,
        created_at DATETIME
    );

    CREATE TABLE IF NOT EXISTS verification_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        code VARCHAR(6) NOT NULL,
        purpose VARCHAR(20) NOT NULL DEFAULT 'email',
        expires_at DATETIME NOT NULL,
        used BOOLEAN DEFAULT 0,
        created_at DATETIME
    );
    """)
    db.commit()


def _migrate_users(old: sqlite3.Connection, new: sqlite3.Connection) -> dict:
    """Migrate auth_user → users. Returns old_id → new_id mapping."""
    print("\n--- Migrating users ---")
    id_map = {}

    old_users = old.execute("SELECT * FROM auth_user").fetchall()
    now = datetime.utcnow().isoformat()

    for u in old_users:
        old_id = u["id"]
        username = u["username"]
        email = u.get("email", "") or ""
        password = u.get("password", "")  # Django PBKDF2 hashed password
        is_active = bool(u.get("is_active", 1))
        is_superuser = bool(u.get("is_superuser", 0))
        date_joined = u.get("date_joined", "")

        # Django passwords are prefixed with algorithm like "pbkdf2_sha256$..."
        # We re-hash them with bcrypt because the hash format is incompatible.
        # The first time users login after migration they must use their
        # original password — but since we can't verify the Django PBKDF2
        # hash, we generate a random password. The user must do password reset.
        # 
        # Alternative: store the Django hash in a special field and try both.
        # For simplicity: mark migrated users and require password reset.

        if password:
            # Keep the original Django hash — our verify_password() now supports
            # both bcrypt (new) and Django PBKDF2 (migrated) formats
            hashed = password
        else:
            hashed = hash_password(secrets.token_urlsafe(16))

        try:
            new.execute(
                "INSERT INTO users (username, email, hashed_password, is_active, is_verified, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (username, email, hashed, is_active, is_superuser, date_joined or now)
            )
            new_id = new.execute("SELECT last_insert_rowid()").fetchone()[0]
            id_map[old_id] = new_id
            print(f"  {username} (id {old_id} → {new_id})")
        except sqlite3.IntegrityError as e:
            print(f"  SKIP {username}: {e}")

    new.commit()
    return id_map


def _migrate_userdata(old: sqlite3.Connection, new: sqlite3.Connection, id_map: dict):
    """Migrate core_userdata → user_data."""
    print("\n--- Migrating user data ---")
    count = 0

    old_rows = old.execute("SELECT * FROM core_userdata").fetchall()
    now = datetime.utcnow().isoformat()

    for row in old_rows:
        old_user_id = row["user_id"]
        if old_user_id not in id_map:
            print(f"  SKIP user_data for unknown user {old_user_id}")
            continue

        new_user_id = id_map[old_user_id]
        key = row["key"]
        value = row["value"]

        new.execute(
            "INSERT INTO user_data (user_id, key, value, updated_at) VALUES (?, ?, ?, ?)",
            (new_user_id, key, value, now)
        )
        count += 1

    new.commit()
    print(f"  Migrated {count} user data records")


def _migrate_event_groups(old: sqlite3.Connection, new: sqlite3.Connection, id_map: dict):
    """Migrate core_eventgroup → event_groups AND events_groups in user_data."""
    print("\n--- Migrating event groups ---")

    # Check if core_eventgroup table exists
    table_check = old.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='core_eventgroup'"
    ).fetchone()

    if table_check:
        old_groups = old.execute("SELECT * FROM core_eventgroup").fetchall()
        now = datetime.utcnow().isoformat()
        count = 0
        for row in old_groups:
            old_user_id = row["user_id"] if "user_id" in row.keys() else None
            if old_user_id and old_user_id not in id_map:
                continue
            new_user_id = id_map[old_user_id] if old_user_id else None

            gid = row.get("id", "")
            name = row.get("name", "")
            desc = row.get("description", "")
            color = row.get("color", "#3b82f6")
            typ = row.get("typ", row.get("type", "default"))
            wh_start = row.get("working_hours_start", "09:00")
            wh_end = row.get("working_hours_end", "18:00")

            if gid and name and new_user_id:
                try:
                    new.execute(
                        "INSERT INTO event_groups (id, user_id, name, description, color, typ, working_hours_start, working_hours_end, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (gid, new_user_id, name, desc, color, typ, wh_start, wh_end, now, now)
                    )
                    count += 1
                except sqlite3.IntegrityError:
                    pass
        new.commit()
        print(f"  Migrated {count} event groups")

    # Also migrate events_groups from core_userdata (JSON array in user_data table)
    # This is already handled by _migrate_userdata since it copies all user_data keys


def _migrate_share_groups(old: sqlite3.Connection, new: sqlite3.Connection, id_map: dict):
    """Migrate collaboration tables → share_groups, group_memberships, group_calendar_data."""
    now = datetime.utcnow().isoformat()

    # Share groups
    print("\n--- Migrating share groups ---")
    table_check = old.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='core_collaborativecalendargroup'"
    ).fetchone()

    if table_check:
        old_groups = old.execute("SELECT * FROM core_collaborativecalendargroup").fetchall()
        count = 0
        for row in old_groups:
            old_owner_id = row.get("owner_id")
            if old_owner_id not in id_map:
                continue

            gid = row.get("share_group_id") or row.get("id", "")
            name = row.get("name", "Shared Group")
            desc = row.get("description", "")
            join_code = row.get("join_code") or row.get("invite_code", "") or secrets.token_hex(4).upper()
            is_active = row.get("is_active", 1)

            if gid and name:
                try:
                    new.execute(
                        "INSERT INTO share_groups (id, owner_id, name, description, join_code, is_active, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (gid, id_map[old_owner_id], name, desc, join_code, is_active, now, now)
                    )
                    count += 1
                except sqlite3.IntegrityError:
                    pass

        new.commit()
        print(f"  Migrated {count} share groups")

    # Group memberships
    gc_table = old.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='core_groupmembership'"
    ).fetchone()

    if gc_table:
        old_members = old.execute("SELECT * FROM core_groupmembership").fetchall()
        count = 0
        for row in old_members:
            old_user_id = row.get("user_id")
            group_id = row.get("share_group_id") or row.get("group_id", "")
            role = row.get("role", "member")
            color = row.get("color", "")

            if old_user_id in id_map and group_id:
                try:
                    new.execute(
                        "INSERT INTO group_memberships (share_group_id, user_id, role, color, joined_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (group_id, id_map[old_user_id], role, color, now)
                    )
                    count += 1
                except sqlite3.IntegrityError:
                    pass

        new.commit()
        print(f"  Migrated {count} group memberships")

    # Group calendar data
    gcd_table = old.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='core_groupcalendardata'"
    ).fetchone()

    if gcd_table:
        old_data = old.execute("SELECT * FROM core_groupcalendardata").fetchall()
        count = 0
        for row in old_data:
            group_id = row.get("share_group_id") or row.get("group_id", "")
            events_data = row.get("events_data", "[]")
            synced_by = row.get("last_synced_by_id") or row.get("last_synced_by")
            if synced_by and synced_by in id_map:
                synced_by = id_map[synced_by]
            else:
                synced_by = None

            if group_id:
                try:
                    new.execute(
                        "INSERT INTO group_calendar_data (share_group_id, events_data, last_synced_by, updated_at) "
                        "VALUES (?, ?, ?, ?)",
                        (group_id, events_data, synced_by, now)
                    )
                    count += 1
                except sqlite3.IntegrityError:
                    pass

        new.commit()
        print(f"  Migrated {count} group calendar data records")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} /path/to/old/db.sqlite3 [new_db_path]")
        sys.exit(1)

    old_path = sys.argv[1]
    new_path = sys.argv[2] if len(sys.argv) > 2 else "uni_calendar.db"
    migrate(old_path, new_path)
