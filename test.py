"""
backend.py
Handles user registration, login verification, user profile storage (local only),
and job application tracking with Google Sheets integration for job rows only.
Uses SQLite as a lightweight local database.
"""

import sqlite3
import bcrypt
import validators
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

DB_NAME = "users.db"

# ----------------------------
# Google Sheets config (EDIT)
# ----------------------------
SERVICE_ACCOUNT_FILE = "service_account.json"   # <-- put your JSON here (project root)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = "1DbxpXxkFSJ9D3Acep9U7aOcnKe9rGBIoh7y56ucLlrg"  # <-- replace with your Sheet ID
# ----------------------------------------------------------------


def get_db_connection():
    return sqlite3.connect(DB_NAME)


def init_db():
    """
    Completely reset database: drop all tables if exist and recreate fresh.
    This ensures no leftover data in users, profiles, or job_applications.
    """
    conn = get_db_connection()
    c = conn.cursor()

    # Drop all tables if they exist
    c.execute("DROP TABLE IF EXISTS job_applications;")
    c.execute("DROP TABLE IF EXISTS user_profiles;")
    c.execute("DROP TABLE IF EXISTS users;")

    # Recreate tables
    c.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE user_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            address TEXT,
            city TEXT,
            mobile_number TEXT,
            github_url TEXT,
            job_position TEXT,
            experience_months INTEGER,
            skills TEXT,
            preferred_locations TEXT,
            created_at TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE job_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            job_link TEXT NOT NULL,
            company_name TEXT,
            job_role TEXT,
            job_location TEXT,
            status TEXT,
            recruiter_name TEXT,
            recruiter_email TEXT,
            recruiter_phone TEXT,
            comments TEXT,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


# ----------------------------
# Registration & Login
# ----------------------------
def register_user(email: str, password: str) -> str:
    if not validators.email(email):
        return "Invalid email format."
    if len(password) < 8:
        return "Password must be at least 8 characters."

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, password_hash.decode("utf-8"), datetime.utcnow().isoformat())
        )
        conn.commit()
        return "Registration successful!"
    except sqlite3.IntegrityError:
        return "Email already registered."
    finally:
        conn.close()


def login_user(email: str, password: str) -> str:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT password_hash FROM users WHERE email = ?", (email,))
    user = c.fetchone()
    conn.close()

    if not user:
        return "No account found with that email."

    stored_hash = user[0].encode("utf-8")
    if bcrypt.checkpw(password.encode("utf-8"), stored_hash):
        return "Login successful!"
    return "Incorrect password."


# ----------------------------
# Profile functions (local only)
# ----------------------------
def save_profile(data: dict) -> str:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO user_profiles
        (user_email, first_name, last_name, address, city, mobile_number,
         github_url, job_position, experience_months, skills, preferred_locations, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["user_email"],
        data.get("first_name", ""),
        data.get("last_name", ""),
        data.get("address", ""),
        data.get("city", ""),
        data.get("mobile_number", ""),
        data.get("github_url", ""),
        data.get("job_position", ""),
        data.get("experience_months", 0),
        data.get("skills", ""),
        data.get("preferred_locations", ""),
        datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()
    return "Profile saved locally."


def get_profile(user_email: str) -> dict:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT first_name, last_name, address, city, mobile_number, github_url,
               job_position, experience_months, skills, preferred_locations
        FROM user_profiles
        WHERE user_email = ?
        ORDER BY id DESC LIMIT 1
    """, (user_email,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "first_name": row[0],
            "last_name": row[1],
            "address": row[2],
            "city": row[3],
            "mobile_number": row[4],
            "github_url": row[5],
            "job_position": row[6],
            "experience_months": row[7],
            "skills": row[8],
            "preferred_locations": row[9],
        }
    return {}


def update_profile(user_email: str, data: dict) -> str:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE user_profiles
        SET first_name = ?, last_name = ?, address = ?, city = ?, mobile_number = ?,
            github_url = ?, job_position = ?, experience_months = ?, skills = ?, preferred_locations = ?
        WHERE id = (SELECT id FROM user_profiles WHERE user_email = ? ORDER BY id DESC LIMIT 1)
    """, (
        data.get("first_name", ""),
        data.get("last_name", ""),
        data.get("address", ""),
        data.get("city", ""),
        data.get("mobile_number", ""),
        data.get("github_url", ""),
        data.get("job_position", ""),
        data.get("experience_months", 0),
        data.get("skills", ""),
        data.get("preferred_locations", ""),
        user_email
    ))
    conn.commit()
    conn.close()
    return "Profile updated locally."


