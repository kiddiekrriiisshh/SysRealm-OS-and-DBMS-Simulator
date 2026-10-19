#!/usr/bin/env python3
"""
SysRealm Administrative Provisioning Tool
Provisions Teacher/Instructor accounts securely with salted scrypt hashing.
Public registration only allows student accounts.
"""

import sys
import argparse
import pymysql
import sqlite3
import os
from werkzeug.security import generate_password_hash
from config import Config

def provision_teacher(email: str, name: str, password: str):
    email = email.strip().lower()
    name = name.strip()
    if not email or not password or not name:
        print("Error: Name, email, and password must not be empty.")
        sys.exit(1)

    hashed_pw = generate_password_hash(password, method='scrypt')
    print(f"Provisioning teacher account for: {name} ({email})...")

    # 1. Update SQLite Mirror
    db_path = os.path.join(os.path.dirname(__file__), 'sysrealm_mysql_mirror.db')
    try:
        conn = sqlite3.connect(db_path)
        with conn:
            conn.execute(
                """INSERT INTO users (username, email, password_hash, account_type)
                   VALUES (?, ?, ?, 'teacher')
                   ON CONFLICT(email) DO UPDATE SET
                       username=excluded.username,
                       password_hash=excluded.password_hash,
                       account_type='teacher'""",
                (name, email, hashed_pw)
            )
        conn.close()
        print(f"  ✓ Synchronized to SQLite mirror ({db_path})")
    except Exception as e:
        print(f"  ✗ SQLite mirror error: {e}")

    # 2. Update MySQL Database if available
    try:
        mconn = pymysql.connect(
            host=Config.DB_HOST,
            port=int(Config.DB_PORT),
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=2
        )
        with mconn.cursor() as cur:
            cur.execute(
                """INSERT INTO users (username, email, password_hash, account_type)
                   VALUES (%s, %s, %s, 'teacher')
                   ON DUPLICATE KEY UPDATE
                       username=VALUES(username),
                       password_hash=VALUES(password_hash),
                       account_type='teacher'""",
                (name, email, hashed_pw)
            )
        mconn.commit()
        mconn.close()
        print(f"  ✓ Synchronized to MySQL database ({Config.DB_NAME}@{Config.DB_HOST})")
    except Exception as e:
        print(f"  ℹ MySQL offline ({e}); recorded in SQLite mirror.")

    print(f"Successfully provisioned Teacher account '{email}'.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="SysRealm Teacher Account Provisioning")
    parser.add_argument('--email', default='teacher@sysrealm.com', help="Teacher email address")
    parser.add_argument('--name', default='Prof. Sharma', help="Teacher display name")
    parser.add_argument('--password', default='Teacher@123', help="Teacher password")
    args = parser.parse_args()

    provision_teacher(args.email, args.name, args.password)
