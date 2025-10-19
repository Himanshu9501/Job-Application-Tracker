"""
clear_users.py
Fully clears all data and reinitializes the database,
including users, profiles, and job applications.
Also clears the Google Sheets job rows.
"""

import backend as backend

if __name__ == "__main__":
    # Reinitialize DB (drops all tables and recreates)
    backend.init_db()
    print("Database fully cleared and reinitialized.")

    # Clear Google Sheets (job applications)
    try:
        backend.clear_google_sheet_rows()
        print("Google Sheet cleared and headers re-added.")
    except Exception as e:
        print("Failed to clear Google Sheet:", e)