# ----------------------------
# Job applications functions (local + Google Sheets)
# ----------------------------
def job_exists_for_user(user_email: str, job_link: str) -> bool:
    """Return True if the user already has a job entry with the same job_link."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "SELECT id FROM job_applications WHERE user_email = ? AND job_link = ?",
        (user_email, job_link)
    )
    exists = c.fetchone() is not None
    conn.close()
    return exists


def save_job_application(data: dict) -> str:
    """
    Save a job application to local DB and append to Google Sheets.
    Prevents duplicate job_link per user.
    """
    if job_exists_for_user(data["user_email"], data["job_link"]):
        return "Duplicate job link for this user. Record not added."

    now_iso = datetime.utcnow().isoformat()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO job_applications
        (user_email, job_link, company_name, job_role, job_location, status,
         recruiter_name, recruiter_email, recruiter_phone, comments, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["user_email"],
        data.get("job_link", ""),
        data.get("company_name", ""),
        data.get("job_role", ""),
        data.get("job_location", ""),
        data.get("status", ""),
        data.get("recruiter_name", ""),
        data.get("recruiter_email", ""),
        data.get("recruiter_phone", ""),
        data.get("comments", ""),
        now_iso
    ))
    conn.commit()
    conn.close()

    # Append to Google Sheets
    gs_msg = append_job_to_google_sheets(data, now_iso)
    print("Google Sheets:", gs_msg)
    return "Job application saved successfully!"


def get_user_applications(user_email: str) -> list:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, job_link, company_name, job_role, job_location, status,
               recruiter_name, recruiter_email, recruiter_phone, comments, created_at
        FROM job_applications
        WHERE user_email = ?
        ORDER BY id DESC
    """, (user_email,))
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "job_link": row[1],
            "company_name": row[2],
            "job_role": row[3],
            "job_location": row[4],
            "status": row[5],
            "recruiter_name": row[6],
            "recruiter_email": row[7],
            "recruiter_phone": row[8],
            "comments": row[9],
            "created_at": row[10]
        } for row in rows
    ]


def append_job_to_google_sheets(data: dict, created_iso: str) -> str:
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1

        headers = [
            "User Email", "Job Link", "Company Name", "Job Role", "Job Location", "Status",
            "Recruiter Name", "Recruiter Email", "Recruiter Phone", "Days Since Created",
            "Comments", "Created At"
        ]

        all_values = sheet.get_all_values()
        if not all_values:
            sheet.append_row(headers)
        else:
            first_row = all_values[0]
            if len(first_row) < len(headers) or any(h1.strip() != h2.strip() for h1, h2 in zip(first_row, headers)):
                sheet.clear()
                sheet.append_row(headers)

        created_dt = datetime.fromisoformat(created_iso)
        days_since = (datetime.utcnow() - created_dt).days

        row = [
            data.get("user_email", ""),
            data.get("job_link", ""),
            data.get("company_name", ""),
            data.get("job_role", ""),
            data.get("job_location", ""),
            data.get("status", ""),
            data.get("recruiter_name", ""),
            data.get("recruiter_email", ""),
            data.get("recruiter_phone", ""),
            days_since,
            data.get("comments", ""),
            created_iso
        ]
        sheet.append_row(row)
        return "Job appended to Google Sheets."
    except Exception as e:
        print("Google Sheets error:", e)
        return f"Failed to append job to Google Sheets: {e}"


