"""
frontend.py
Flask-based frontend for Job Apply Bot.
Handles registration, login, dashboard (profile edit), job application form, and applications list.
"""

from flask import Flask, render_template, request, redirect, url_for, flash, session
import backend as backend
from datetime import datetime

app = Flask(__name__)
app.secret_key = "supersecretkey"

# --------------------
# Home
# --------------------
@app.route("/")
def home():
    return redirect(url_for("login"))

# --------------------
# Registration
# --------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        msg = backend.register_user(email, password)
        flash(msg)
        if "Registration successful!" in msg:
            return redirect(url_for("login"))
        return redirect(url_for("register"))
    return render_template("register.html")

# --------------------
# Login
# --------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        msg = backend.login_user(email, password)
        flash(msg)
        if "Login successful!" in msg:
            session["user"] = email
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))
    return render_template("login.html")

# --------------------
# Dashboard (Profile edit)
# --------------------
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user" not in session:
        flash("Please log in first!")
        return redirect(url_for("login"))

    profile_data = backend.get_profile(session["user"])

    if request.method == "POST":
        data = {
            "user_email": session["user"],
            "first_name": request.form.get("first_name", ""),
            "last_name": request.form.get("last_name", ""),
            "address": request.form.get("address", ""),
            "city": request.form.get("city", ""),
            "mobile_number": request.form.get("mobile_number", ""),
            "github_url": request.form.get("github_url", ""),
            "job_position": request.form.get("job_position", ""),
            "experience_months": int(request.form.get("experience_months", 0)),
            "skills": request.form.get("skills", ""),
            "preferred_locations": request.form.get("preferred_locations", ""),
        }

        if profile_data:
            backend.update_profile(session["user"], data)
        else:
            backend.save_profile(data)

        flash("Profile saved successfully!")
        # redirect to job details page for new application entry
        return redirect(url_for("job_details"))

    return render_template("dashboard.html", profile=profile_data)

# --------------------
# Job Application Form
# --------------------
@app.route("/job_details", methods=["GET", "POST"])
def job_details():
    if "user" not in session:
        flash("Please log in first!")
        return redirect(url_for("login"))

    if request.method == "POST":
        data = {
            "user_email": session["user"],
            "job_link": request.form.get("job_link", ""),
            "company_name": request.form.get("company_name", ""),
            "job_role": request.form.get("job_role", ""),
            "job_location": request.form.get("job_location", ""),
            "status": request.form.get("status", ""),
            "recruiter_name": request.form.get("recruiter_name", ""),
            "recruiter_email": request.form.get("recruiter_email", ""),
            "recruiter_phone": request.form.get("recruiter_phone", ""),
            "comments": request.form.get("comments", ""),
        }
        
        from backend import job_exists_for_user, save_job_application
        if job_exists_for_user(data["user_email"], data["job_link"]):
            return render_template("job_details.html", success_message="Duplicate Job Link! Record not added.")

        backend.save_job_application(data)
        return render_template("job_details.html", success_message="Form filled successfully!")
        return redirect(url_for("job_details"))  # clear form after submit

    return render_template("job_details.html")


# --------------------
# Applications List
# --------------------
@app.route("/applications")
def applications():
    if "user" not in session:
        flash("Please log in first!")
        return redirect(url_for("login"))

    apps = backend.get_user_applications(session["user"])
    # Compute Days Since Created
    for job in apps:
        created_dt = datetime.fromisoformat(job["created_at"])
        job["days_since_created"] = (datetime.utcnow() - created_dt).days

    return render_template("applications.html", jobs=apps)

@app.route("/delete_job/<int:job_id>", methods=["POST"])
def delete_job(job_id):
    if "user" not in session:
        flash("Please log in first!")
        return redirect(url_for("login"))

    msg = backend.delete_job_application_by_id(job_id)
    flash(msg)
    return redirect(url_for("applications"))

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out successfully.")
    return redirect(url_for("login"))



# --------------------
# Profile View
# --------------------
@app.route("/profile")
def profile():
    if "user" not in session:
        flash("Please log in first!")
        return redirect(url_for("login"))

    profile_data = backend.get_profile(session["user"])
    if not profile_data:
        flash("No profile found. Please fill your details.")
        return redirect(url_for("dashboard"))

    return render_template("profile.html", profile=profile_data)


if __name__ == "__main__":
    backend.init_db()
    app.run(debug=True)