# Optional update/delete functions
def update_job_application(job_id: int, data: dict) -> str:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE job_applications
        SET job_link = ?, company_name = ?, job_role = ?, job_location = ?, status = ?,
            recruiter_name = ?, recruiter_email = ?, recruiter_phone = ?, comments = ?
        WHERE id = ?
    """, (
        data.get("job_link", ""),
        data.get("company_name", ""),
        data.get("job_role", ""),
        data.get("job_location", ""),
        data.get("status", ""),
        data.get("recruiter_name", ""),
        data.get("recruiter_email", ""),
        data.get("recruiter_phone", ""),
        data.get("comments", ""),
        job_id
    ))
    conn.commit()
    conn.close()
    return "Job updated locally."


def delete_job_application_by_id(job_id: int) -> str:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT job_link, user_email FROM job_applications WHERE id = ?", (job_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return "No such job record found."

    job_link, user_email = row[0], row[1]

    # Delete from local DB
    c.execute("DELETE FROM job_applications WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    # Delete from Google Sheets
    sheet_msg = delete_job_from_google_sheets(user_email, job_link)
    print("Google Sheets:", sheet_msg)

    return f"Job application deleted successfully ({sheet_msg})"


def delete_job_from_google_sheets(user_email: str, job_link: str) -> str:
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1

        data = sheet.get_all_values()
        if not data or len(data) <= 1:
            return "No rows to delete in Google Sheet."

        headers = data[0]
        user_email_col = headers.index("User Email") + 1 if "User Email" in headers else None
        job_link_col = headers.index("Job Link") + 1 if "Job Link" in headers else None

        if not user_email_col or not job_link_col:
            return "Required columns not found in Google Sheet."

        rows_to_delete = []
        for i, row in enumerate(data[1:], start=2):
            if len(row) >= max(user_email_col, job_link_col):
                if row[user_email_col - 1] == user_email and row[job_link_col - 1] == job_link:
                    rows_to_delete.append(i)

        if not rows_to_delete:
            return "No matching row found in Google Sheet."

        for row_idx in sorted(rows_to_delete, reverse=True):
            sheet.delete_rows(row_idx)

        return "Deleted from Google Sheet."
    except Exception as e:
        print("Error deleting job from Google Sheets:", e)
        return f"Failed to delete from Google Sheets: {e}"


# ----------------------------
# Clear Google Sheets helper
# ----------------------------
def clear_google_sheet_rows():
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1

        sheet.clear()
        headers = [
            "User Email", "Job Link", "Company Name", "Job Role", "Job Location", "Status",
            "Recruiter Name", "Recruiter Email", "Recruiter Phone", "Days Since Created",
            "Comments", "Created At"
        ]
        sheet.append_row(headers)
        print("Google Sheet cleared and headers re-added.")
    except Exception as e:
        print("Error clearing Google Sheet:", e)
        raise


# Run this file alone once to initialize the DB
if __name__ == "__main__":
    init_db()
    print("Database fully initialized and cleared.")


"""
backend.py
Handles user registration, login verification, user profile storage (local only),
and job application tracking with Google Sheets integration for job rows only.
Uses SQLite as a lightweight local database.
"""

import sqlite3
import bcrypt
import validators
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

DB_NAME = "users.db"

# ----------------------------
# Google Sheets config (EDIT)
# ----------------------------
SERVICE_ACCOUNT_FILE = "service_account.json"   # <-- put your JSON here (project root)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = "1DbxpXxkFSJ9D3Acep9U7aOcnKe9rGBIoh7y56ucLlrg"                 # <-- replace with your Sheet ID
# ----------------------------------------------------------------


def get_db_connection():
    return sqlite3.connect(DB_NAME)


def init_db():
    """
    Completely reset database: drop all tables if exist and recreate fresh.
    This ensures no leftover data in users, profiles, or job_applications.
    """
    conn = get_db_connection()
    c = conn.cursor()

    # Drop all tables if they exist
    c.execute("DROP TABLE IF EXISTS job_applications;")
    c.execute("DROP TABLE IF EXISTS user_profiles;")
    c.execute("DROP TABLE IF EXISTS users;")

    # Recreate tables
    c.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE user_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            address TEXT,
            city TEXT,
            mobile_number TEXT,
            github_url TEXT,
            job_position TEXT,
            experience_months INTEGER,
            skills TEXT,
            preferred_locations TEXT,
            created_at TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE job_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            job_link TEXT NOT NULL,
            company_name TEXT,
            job_role TEXT,
            job_location TEXT,
            status TEXT,
            recruiter_name TEXT,
            recruiter_email TEXT,
            recruiter_phone TEXT,
            comments TEXT,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


# ----------------------------
# Registration & Login
# ----------------------------
def register_user(email: str, password: str) -> str:
    if not validators.email(email):
        return "Invalid email format."
    if len(password) < 8:
        return "Password must be at least 8 characters."

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, password_hash.decode("utf-8"), datetime.utcnow().isoformat())
        )
        conn.commit()
        return "Registration successful!"
    except sqlite3.IntegrityError:
        return "Email already registered."
    finally:
        conn.close()


def login_user(email: str, password: str) -> str:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT password_hash FROM users WHERE email = ?", (email,))
    user = c.fetchone()
    conn.close()

    if not user:
        return "No account found with that email."

    stored_hash = user[0].encode("utf-8")
    if bcrypt.checkpw(password.encode("utf-8"), stored_hash):
        return "Login successful!"
    return "Incorrect password."


# ----------------------------
# Profile functions (local only)
# ----------------------------
def save_profile(data: dict) -> str:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO user_profiles
        (user_email, first_name, last_name, address, city, mobile_number,
         github_url, job_position, experience_months, skills, preferred_locations, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["user_email"],
        data.get("first_name", ""),
        data.get("last_name", ""),
        data.get("address", ""),
        data.get("city", ""),
        data.get("mobile_number", ""),
        data.get("github_url", ""),
        data.get("job_position", ""),
        data.get("experience_months", 0),
        data.get("skills", ""),
        data.get("preferred_locations", ""),
        datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()
    return "Profile saved locally."


def get_profile(user_email: str) -> dict:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT first_name, last_name, address, city, mobile_number, github_url,
               job_position, experience_months, skills, preferred_locations
        FROM user_profiles
        WHERE user_email = ?
        ORDER BY id DESC LIMIT 1
    """, (user_email,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "first_name": row[0],
            "last_name": row[1],
            "address": row[2],
            "city": row[3],
            "mobile_number": row[4],
            "github_url": row[5],
            "job_position": row[6],
            "experience_months": row[7],
            "skills": row[8],
            "preferred_locations": row[9],
        }
    return {}


def update_profile(user_email: str, data: dict) -> str:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE user_profiles
        SET first_name = ?, last_name = ?, address = ?, city = ?, mobile_number = ?,
            github_url = ?, job_position = ?, experience_months = ?, skills = ?, preferred_locations = ?
        WHERE id = (SELECT id FROM user_profiles WHERE user_email = ? ORDER BY id DESC LIMIT 1)
    """, (
        data.get("first_name", ""),
        data.get("last_name", ""),
        data.get("address", ""),
        data.get("city", ""),
        data.get("mobile_number", ""),
        data.get("github_url", ""),
        data.get("job_position", ""),
        data.get("experience_months", 0),
        data.get("skills", ""),
        data.get("preferred_locations", ""),
        user_email
    ))
    conn.commit()
    conn.close()
    return "Profile updated locally."


# ----------------------------
# Job applications functions (local + Google Sheets)
# ----------------------------
def save_job_application(data: dict) -> str:
    now_iso = datetime.utcnow().isoformat()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO job_applications
        (user_email, job_link, company_name, job_role, job_location, status,
         recruiter_name, recruiter_email, recruiter_phone, comments, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["user_email"],
        data.get("job_link", ""),
        data.get("company_name", ""),
        data.get("job_role", ""),
        data.get("job_location", ""),
        data.get("status", ""),
        data.get("recruiter_name", ""),
        data.get("recruiter_email", ""),
        data.get("recruiter_phone", ""),
        data.get("comments", ""),
        now_iso
    ))
    conn.commit()
    conn.close()

    # Append to Google Sheets
    gs_msg = append_job_to_google_sheets(data, now_iso)
    print("Google Sheets:", gs_msg)
    return "Job application saved successfully!"


def get_user_applications(user_email: str) -> list:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, job_link, company_name, job_role, job_location, status,
               recruiter_name, recruiter_email, recruiter_phone, comments, created_at
        FROM job_applications
        WHERE user_email = ?
        ORDER BY id DESC
    """, (user_email,))
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "job_link": row[1],
            "company_name": row[2],
            "job_role": row[3],
            "job_location": row[4],
            "status": row[5],
            "recruiter_name": row[6],
            "recruiter_email": row[7],
            "recruiter_phone": row[8],
            "comments": row[9],
            "created_at": row[10]
        } for row in rows
    ]


def append_job_to_google_sheets(data: dict, created_iso: str) -> str:
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1

        headers = [
            "User Email", "Job Link", "Company Name", "Job Role", "Job Location", "Status",
            "Recruiter Name", "Recruiter Email", "Recruiter Phone", "Days Since Created",
            "Comments", "Created At"
        ]

        all_values = sheet.get_all_values()
        if not all_values:
            sheet.append_row(headers)
        else:
            first_row = all_values[0]
            if len(first_row) < len(headers) or any(h1.strip() != h2.strip() for h1, h2 in zip(first_row, headers)):
                sheet.clear()
                sheet.append_row(headers)

        created_dt = datetime.fromisoformat(created_iso)
        days_since = (datetime.utcnow() - created_dt).days

        row = [
            data.get("user_email", ""),
            data.get("job_link", ""),
            data.get("company_name", ""),
            data.get("job_role", ""),
            data.get("job_location", ""),
            data.get("status", ""),
            data.get("recruiter_name", ""),
            data.get("recruiter_email", ""),
            data.get("recruiter_phone", ""),
            days_since,
            data.get("comments", ""),
            created_iso
        ]
        sheet.append_row(row)
        return "Job appended to Google Sheets."
    except Exception as e:
        print("Google Sheets error:", e)
        return f"Failed to append job to Google Sheets: {e}"


# Optional update/delete functions
def update_job_application(job_id: int, data: dict) -> str:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE job_applications
        SET job_link = ?, company_name = ?, job_role = ?, job_location = ?, status = ?,
            recruiter_name = ?, recruiter_email = ?, recruiter_phone = ?, comments = ?
        WHERE id = ?
    """, (
        data.get("job_link", ""),
        data.get("company_name", ""),
        data.get("job_role", ""),
        data.get("job_location", ""),
        data.get("status", ""),
        data.get("recruiter_name", ""),
        data.get("recruiter_email", ""),
        data.get("recruiter_phone", ""),
        data.get("comments", ""),
        job_id
    ))
    conn.commit()
    conn.close()
    return "Job updated locally."


def delete_job_application_by_id(job_id: int) -> str:
    """
    Delete a job application by its ID from both the local DB and Google Sheets.
    """
    conn = get_db_connection()
    c = conn.cursor()

    # Fetch job details before deleting (to find in Sheets)
    c.execute("SELECT job_link, user_email FROM job_applications WHERE id = ?", (job_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return "No such job record found."

    job_link, user_email = row[0], row[1]

    # Delete from local DB
    c.execute("DELETE FROM job_applications WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    # Try to delete from Google Sheets too
    sheet_msg = delete_job_from_google_sheets(user_email, job_link)
    print("Google Sheets:", sheet_msg)

    return f"Job application deleted successfully ({sheet_msg})"


def delete_job_from_google_sheets(user_email: str, job_link: str) -> str:
    """
    Delete a job row from Google Sheets based on user_email and job_link match.
    """
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1

        data = sheet.get_all_values()

        if not data or len(data) <= 1:
            return "No rows to delete in Google Sheet."

        headers = data[0]
        user_email_col = headers.index("User Email") + 1 if "User Email" in headers else None
        job_link_col = headers.index("Job Link") + 1 if "Job Link" in headers else None

        if not user_email_col or not job_link_col:
            return "Required columns not found in Google Sheet."

        rows_to_delete = []
        for i, row in enumerate(data[1:], start=2):  # start=2 since first row is header
            if len(row) >= max(user_email_col, job_link_col):
                if row[user_email_col - 1] == user_email and row[job_link_col - 1] == job_link:
                    rows_to_delete.append(i)

        if not rows_to_delete:
            return "No matching row found in Google Sheet."

        # Delete in reverse order (so row numbers don’t shift)
        for row_idx in sorted(rows_to_delete, reverse=True):
            sheet.delete_rows(row_idx)

        return "Deleted from Google Sheet."

    except Exception as e:
        print("Error deleting job from Google Sheets:", e)
        return f"Failed to delete from Google Sheets: {e}"



# ----------------------------
# Clear Google Sheets helper
# ----------------------------
def clear_google_sheet_rows():
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1

        sheet.clear()
        headers = [
            "User Email", "Job Link", "Company Name", "Job Role", "Job Location", "Status",
            "Recruiter Name", "Recruiter Email", "Recruiter Phone", "Days Since Created",
            "Comments", "Created At"
        ]
        sheet.append_row(headers)
        print("Google Sheet cleared and headers re-added.")
    except Exception as e:
        print("Error clearing Google Sheet:", e)
        raise


# Run this file alone once to initialize the DB
if __name__ == "__main__":
    init_db()
    print("Database fully initialized and cleared.")
