import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import jwt
from dotenv import load_dotenv
from flask import Flask, g, jsonify, request, send_file
from PIL import Image, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from civic_services import (
    analyze_urgency,
    classify_complaint,
    dispatch_citizen_notification,
    estimate_completion,
    evaluate_classifier,
    hotspot_clusters,
    predict_priority,
    predict_with_tfidf_model,
    retry_delivery,
    normalize_indian_mobile,
    similar_complaints,
)

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

CATEGORY_DEPARTMENT_MAP = json.loads(
    (BASE_DIR.parent / "category_departments.json").read_text(encoding="utf-8")
)
CATEGORIES = set(CATEGORY_DEPARTMENT_MAP)
DEPARTMENTS = set(CATEGORY_DEPARTMENT_MAP.values())
STATUSES = {"Pending", "In progress", "Resolved"}
DEPARTMENT_STATUSES = {"Pending", "Accepted", "In progress", "Completed"}
PRIORITIES = {"Low", "Medium", "High"}
UNASSIGNED_DEPARTMENT = "Municipal review required"
DEPARTMENT_BY_CATEGORY = CATEGORY_DEPARTMENT_MAP
ALLOWED_IMAGE_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE=str((BASE_DIR / os.getenv("DATABASE_PATH", "data/smartcivic.db")).resolve()),
        UPLOAD_FOLDER=str((BASE_DIR / os.getenv("UPLOAD_FOLDER", "uploads")).resolve()),
        MAX_CONTENT_LENGTH=MAX_IMAGE_BYTES + 256 * 1024,
        ACCESS_TOKEN_MINUTES=int(os.getenv("ACCESS_TOKEN_MINUTES", "30")),
        OVERDUE_AFTER_HOURS=int(os.getenv("OVERDUE_AFTER_HOURS", "72")),
        UNACCEPTED_AFTER_HOURS=int(os.getenv("UNACCEPTED_AFTER_HOURS", "24")),
        ETA_FALLBACK_HOURS=float(os.getenv("ETA_FALLBACK_HOURS", "72")),
        ML_CONFIDENCE_THRESHOLD=float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.55")),
        MSG91_AUTH_KEY=os.getenv("MSG91_AUTH_KEY"),
        MSG91_TEMPLATE_ID=os.getenv("MSG91_TEMPLATE_ID"),
        MSG91_SENDER_ID=os.getenv("MSG91_SENDER_ID"),
        MSG91_DLT_PE_ID=os.getenv("MSG91_DLT_PE_ID"),
        MSG91_DLT_TEMPLATE_ID=os.getenv("MSG91_DLT_TEMPLATE_ID"),
        BREVO_API_KEY=os.getenv("BREVO_API_KEY"),
        BREVO_SENDER_EMAIL=os.getenv("BREVO_SENDER_EMAIL"),
        BREVO_SENDER_NAME=os.getenv("BREVO_SENDER_NAME", "SmartCivicAI"),
        OVERDUE_REMINDER_INTERVAL_SECONDS=int(os.getenv("OVERDUE_REMINDER_INTERVAL_SECONDS", "3600")),
        FRONTEND_ORIGINS={
            origin.strip()
            for origin in os.getenv(
                "FRONTEND_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if origin.strip()
        },
    )
    if test_config:
        app.config.update(test_config)
    app.config["JWT_SECRET"] = app.config.get("JWT_SECRET") or os.getenv("SECRET_KEY")
    if not app.config["JWT_SECRET"] and not app.config.get("TESTING"):
        raise RuntimeError("Set SECRET_KEY in backend/.env before starting the API.")
    if app.config.get("TESTING") and not app.config["JWT_SECRET"]:
        raise RuntimeError("Tests must provide a JWT_SECRET.")

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    initialize_database(app)
    scheduler_lock = threading.Lock()
    scheduler_started = False

    @app.before_request
    def start_overdue_scheduler():
        nonlocal scheduler_started
        if app.config.get("TESTING") or not app.config.get("START_OVERDUE_SCHEDULER", True):
            return
        with scheduler_lock:
            if scheduler_started:
                return
            scheduler_started = True
            thread = threading.Thread(
                target=overdue_scheduler,
                args=(app,),
                name="smartcivic-overdue-reminders",
                daemon=True,
            )
            thread.start()

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin")
        if origin in app.config["FRONTEND_ORIGINS"]:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
        return response

    @app.errorhandler(413)
    def file_too_large(_error):
        return jsonify(error="Request or image exceeds the allowed size."), 413

    @app.errorhandler(sqlite3.IntegrityError)
    def database_conflict(_error):
        return jsonify(error="The requested data conflicts with an existing record."), 409

    @app.teardown_appcontext
    def close_database(_error=None):
        database = g.pop("database", None)
        if database is not None:
            database.close()

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.post("/api/auth/register")
    def register():
        payload = json_payload()
        if isinstance(payload, tuple):
            return payload
        name = clean_text(payload.get("name"), "name", 1, 120)
        email = clean_email(payload.get("email"))
        password = validate_password(payload.get("password"))
        if isinstance(name, tuple):
            return name
        if isinstance(email, tuple):
            return email
        if isinstance(password, tuple):
            return password
        phone = payload.get("phone")
        if phone is not None and (not isinstance(phone, str) or len(phone) > 40):
            return jsonify(error="phone must be a string of at most 40 characters."), 400
        sms_consent = payload.get("sms_consent", False)
        if not isinstance(sms_consent, bool):
            return jsonify(error="sms_consent must be true or false."), 400
        if sms_consent and not (phone and phone.strip()):
            return jsonify(error="A phone number is required to consent to SMS updates."), 400
        if sms_consent:
            phone = normalize_indian_mobile(phone)
            if not phone:
                return jsonify(error="Enter a valid Indian mobile number with a +91 country code."), 400

        user = {
            "id": str(uuid.uuid4()),
            "name": name,
            "email": email,
            "phone": phone.strip() if phone else None,
            "sms_consent": int(sms_consent),
            "role": "citizen",
            "created_at": utc_now(),
        }
        try:
            db = get_database()
            db.execute(
                """INSERT INTO users
                   (id, name, email, phone, sms_consent, password_hash, role, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'citizen', ?)""",
                (user["id"], user["name"], user["email"], user["phone"], user["sms_consent"],
                 generate_password_hash(password), user["created_at"]),
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            return jsonify(error="An account with this email already exists."), 409
        return jsonify(token=create_token(user), user=public_user(user)), 201

    @app.post("/api/auth/login")
    def login():
        payload = json_payload()
        if isinstance(payload, tuple):
            return payload
        email = clean_email(payload.get("email"))
        password = payload.get("password")
        if isinstance(email, tuple):
            return email
        if not isinstance(password, str) or not password:
            return jsonify(error="email and password are required."), 400
        user = get_database().execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,)
        ).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            return jsonify(error="Email or password is incorrect."), 401
        user_dict = dict(user)
        return jsonify(token=create_token(user_dict), user=public_user(user_dict))

    @app.post("/api/complaints")
    @authenticated("citizen")
    def submit_complaint():
        if request.mimetype == "multipart/form-data":
            payload = request.form
            image = request.files.get("image")
        else:
            payload = request.get_json(silent=True) or {}
            image = None

        title = clean_text(payload.get("title"), "title", 3, 100)
        category = clean_text(payload.get("category"), "category", 1, 80)
        description = clean_text(payload.get("description", ""), "description", 0, 1200)
        location = clean_text(payload.get("location"), "location", 2, 300)
        for value in (title, category, description, location):
            if isinstance(value, tuple):
                return value
        if len(description) < 10 and not (image and image.filename):
            return jsonify(error="description must contain at least 10 characters unless a photo is provided."), 400

        coordinates = parse_coordinates(payload)
        latitude, longitude, coordinate_error = coordinates
        if coordinate_error:
            return coordinate_error
        filename = None
        if image and image.filename:
            try:
                filename = save_validated_image(image, app.config["UPLOAD_FOLDER"])
            except ValueError as error:
                return jsonify(error=str(error)), 400

        created_at = utc_now()
        complaint_id = f"CIV-{datetime.now(timezone.utc):%Y}-{secrets.token_hex(4).upper()}"
        db = get_database()
        if category not in DEPARTMENT_BY_CATEGORY:
            return jsonify(error="Select one of the supported complaint categories."), 400
        department = DEPARTMENT_BY_CATEGORY[category]
        active_model = db.execute(
            """SELECT artifact, model_version FROM ml_model_runs
               WHERE status = 'evaluated_advisory' AND artifact IS NOT NULL
               ORDER BY created_at DESC, id DESC LIMIT 1"""
        ).fetchone()
        if active_model:
            prediction = predict_with_tfidf_model(
                description,
                json.loads(active_model["artifact"]),
                app.config["ML_CONFIDENCE_THRESHOLD"],
            )
        else:
            prediction = {
                "category": None,
                "confidence": None,
                "model": "tfidf-logistic-regression",
                "model_version": None,
                "trained": False,
                "needs_review": True,
            }
        priority_prediction = predict_priority(category, description)
        urgency = analyze_urgency(description)
        priority = priority_prediction["priority"]
        stored_priority = "High" if priority == "Critical" else priority
        eta = estimate_completion(
            db, category, department, priority, datetime.now(timezone.utc),
            app.config["ETA_FALLBACK_HOURS"],
        )
        assignment_review_required = False
        review_reasons = []
        if not prediction["trained"]:
            review_reasons.append(
                "ML: no evaluated advisory model is available; manual verification requested."
            )
        elif prediction["needs_review"]:
            review_reasons.append(
                "ML: classifier confidence is below the configured review threshold."
            )
        review_reason = " ".join(review_reasons) or None
        try:
            db.execute(
                """INSERT INTO complaints (
                    complaint_id, citizen_id, title, category, description, image_path,
                    location, latitude, longitude, assigned_department, status, priority,
                    created_at, updated_at, legacy_source_id, assignment_review_required,
                    review_reason,
                    predicted_category, category_confidence, classifier_model,
                    predicted_priority, urgency_score, dissatisfaction_score,
                    sentiment_score, expected_completion_at, eta_method
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?, ?, NULL, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (complaint_id, g.current_user["id"], title, category, description,
                 filename, location, latitude, longitude, department, stored_priority,
                 created_at, created_at, int(assignment_review_required), review_reason,
                 prediction["category"], prediction["confidence"], prediction["model"],
                 priority, urgency["urgency_score"], urgency["dissatisfaction_score"],
                 urgency["sentiment_score"],
                 eta["expected_completion_at"], eta["method"]),
            )
            db.execute(
                """INSERT INTO complaint_status_history
                   (complaint_id, changed_by, old_status, new_status, note, changed_at)
                   VALUES (?, ?, NULL, 'Pending', 'Complaint submitted', ?)""",
                (complaint_id, g.current_user["id"], created_at),
            )
            record_department_assignment(
                db, complaint_id, department, None, g.current_user["id"], created_at,
                assignment_review_required=assignment_review_required,
                review_reason=review_reason,
            )
            db.commit()
        except Exception:
            db.rollback()
            if filename:
                safe_upload_path(app.config["UPLOAD_FOLDER"], filename).unlink(missing_ok=True)
            raise
        row = get_database().execute(
            complaint_select() + " WHERE c.complaint_id = ?", (complaint_id,)
        ).fetchone()
        try:
            dispatch_citizen_notification(
                app, complaint_id, f"{complaint_id}:assigned", "assigned",
                f"Your complaint was assigned to {department}.",
            )
        except Exception:
            app.logger.exception("Failed to dispatch assignment notifications for %s.", complaint_id)
        return jsonify(serialize_complaint(row)), 201

    @app.get("/api/complaints/mine")
    @authenticated("citizen")
    def citizen_complaints():
        rows = get_database().execute(
            complaint_select() + " WHERE c.citizen_id = ? ORDER BY c.created_at DESC",
            (g.current_user["id"],),
        ).fetchall()
        return jsonify(complaints=[serialize_complaint(row) for row in rows])

    @app.get("/api/department/complaints")
    @authenticated("department")
    def department_complaints():
        scope, params = department_complaint_scope(g.current_user["department"], "c")
        rows = get_database().execute(
            complaint_select()
            + f" WHERE {scope} ORDER BY c.created_at DESC",
            params,
        ).fetchall()
        return jsonify(complaints=[serialize_complaint(row) for row in rows])

    @app.patch("/api/department/complaints/<complaint_id>")
    @authenticated("department")
    def update_department_complaint(complaint_id):
        payload = json_payload()
        if isinstance(payload, tuple):
            return payload
        action_statuses = {
            "accept": "Accepted",
            "in_progress": "In progress",
            "complete": "Completed",
        }
        action = payload.get("action")
        status = action_statuses.get(action)
        if action and not status:
            return jsonify(error="action must be accept, in_progress, or complete."), 400
        note_value = payload.get("note")
        note = None
        if note_value is not None:
            note = clean_text(note_value, "note", 1, 1000)
            if isinstance(note, tuple):
                return note
        eta_value = payload.get("expected_completion_at")
        eta_datetime = None
        if eta_value is not None:
            if not isinstance(eta_value, str):
                return jsonify(error="expected_completion_at must be an ISO-8601 timestamp."), 400
            try:
                eta_datetime = datetime.fromisoformat(eta_value.replace("Z", "+00:00"))
            except ValueError:
                return jsonify(error="expected_completion_at must be a valid ISO-8601 timestamp."), 400
            if eta_datetime.tzinfo is None:
                return jsonify(error="expected_completion_at must include a timezone."), 400
            if eta_datetime <= datetime.now(timezone.utc):
                return jsonify(error="expected_completion_at must be in the future."), 400
        if not status and note is None and eta_datetime is None:
            return jsonify(error="Provide a department action, ETA update, or progress note."), 400

        db = get_database()
        department_scope, department_params = department_complaint_scope(
            g.current_user["department"]
        )
        current = db.execute(
            f"SELECT * FROM complaints WHERE complaint_id = ? AND {department_scope}",
            (complaint_id, *department_params),
        ).fetchone()
        if current is None:
            exists = db.execute(
                "SELECT 1 FROM complaints WHERE complaint_id = ?", (complaint_id,)
            ).fetchone()
            if exists:
                return jsonify(error="You are not authorized to update this department's complaint."), 403
            return jsonify(error="Complaint was not found."), 404

        old_status = current["workflow_status"] or (
            "Completed" if current["status"] == "Resolved" else current["status"]
        )
        if status:
            allowed = {
                "Accepted": {"Pending", "Accepted"},
                "In progress": {"Accepted", "In progress"},
                "Completed": {"In progress", "Completed"},
            }
            if old_status not in allowed[status]:
                return jsonify(error=f"A complaint must be accepted before it can be marked {status}."), 409
        now = utc_now()
        notification_events = []
        progress_note_id = None
        try:
            if status and status != old_status:
                db.execute(
                    """UPDATE complaints
                       SET workflow_status = ?, updated_at = ?,
                           accepted_by = CASE WHEN ? = 'Accepted' THEN ? ELSE accepted_by END,
                           accepted_at = CASE WHEN ? = 'Accepted' THEN ? ELSE accepted_at END
                       WHERE complaint_id = ? AND assigned_department = ?
                         AND COALESCE(workflow_status,
                             CASE WHEN status = 'Resolved' THEN 'Completed' ELSE status END) = ?""",
                    (status, now, status, g.current_user["id"], status, now,
                     complaint_id, g.current_user["department"], old_status),
                )
                if not db.execute("SELECT changes()").fetchone()[0]:
                    db.rollback()
                    return jsonify(error="The complaint changed concurrently; reload and try again."), 409
                if status == "Completed":
                    db.execute(
                        "UPDATE complaints SET overdue = 0 WHERE complaint_id = ?",
                        (complaint_id,),
                    )
                db.execute(
                    """INSERT INTO department_status_history
                       (complaint_id, changed_by, old_status, new_status, note, changed_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (complaint_id, g.current_user["id"], old_status, status, note, now),
                )
                if status in {"Accepted", "In progress", "Completed"}:
                    notification_kind = {
                        "Accepted": "complaint_accepted",
                        "In progress": "work_started",
                        "Completed": "work_completed",
                    }[status]
                    message = (
                        f"Complaint {complaint_id} was accepted by its department."
                        if status == "Accepted"
                        else f"Work has started on complaint {complaint_id}."
                        if status == "In progress"
                        else f"Complaint {complaint_id} has been completed."
                    )
                    create_notification(
                        db, current["citizen_id"], complaint_id,
                        notification_kind, message, now,
                    )
                    notification_events.append((notification_kind, message))
            if note:
                note_cursor = db.execute(
                    """INSERT INTO complaint_progress_notes
                       (complaint_id, author_id, note, created_at) VALUES (?, ?, ?, ?)""",
                    (complaint_id, g.current_user["id"], note, now),
                )
                progress_note_id = note_cursor.lastrowid
                if not status or status == old_status:
                    db.execute(
                        """UPDATE complaints SET updated_at = ?
                           WHERE complaint_id = ? AND assigned_department = ?""",
                        (now, complaint_id, g.current_user["department"]),
                    )
            if eta_datetime is not None:
                db.execute(
                    """UPDATE complaints SET expected_completion_at = ?,
                              eta_method = 'department officer estimate', updated_at = ?
                       WHERE complaint_id = ? AND assigned_department = ?""",
                    (eta_datetime.astimezone(timezone.utc).isoformat(timespec="seconds"),
                     now, complaint_id, g.current_user["department"]),
                )
                message = f"The estimated completion time for complaint {complaint_id} was updated."
                create_notification(
                    db, current["citizen_id"], complaint_id, "eta_updated", message, now,
                )
                notification_events.append(("eta_updated", message))
            if note:
                message = f"A progress note was added to complaint {complaint_id}: {note}"
                create_notification(
                    db, current["citizen_id"], complaint_id, "progress_note_added", message, now,
                )
                notification_events.append(("progress_note_added", message))
            db.commit()
        except Exception:
            db.rollback()
            raise
        row = db.execute(
            complaint_select() + " WHERE c.complaint_id = ?", (complaint_id,)
        ).fetchone()
        for notification_kind, notification_message in notification_events:
            try:
                dispatch_citizen_notification(
                    app, complaint_id,
                    (
                        f"{complaint_id}:progress_note:{progress_note_id}"
                        if notification_kind == "progress_note_added"
                        else f"{complaint_id}:{notification_kind}:{now}"
                    ),
                    notification_kind,
                    notification_message,
                    channels=("email",) if notification_kind == "progress_note_added" else ("sms", "email"),
                )
            except Exception:
                app.logger.exception(
                    "Failed to dispatch %s notifications for %s.",
                    notification_kind, complaint_id,
                )
        return jsonify(serialize_complaint(row))

    @app.get("/api/notifications")
    @authenticated("citizen", "department", "municipal", "admin")
    def list_notifications():
        rows = get_database().execute(
            """SELECT id, complaint_id, kind, message, created_at, read_at
               FROM notifications WHERE user_id = ?
               ORDER BY created_at DESC, id DESC LIMIT 50""",
            (g.current_user["id"],),
        ).fetchall()
        return jsonify(notifications=[dict(row) for row in rows])

    @app.patch("/api/notifications/<int:notification_id>/read")
    @authenticated("citizen", "department", "municipal", "admin")
    def mark_notification_read(notification_id):
        now = utc_now()
        result = get_database().execute(
            """UPDATE notifications SET read_at = ?
               WHERE id = ? AND user_id = ? AND read_at IS NULL""",
            (now, notification_id, g.current_user["id"]),
        )
        get_database().commit()
        if not result.rowcount:
            exists = get_database().execute(
                "SELECT 1 FROM notifications WHERE id = ? AND user_id = ?",
                (notification_id, g.current_user["id"]),
            ).fetchone()
            if not exists:
                return jsonify(error="Notification was not found."), 404
        return jsonify(read=True)

    @app.route("/api/account/notification-preferences", methods=["GET", "PATCH"])
    @authenticated("citizen")
    def notification_preferences():
        db = get_database()
        if request.method == "GET":
            user = db.execute(
                "SELECT phone, sms_consent FROM users WHERE id = ?",
                (g.current_user["id"],),
            ).fetchone()
            return jsonify(phone=user["phone"], sms_consent=bool(user["sms_consent"]))
        payload = json_payload()
        if isinstance(payload, tuple):
            return payload
        consent = payload.get("sms_consent")
        if not isinstance(consent, bool):
            return jsonify(error="sms_consent must be true or false."), 400
        user = db.execute(
            "SELECT phone FROM users WHERE id = ?", (g.current_user["id"],)
        ).fetchone()
        normalized_phone = normalize_indian_mobile(user["phone"])
        if consent and not normalized_phone:
            return jsonify(
                error="Add a valid Indian mobile number with a +91 country code before consenting to SMS updates."
            ), 400
        db.execute(
            "UPDATE users SET sms_consent = ?, phone = ? WHERE id = ?",
            (int(consent), normalized_phone if consent else user["phone"], g.current_user["id"]),
        )
        db.commit()
        return jsonify(
            phone=normalized_phone if consent else user["phone"],
            sms_consent=consent,
        )

    @app.get("/api/admin/notification-deliveries")
    @authenticated("admin")
    def notification_delivery_log():
        rows = get_database().execute(
            """SELECT id, complaint_id, channel, event_key, status,
                      failure_detail, attempts, created_at, updated_at
               FROM notification_deliveries
               ORDER BY created_at DESC LIMIT 200"""
        ).fetchall()
        return jsonify(deliveries=[dict(row) for row in rows])

    @app.get("/api/admin/ml-metrics")
    @authenticated("municipal", "admin")
    def ml_metrics():
        if g.current_user.get("department"):
            return jsonify(error="Department officers cannot access citywide model metrics."), 403
        rows = get_database().execute(
            """SELECT id, description, category FROM verified_training_examples
               ORDER BY created_at, id"""
        ).fetchall()
        return jsonify(evaluate_classifier(rows))

    @app.route("/api/municipal/category-mappings", methods=["GET", "PATCH"])
    @authenticated("municipal", "admin")
    def municipal_category_mappings():
        if g.current_user.get("department"):
            return jsonify(error="Department officers cannot edit citywide category mappings."), 403
        db = get_database()
        if request.method == "GET":
            mappings = [
                {
                    "category": category,
                    "department": department,
                    "verified": True,
                    "updated_at": None,
                }
                for category, department in sorted(DEPARTMENT_BY_CATEGORY.items())
            ]
            history = db.execute(
                """SELECT h.category, h.old_department, h.new_department, h.reason,
                          h.changed_at, u.name AS changed_by
                   FROM category_mapping_history h
                   JOIN users u ON u.id = h.changed_by
                   ORDER BY h.changed_at DESC, h.id DESC LIMIT 100"""
            ).fetchall()
            return jsonify(
                supported_categories=sorted(CATEGORIES),
                departments=sorted(DEPARTMENTS),
                mappings=mappings,
                history=[dict(row) for row in history],
            )
        payload = json_payload()
        if isinstance(payload, tuple):
            return payload
        return jsonify(error="Category routing is fixed to the approved municipal mapping."), 409

    @app.route("/api/municipal/ml-dataset", methods=["GET", "POST"])
    @authenticated("municipal", "admin")
    def municipal_ml_dataset():
        if g.current_user.get("department"):
            return jsonify(error="Department officers cannot manage the verified citywide dataset."), 403
        db = get_database()
        if request.method == "GET":
            rows = db.execute(
                """SELECT e.id, e.description, e.category, e.source_complaint_id,
                          e.verification_note, e.created_at, e.updated_at,
                          u.name AS verified_by
                   FROM verified_training_examples e JOIN users u ON u.id = e.verified_by
                   ORDER BY e.created_at DESC, e.id DESC LIMIT 500"""
            ).fetchall()
            latest_run = db.execute(
                """SELECT id, status, model_name, model_version, sample_count,
                          category_counts, metrics, created_at
                   FROM ml_model_runs ORDER BY created_at DESC, id DESC LIMIT 1"""
            ).fetchone()
            return jsonify(
                examples=[dict(row) for row in rows],
                model_run=(
                    {
                        **dict(latest_run),
                        "category_counts": json.loads(latest_run["category_counts"]),
                        "metrics": json.loads(latest_run["metrics"]),
                    }
                    if latest_run else None
                ),
            )
        payload = json_payload()
        if isinstance(payload, tuple):
            return payload
        category = clean_text(payload.get("category"), "category", 1, 80)
        note = clean_text(payload.get("verification_note"), "verification_note", 5, 500)
        source_id = payload.get("complaint_id")
        if isinstance(category, tuple):
            return category
        if isinstance(note, tuple):
            return note
        if category not in DEPARTMENT_BY_CATEGORY:
            return jsonify(error="The verified label must be a supported complaint category."), 400
        if source_id is not None:
            if not isinstance(source_id, str) or not source_id.strip():
                return jsonify(error="complaint_id must be a non-empty string."), 400
            source = db.execute(
                "SELECT description FROM complaints WHERE complaint_id = ?",
                (source_id.strip(),),
            ).fetchone()
            if source is None:
                return jsonify(error="Source complaint was not found."), 404
            description_value = source["description"]
        else:
            description_value = payload.get("description")
        description = clean_text(description_value, "description", 10, 1200)
        if isinstance(description, tuple):
            return description
        now = utc_now()
        try:
            cursor = db.execute(
                """INSERT INTO verified_training_examples
                   (description, category, source_complaint_id, verified_by,
                    verification_note, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (description, category, source_id.strip() if source_id else None,
                 g.current_user["id"], note, now, now),
            )
            example_id = cursor.lastrowid
            db.execute(
                """INSERT INTO verified_training_history
                   (example_id, action, new_description, new_category,
                    verification_note, changed_by, changed_at)
                   VALUES (?, 'added', ?, ?, ?, ?, ?)""",
                (example_id, description, category, note, g.current_user["id"], now),
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            return jsonify(error="This complaint already has a verified training label."), 409
        return jsonify(
            id=example_id, description=description, category=category,
            source_complaint_id=source_id, verification_note=note,
            created_at=now,
        ), 201

    @app.patch("/api/municipal/ml-dataset/<int:example_id>")
    @authenticated("municipal", "admin")
    def update_verified_training_example(example_id):
        if g.current_user.get("department"):
            return jsonify(error="Department officers cannot edit the verified citywide dataset."), 403
        payload = json_payload()
        if isinstance(payload, tuple):
            return payload
        description = clean_text(payload.get("description"), "description", 10, 1200)
        category = clean_text(payload.get("category"), "category", 1, 80)
        note = clean_text(payload.get("verification_note"), "verification_note", 5, 500)
        for value in (description, category, note):
            if isinstance(value, tuple):
                return value
        db = get_database()
        current = db.execute(
            "SELECT * FROM verified_training_examples WHERE id = ?", (example_id,)
        ).fetchone()
        if current is None:
            return jsonify(error="Verified training example was not found."), 404
        if category not in DEPARTMENT_BY_CATEGORY:
            return jsonify(error="The verified label must be a supported complaint category."), 400
        now = utc_now()
        db.execute(
            """UPDATE verified_training_examples
               SET description = ?, category = ?, verification_note = ?,
                   verified_by = ?, updated_at = ? WHERE id = ?""",
            (description, category, note, g.current_user["id"], now, example_id),
        )
        db.execute(
            """INSERT INTO verified_training_history
               (example_id, action, old_description, old_category, new_description,
                new_category, verification_note, changed_by, changed_at)
               VALUES (?, 'updated', ?, ?, ?, ?, ?, ?, ?)""",
            (example_id, current["description"], current["category"], description,
             category, note, g.current_user["id"], now),
        )
        db.commit()
        return jsonify(id=example_id, description=description, category=category, updated_at=now)

    @app.delete("/api/municipal/ml-dataset/<int:example_id>")
    @authenticated("municipal", "admin")
    def delete_verified_training_example(example_id):
        if g.current_user.get("department"):
            return jsonify(error="Department officers cannot edit the verified citywide dataset."), 403
        db = get_database()
        current = db.execute(
            "SELECT * FROM verified_training_examples WHERE id = ?", (example_id,)
        ).fetchone()
        if current is None:
            return jsonify(error="Verified training example was not found."), 404
        now = utc_now()
        db.execute(
            """INSERT INTO verified_training_history
               (example_id, action, old_description, old_category,
                verification_note, changed_by, changed_at)
               VALUES (?, 'removed', ?, ?, 'Verified example removed', ?, ?)""",
            (example_id, current["description"], current["category"],
             g.current_user["id"], now),
        )
        db.execute("DELETE FROM verified_training_examples WHERE id = ?", (example_id,))
        db.commit()
        return jsonify(removed=True, id=example_id)

    @app.post("/api/municipal/ml-model/retrain")
    @authenticated("municipal", "admin")
    def retrain_verified_classifier():
        return jsonify(error="Model retraining is disabled; the current model was not changed."), 409

    @app.post("/api/admin/notification-deliveries/<int:delivery_id>/retry")
    @authenticated("admin")
    def retry_notification_delivery(delivery_id):
        try:
            result = retry_delivery(app, delivery_id)
        except LookupError:
            return jsonify(error="Notification delivery was not found."), 404
        return jsonify(delivery=result)

    @app.get("/api/municipal/analytics")
    @authenticated("municipal", "admin")
    def municipal_analytics():
        if g.current_user.get("department"):
            return jsonify(error="Department officers must use their assigned queue."), 403
        db = get_database()
        department_rows = db.execute(
            """SELECT assigned_department AS department,
                      COUNT(*) AS total,
                      SUM(CASE WHEN COALESCE(workflow_status, status) IN ('Pending', 'Accepted') THEN 1 ELSE 0 END) AS pending,
                      SUM(CASE WHEN COALESCE(workflow_status, status) = 'In progress' THEN 1 ELSE 0 END) AS in_progress,
                      SUM(CASE WHEN COALESCE(workflow_status, status) IN ('Completed', 'Resolved') THEN 1 ELSE 0 END) AS completed,
                      SUM(CASE WHEN overdue = 1 THEN 1 ELSE 0 END) AS overdue,
                      SUM(CASE WHEN assignment_review_required = 1 THEN 1 ELSE 0 END) AS needs_review
               FROM complaints GROUP BY assigned_department ORDER BY assigned_department"""
        ).fetchall()
        hotspots = db.execute(
            """SELECT complaint_id, latitude, longitude FROM complaints
               WHERE latitude IS NOT NULL AND longitude IS NOT NULL"""
        ).fetchall()
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(hours=app.config["UNACCEPTED_AFTER_HOURS"])
        ).isoformat(timespec="seconds")
        escalations = db.execute(
            """SELECT complaint_id, category, assigned_department,
                      COALESCE(workflow_status, status) AS status, created_at,
                      expected_completion_at, overdue
               FROM complaints
               WHERE assignment_review_required = 1 OR overdue = 1
                  OR (COALESCE(workflow_status, status) = 'Pending' AND created_at <= ?)
               ORDER BY overdue DESC, created_at ASC""",
            (cutoff,),
        ).fetchall()
        delivery_counts = db.execute(
            """SELECT channel, status, COUNT(*) AS count
               FROM notification_deliveries GROUP BY channel, status"""
        ).fetchall()
        return jsonify(
            departments=[dict(row) for row in department_rows],
            hotspots=hotspot_clusters(hotspots),
            escalations=[dict(row) for row in escalations],
            notification_deliveries=[dict(row) for row in delivery_counts],
            gps_complaints=len(hotspots),
            gps_hotspot_precision="rounded to 0.01 degree; approximate cluster, not a surveyed boundary",
        )

    @app.get("/api/complaints/<complaint_id>/insights")
    @authenticated("citizen", "municipal", "admin", "department")
    def complaint_insights(complaint_id):
        db = get_database()
        target = db.execute(
            "SELECT * FROM complaints WHERE complaint_id = ?", (complaint_id,)
        ).fetchone()
        if target is None:
            return jsonify(error="Complaint was not found."), 404
        if g.current_user["role"] == "citizen" and target["citizen_id"] != g.current_user["id"]:
            return jsonify(error="You are not authorized to view this complaint."), 403
        if g.current_user["role"] == "department" and target["assigned_department"] != g.current_user["department"]:
            return jsonify(error="You are not authorized to view this complaint."), 403
        clauses = ["complaint_id != ?"]
        params = [complaint_id]
        if g.current_user["role"] == "department":
            clauses.append("assigned_department = ?")
            params.append(g.current_user["department"])
        candidates = db.execute(
            f"""SELECT complaint_id, category, title, description, workflow_status, status
                FROM complaints WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC LIMIT 500""",
            params,
        ).fetchall()
        return jsonify(
            selected_category=target["category"],
            assigned_department=target["assigned_department"],
            review_reason=target["review_reason"],
            classifier={
                "category": target["predicted_category"],
                "confidence": target["category_confidence"],
                "model": target["classifier_model"],
                "requires_review": bool(
                    target["review_reason"]
                    and "ML:" in target["review_reason"]
                ),
            },
            priority={
                "predicted": target["predicted_priority"],
                "assigned": target["priority"],
                "method": "transparent severity keyword rules",
            },
            urgency={
                "score": target["urgency_score"],
                "dissatisfaction_score": target["dissatisfaction_score"],
                "sentiment_score": target["sentiment_score"],
                "sentiment_label": (
                    "negative" if target["sentiment_score"] is not None and target["sentiment_score"] < -0.1
                    else "positive" if target["sentiment_score"] is not None and target["sentiment_score"] > 0.1
                    else "neutral/unknown"
                ),
                "method": "transparent keyword indicators; not an emotion or severity determination",
            },
            duplicates=similar_complaints(target, candidates),
            eta={
                "expected_completion_at": target["expected_completion_at"],
                "method": target["eta_method"],
                "is_guarantee": False,
            },
            accepted_at=target["accepted_at"],
        )

    @app.post("/api/complaints/<complaint_id>/feedback")
    @authenticated("citizen")
    def submit_complaint_feedback(complaint_id):
        payload = json_payload()
        if isinstance(payload, tuple):
            return payload
        rating = payload.get("rating")
        if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
            return jsonify(error="rating must be an integer from 1 to 5."), 400
        comment = payload.get("comment", "")
        if not isinstance(comment, str) or len(comment.strip()) > 1000:
            return jsonify(error="comment must be text of at most 1000 characters."), 400
        db = get_database()
        complaint = db.execute(
            """SELECT citizen_id, workflow_status, status FROM complaints
               WHERE complaint_id = ?""",
            (complaint_id,),
        ).fetchone()
        if complaint is None:
            return jsonify(error="Complaint was not found."), 404
        if complaint["citizen_id"] != g.current_user["id"]:
            return jsonify(error="You are not authorized to leave feedback for this complaint."), 403
        if (complaint["workflow_status"] or complaint["status"]) not in {"Completed", "Resolved"}:
            return jsonify(error="Feedback is available after the complaint is completed."), 409
        created_at = utc_now()
        try:
            db.execute(
                """INSERT INTO complaint_feedback
                   (complaint_id, citizen_id, rating, comment, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (complaint_id, g.current_user["id"], rating, comment.strip(), created_at),
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            return jsonify(error="Feedback has already been submitted for this complaint."), 409
        return jsonify(feedback={
            "complaint_id": complaint_id,
            "rating": rating,
            "comment": comment.strip(),
            "created_at": created_at,
        }), 201

    @app.get("/api/complaints")
    @authenticated("municipal", "admin")
    def managed_complaints():
        if g.current_user.get("department"):
            return jsonify(error="Use the department complaint queue for this account."), 403
        query = request.args.get("q", "").strip()[:120]
        category = request.args.get("category", "").strip()
        status = request.args.get("status", "").strip()
        clauses = []
        params = []
        if query:
            clauses.append("(c.complaint_id LIKE ? OR c.title LIKE ? OR c.description LIKE ? OR u.name LIKE ?)")
            params.extend([f"%{query}%"] * 4)
        if category:
            if category not in CATEGORIES:
                return jsonify(error="Unknown complaint category."), 400
            clauses.append("c.category = ?")
            params.append(category)
        if status:
            if status not in STATUSES | DEPARTMENT_STATUSES:
                return jsonify(error="Unknown complaint status."), 400
            clauses.append("c.status = ?")
            params.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = get_database().execute(
            complaint_select() + where + " ORDER BY c.created_at DESC", params
        ).fetchall()
        return jsonify(complaints=[serialize_complaint(row) for row in rows])

    @app.patch("/api/complaints/<complaint_id>")
    @authenticated("municipal", "admin")
    def update_complaint(complaint_id):
        if g.current_user["role"] == "municipal":
            return jsonify(error="Municipal officers have read-only access to complaints."), 403
        payload = json_payload()
        if isinstance(payload, tuple):
            return payload
        status = payload.get("status")
        department = payload.get("department")
        priority = payload.get("priority")
        if status is not None:
            return jsonify(
                error="Only the currently assigned department officer can change complaint status."
            ), 403
        if department is not None and department not in DEPARTMENTS:
            return jsonify(error="Select a supported municipal department."), 400
        if priority is not None and priority not in PRIORITIES:
            return jsonify(error="priority must be Low, Medium, or High."), 400
        if department is None and priority is None:
            return jsonify(error="Provide a department assignment or priority to update."), 400

        db = get_database()
        current = db.execute(
            "SELECT * FROM complaints WHERE complaint_id = ?", (complaint_id,)
        ).fetchone()
        if current is None:
            return jsonify(error="Complaint was not found."), 404
        if department is not None and department != DEPARTMENT_BY_CATEGORY.get(current["category"]):
            return jsonify(
                error="The complaint must remain assigned to the department mapped to its category."
            ), 409
        new_department = department or current["assigned_department"]
        new_priority = priority or current["priority"]
        department_changed = department is not None and department != current["assigned_department"]
        now = utc_now()
        try:
            db.execute(
                """UPDATE complaints
                   SET assigned_department = ?, priority = ?, updated_at = ?,
                       assignment_review_required = CASE WHEN ? THEN 0 ELSE assignment_review_required END,
                       review_reason = CASE WHEN ? THEN NULL ELSE review_reason END
                   WHERE complaint_id = ?""",
                (new_department, new_priority, now, int(department_changed),
                 int(department_changed), complaint_id),
            )
            if department_changed:
                record_department_assignment(
                    db, complaint_id, new_department, g.current_user["id"],
                    current["citizen_id"], now,
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        if department_changed:
            try:
                dispatch_citizen_notification(
                    app, complaint_id, f"{complaint_id}:assigned:{now}",
                    "assigned", f"Your complaint has been reassigned to {new_department}.",
                )
            except Exception:
                app.logger.exception("Failed to dispatch reassignment notifications for %s.", complaint_id)
        row = db.execute(
            complaint_select() + " WHERE c.complaint_id = ?", (complaint_id,)
        ).fetchone()
        return jsonify(serialize_complaint(row))

    @app.get("/api/complaints/<complaint_id>/history")
    @authenticated("citizen", "municipal", "admin", "department")
    def complaint_history(complaint_id):
        db = get_database()
        complaint = db.execute(
            "SELECT citizen_id, assigned_department FROM complaints WHERE complaint_id = ?", (complaint_id,)
        ).fetchone()
        if complaint is None:
            return jsonify(error="Complaint was not found."), 404
        if g.current_user["role"] == "citizen" and complaint["citizen_id"] != g.current_user["id"]:
            return jsonify(error="You are not authorized to view this complaint."), 403
        if g.current_user["role"] == "department" and complaint["assigned_department"] != g.current_user["department"]:
            return jsonify(error="You are not authorized to view this complaint."), 403
        legacy_rows = db.execute(
            """SELECT h.old_status, h.new_status, h.note, h.changed_at, u.name AS changed_by
               FROM complaint_status_history h JOIN users u ON u.id = h.changed_by
               WHERE h.complaint_id = ? ORDER BY h.changed_at DESC, h.id DESC""",
            (complaint_id,),
        ).fetchall()
        department_rows = db.execute(
            """SELECT h.old_status, h.new_status, h.note, h.changed_at, u.name AS changed_by
               FROM department_status_history h JOIN users u ON u.id = h.changed_by
               WHERE h.complaint_id = ?""",
            (complaint_id,),
        ).fetchall()
        history = sorted(
            [dict(row) for row in (*legacy_rows, *department_rows)],
            key=lambda row: row["changed_at"],
            reverse=True,
        )
        return jsonify(history=history)

    @app.get("/api/complaints/<complaint_id>/image")
    @authenticated("citizen", "municipal", "admin", "department")
    def complaint_image(complaint_id):
        row = get_database().execute(
            "SELECT citizen_id, image_path, assigned_department FROM complaints WHERE complaint_id = ?",
            (complaint_id,),
        ).fetchone()
        if row is None or not row["image_path"]:
            return jsonify(error="Complaint image was not found."), 404
        if g.current_user["role"] == "citizen" and row["citizen_id"] != g.current_user["id"]:
            return jsonify(error="You are not authorized to view this image."), 403
        if g.current_user["role"] == "department" and row["assigned_department"] != g.current_user["department"]:
            return jsonify(error="You are not authorized to view this image."), 403
        path = safe_upload_path(app.config["UPLOAD_FOLDER"], row["image_path"])
        if not path.is_file():
            return jsonify(error="Complaint image file is missing."), 404
        return send_file(path, conditional=True, max_age=0)

    @app.get("/api/dashboard/summary")
    @authenticated("citizen", "municipal", "admin", "department")
    def dashboard_summary():
        db = get_database()
        role = g.current_user["role"]
        where = ""
        params = ()
        if role == "citizen":
            where = " WHERE citizen_id = ?"
            params = (g.current_user["id"],)
        elif role == "department":
            where, params = department_complaint_scope(g.current_user["department"])
            where = f" WHERE {where}"
        rows = db.execute(
            f"""SELECT COALESCE(workflow_status, status) AS status, COUNT(*) AS count
                FROM complaints{where} GROUP BY COALESCE(workflow_status, status)""",
            params,
        ).fetchall()
        counts = {status: 0 for status in STATUSES | DEPARTMENT_STATUSES}
        counts.update({row["status"]: row["count"] for row in rows})
        total = sum(counts.values())
        pending_count = counts["Pending"] + counts["Accepted"]
        completed_count = counts["Completed"] + counts["Resolved"]
        summary = {
            "total": total,
            "pending": pending_count,
            "in_progress": counts["In progress"],
            "completed": completed_count,
            "resolved": completed_count,
            "resolution_rate": round(completed_count * 100 / total) if total else 0,
        }
        summary["monthly"] = monthly_complaint_counts(
            db,
            g.current_user["id"] if role == "citizen" else None,
            g.current_user["department"] if role == "department" else None,
            department_categories=(
                department_categories(g.current_user["department"])
                if role == "department" else None
            ),
        )
        if role in {"municipal", "admin"}:
            summary["citizen_count"] = db.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'citizen'"
            ).fetchone()[0]
            summary["overdue"] = db.execute(
                "SELECT COUNT(*) FROM complaints WHERE overdue = 1"
            ).fetchone()[0]
            summary["by_category"] = query_counts(db, "category")
            summary["by_department"] = query_counts(db, "assigned_department")
            summary["needs_review"] = db.execute(
                "SELECT COUNT(*) FROM complaints WHERE assignment_review_required = 1"
            ).fetchone()[0]
        return jsonify(summary)

    @app.get("/api/admin/citizens")
    @authenticated("admin")
    def admin_citizens():
        rows = get_database().execute(
            """SELECT u.id, u.name, u.email, u.created_at,
                      COUNT(c.complaint_id) AS complaint_count,
                      SUM(CASE WHEN c.status = 'Pending' THEN 1 ELSE 0 END) AS pending_count,
                      SUM(CASE WHEN c.status = 'Resolved' THEN 1 ELSE 0 END) AS resolved_count
               FROM users u LEFT JOIN complaints c ON c.citizen_id = u.id
               WHERE u.role = 'citizen'
               GROUP BY u.id, u.name, u.email, u.created_at
               ORDER BY complaint_count DESC, u.created_at DESC"""
        ).fetchall()
        citizens = []
        for row in rows:
            citizen = dict(row)
            citizen["pending_count"] = citizen["pending_count"] or 0
            citizen["resolved_count"] = citizen["resolved_count"] or 0
            citizen["resolution_rate"] = (
                round(citizen["resolved_count"] * 100 / citizen["complaint_count"])
                if citizen["complaint_count"] else 0
            )
            citizens.append(citizen)
        return jsonify(citizens=citizens)

    @app.post("/api/complaints/import")
    @authenticated("citizen")
    def import_legacy_complaints():
        payload = json_payload()
        if isinstance(payload, tuple):
            return payload
        entries = payload.get("complaints")
        if not isinstance(entries, list) or not entries or len(entries) > 100:
            return jsonify(error="Select a backup containing between 1 and 100 complaints."), 400

        imported = []
        db = get_database()
        created_files = []
        try:
            for entry in entries:
                validated = validate_imported_entry(entry)
                if isinstance(validated, tuple):
                    raise ValueError(validated[0].get_json()["error"])
                image_name = None
                data_url = validated.pop("image_data")
                if data_url:
                    image_stream = data_url_to_file(data_url)
                    image_name = save_validated_image(image_stream, app.config["UPLOAD_FOLDER"])
                    created_files.append(image_name)
                now = utc_now()
                complaint_id = f"CIV-{datetime.now(timezone.utc):%Y}-{secrets.token_hex(4).upper()}"
                db.execute(
                    """INSERT INTO complaints (
                        complaint_id, citizen_id, title, category, description, image_path,
                        location, latitude, longitude, assigned_department, status, priority,
                        created_at, updated_at, legacy_source_id, assignment_review_required
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Medium', ?, ?, ?, ?)""",
                    (complaint_id, g.current_user["id"], validated["title"],
                     validated["category"], validated["description"], image_name,
                     validated["location"], None, None, validated["department"],
                     validated["status"], now, now, validated["legacy_source_id"],
                     int(validated["assignment_review_required"])),
                )
                db.execute(
                    """INSERT INTO complaint_status_history
                       (complaint_id, changed_by, old_status, new_status, note, changed_at)
                       VALUES (?, ?, NULL, ?, 'Imported from citizen browser backup', ?)""",
                    (complaint_id, g.current_user["id"], validated["status"], now),
                )
                record_department_assignment(
                    db, complaint_id, validated["department"], None,
                    g.current_user["id"], now,
                    assignment_review_required=validated["assignment_review_required"],
                )
                imported.append(complaint_id)
            db.commit()
        except ValueError as error:
            db.rollback()
            for filename in created_files:
                safe_upload_path(app.config["UPLOAD_FOLDER"], filename).unlink(missing_ok=True)
            return jsonify(error=f"Backup import failed; no complaints were imported. {error}"), 400
        except sqlite3.IntegrityError:
            db.rollback()
            for filename in created_files:
                safe_upload_path(app.config["UPLOAD_FOLDER"], filename).unlink(missing_ok=True)
            return jsonify(error="This backup includes complaints already imported into your account. No complaints were imported."), 409
        return jsonify(imported_ids=imported, count=len(imported)), 201

    return app


def create_notification(database, user_id, complaint_id, kind, message, created_at):
    database.execute(
        """INSERT INTO notifications
           (user_id, complaint_id, kind, message, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, complaint_id, kind, message, created_at),
    )


def record_department_assignment(
    database, complaint_id, department, assigned_by, citizen_id, now,
    assignment_review_required=False, review_reason=None,
):
    database.execute(
        """INSERT INTO complaint_department_history
           (complaint_id, department, assigned_by, assigned_at)
           VALUES (?, ?, ?, ?)""",
        (complaint_id, department, assigned_by, now),
    )
    if assignment_review_required:
        message = f"Complaint {complaint_id} needs municipal review: {review_reason or 'assignment requires review.'}"
    else:
        message = f"Complaint {complaint_id} has been assigned to {department}."
    kind = "assignment_review_required" if assignment_review_required else "assigned"
    citizen_kind = "assigned" if department != UNASSIGNED_DEPARTMENT else kind
    citizen_message = (
        f"Complaint {complaint_id} has been assigned to {department}."
        if department != UNASSIGNED_DEPARTMENT
        else message
    )
    if assignment_review_required and department != UNASSIGNED_DEPARTMENT:
        citizen_message += " The category suggestion is flagged for municipal review."
    create_notification(database, citizen_id, complaint_id, citizen_kind, citizen_message, now)
    if assignment_review_required:
        department_users = database.execute(
            """SELECT id FROM users WHERE role = 'admin'
               OR (role = 'municipal' AND department = ?)
               OR (role = 'municipal' AND department IS NULL AND ? = ?)""",
            (department, department, UNASSIGNED_DEPARTMENT),
        ).fetchall()
    else:
        department_users = database.execute(
            "SELECT id FROM users WHERE role = 'municipal' AND department = ?",
            (department,),
        ).fetchall()
    for user in department_users:
        create_notification(database, user["id"], complaint_id, kind, message, now)


def overdue_scheduler(application):
    interval = max(60, application.config["OVERDUE_REMINDER_INTERVAL_SECONDS"])
    while True:
        try:
            send_overdue_reminders(application)
        except Exception:
            application.logger.exception("The overdue reminder job failed.")
        threading.Event().wait(interval)


def send_overdue_reminders(application):
    now = datetime.now(timezone.utc)
    due_before = (now - timedelta(hours=application.config["OVERDUE_AFTER_HOURS"])).isoformat(timespec="seconds")
    remind_after = (now - timedelta(hours=24)).isoformat(timespec="seconds")
    unaccepted_before = (
        now - timedelta(hours=application.config["UNACCEPTED_AFTER_HOURS"])
    ).isoformat(timespec="seconds")
    timestamp = now.isoformat(timespec="seconds")
    connection = sqlite3.connect(application.config["DATABASE"])
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    external_events = []
    try:
        due_complaints = connection.execute(
            """SELECT complaint_id, citizen_id, assigned_department
               FROM complaints
               WHERE created_at <= ?
                 AND COALESCE(workflow_status, status) NOT IN ('Resolved', 'Completed')
                 AND (last_overdue_reminder_at IS NULL OR last_overdue_reminder_at <= ?)""",
            (due_before, remind_after),
        ).fetchall()
        for complaint in due_complaints:
            updated = connection.execute(
                """UPDATE complaints SET overdue = 1, last_overdue_reminder_at = ?
                   WHERE complaint_id = ? AND
                     (last_overdue_reminder_at IS NULL OR last_overdue_reminder_at <= ?)""",
                (timestamp, complaint["complaint_id"], remind_after),
            )
            if not updated.rowcount:
                continue
            message = f"Complaint {complaint['complaint_id']} is overdue and needs attention."
            external_events.append((complaint["complaint_id"], "overdue", message))
            create_notification(
                connection, complaint["citizen_id"], complaint["complaint_id"],
                "overdue", message, timestamp,
            )
            department_users = connection.execute(
                "SELECT id FROM users WHERE role = 'municipal' AND department = ?",
                (complaint["assigned_department"],),
            ).fetchall()
            for user in department_users:
                create_notification(
                    connection, user["id"], complaint["complaint_id"],
                    "overdue", message, timestamp,
                )
        escalated = connection.execute(
            """SELECT complaint_id, citizen_id, assigned_department
               FROM complaints
               WHERE COALESCE(workflow_status, status) = 'Pending'
                 AND created_at <= ?
                 AND (last_escalated_at IS NULL OR last_escalated_at <= ?)""",
            (unaccepted_before, remind_after),
        ).fetchall()
        for complaint in escalated:
            updated = connection.execute(
                """UPDATE complaints SET last_escalated_at = ?
                   WHERE complaint_id = ? AND
                     (last_escalated_at IS NULL OR last_escalated_at <= ?)""",
                (timestamp, complaint["complaint_id"], remind_after),
            )
            if not updated.rowcount:
                continue
            message = (
                f"Complaint {complaint['complaint_id']} has not been accepted within "
                f"{application.config['UNACCEPTED_AFTER_HOURS']} hours and needs escalation."
            )
            external_events.append((
                complaint["complaint_id"], "unaccepted_escalation", message,
            ))
            managers = connection.execute(
                """SELECT id FROM users
                   WHERE role = 'admin'
                      OR (role = 'municipal' AND department IS NULL)"""
            ).fetchall()
            for user in managers:
                create_notification(
                    connection, user["id"], complaint["complaint_id"],
                    "unaccepted_escalation", message, timestamp,
                )
            officers = connection.execute(
                "SELECT id FROM users WHERE role = 'municipal' AND department = ?",
                (complaint["assigned_department"],),
            ).fetchall()
            for user in officers:
                create_notification(
                    connection, user["id"], complaint["complaint_id"],
                    "unaccepted_escalation", message, timestamp,
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    deduplicated_events = {}
    for complaint_id, kind, message in external_events:
        if complaint_id in deduplicated_events:
            _, previous_message = deduplicated_events[complaint_id]
            deduplicated_events[complaint_id] = (
                "escalation_reminder",
                f"{previous_message} {message}",
            )
        else:
            deduplicated_events[complaint_id] = (kind, message)
    for complaint_id, (kind, message) in deduplicated_events.items():
        try:
            dispatch_citizen_notification(
                application, complaint_id,
                f"{complaint_id}:{kind}:{timestamp}", kind, message,
            )
        except Exception:
            application.logger.exception(
                "Failed to dispatch %s notifications for %s.", kind, complaint_id
            )


def initialize_database(app):
    database = Path(app.config["DATABASE"])
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        existing = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'complaints'"
        ).fetchone()
        if existing:
            complaint_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(complaints)")
            }
            user_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(users)")
            }
            additions = {
                "legacy_source_id": "TEXT",
                "priority": "TEXT NOT NULL DEFAULT 'Medium' CHECK (priority IN ('Low', 'Medium', 'High'))",
                "workflow_status": "TEXT CHECK (workflow_status IN ('Pending', 'Accepted', 'In progress', 'Completed'))",
                "last_overdue_reminder_at": "TEXT",
                "assignment_review_required": "INTEGER NOT NULL DEFAULT 0 CHECK (assignment_review_required IN (0, 1))",
                "review_reason": "TEXT",
                "predicted_category": "TEXT",
                "category_confidence": "REAL",
                "classifier_model": "TEXT",
                "predicted_priority": "TEXT",
                "urgency_score": "REAL",
                "dissatisfaction_score": "REAL",
                "sentiment_score": "REAL",
                "expected_completion_at": "TEXT",
                "eta_method": "TEXT",
                "accepted_by": "TEXT REFERENCES users(id)",
                "accepted_at": "TEXT",
                "last_escalated_at": "TEXT",
            }
            for name, definition in additions.items():
                if name not in complaint_columns:
                    connection.execute(f"ALTER TABLE complaints ADD COLUMN {name} {definition}")
            if "department" not in user_columns:
                connection.execute("ALTER TABLE users ADD COLUMN department TEXT")
            if "sms_consent" not in user_columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN sms_consent INTEGER NOT NULL DEFAULT 0 CHECK (sms_consent IN (0, 1))"
                )
            connection.commit()
        connection.executescript((BASE_DIR / "schema.sql").read_text(encoding="utf-8"))
        delivery_table = connection.execute(
            """SELECT sql FROM sqlite_master
               WHERE type = 'table' AND name = 'notification_deliveries'"""
        ).fetchone()
        if delivery_table and "'delivered'" not in delivery_table[0]:
            connection.execute("DROP INDEX IF EXISTS idx_notification_deliveries_status")
            connection.execute(
                "ALTER TABLE notification_deliveries RENAME TO notification_deliveries_legacy"
            )
            connection.execute(
                """CREATE TABLE notification_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    complaint_id TEXT NOT NULL REFERENCES complaints(complaint_id) ON DELETE CASCADE,
                    channel TEXT NOT NULL CHECK (channel IN ('sms', 'email')),
                    event_key TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('pending', 'sent', 'delivered', 'failed', 'skipped', 'not_configured')
                    ),
                    provider_response TEXT,
                    failure_detail TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (complaint_id, channel, event_key)
                )"""
            )
            connection.execute(
                """INSERT INTO notification_deliveries
                   (id, user_id, complaint_id, channel, event_key, status,
                    provider_response, failure_detail, attempts, created_at, updated_at)
                   SELECT id, user_id, complaint_id, channel, event_key, status,
                          provider_response, failure_detail, attempts, created_at, updated_at
                   FROM notification_deliveries_legacy"""
            )
            connection.execute("DROP TABLE notification_deliveries_legacy")
            connection.execute(
                """CREATE INDEX idx_notification_deliveries_status
                   ON notification_deliveries(status, created_at DESC)"""
            )
            connection.commit()
        delivery_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(notification_deliveries)")
        }
        if "message" not in delivery_columns:
            connection.execute("ALTER TABLE notification_deliveries ADD COLUMN message TEXT")
        if "progress_note" not in delivery_columns:
            connection.execute("ALTER TABLE notification_deliveries ADD COLUMN progress_note TEXT")
        connection.commit()
        migration_timestamp = utc_now()
        connection.executemany(
            """INSERT OR IGNORE INTO category_department_mappings
               (category, department, verified, updated_by, updated_at)
               VALUES (?, ?, 1, NULL, ?)""",
            [
                (category, department, migration_timestamp)
                for category, department in DEPARTMENT_BY_CATEGORY.items()
            ],
        )
        connection.execute(
            """INSERT INTO complaint_department_history
               (complaint_id, department, assigned_by, assigned_at)
               SELECT c.complaint_id, c.assigned_department, NULL, c.created_at
               FROM complaints c
               WHERE NOT EXISTS (
                   SELECT 1 FROM complaint_department_history h
                   WHERE h.complaint_id = c.complaint_id
               )"""
        )
        connection.commit()
    finally:
        connection.close()


def get_database():
    if "database" not in g:
        connection = sqlite3.connect(current_app_database())
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        g.database = connection
    return g.database


def current_app_database():
    from flask import current_app

    return current_app.config["DATABASE"]


def json_payload():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="A JSON object request body is required."), 400
    return payload


def clean_text(value, field, minimum, maximum):
    if not isinstance(value, str):
        return jsonify(error=f"{field} must be text."), 400
    value = value.strip()
    if not minimum <= len(value) <= maximum:
        return jsonify(error=f"{field} must contain {minimum} to {maximum} characters."), 400
    return value


def clean_email(value):
    if not isinstance(value, str):
        return jsonify(error="A valid email address is required."), 400
    email = value.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify(error="A valid email address is required."), 400
    return email


def validate_password(password):
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        return jsonify(error="Password must contain between 10 and 128 characters."), 400
    return password


def parse_coordinates(payload):
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    if latitude in (None, "") and longitude in (None, ""):
        return None, None, None
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return None, None, (jsonify(error="Latitude and longitude must be numeric and provided together."), 400)
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None, None, (jsonify(error="Latitude or longitude is outside the valid range."), 400)
    return latitude, longitude, None


def save_validated_image(file_storage, upload_folder):
    if not file_storage or not file_storage.filename:
        raise ValueError("Choose an image file.")
    if file_storage.content_length and file_storage.content_length > MAX_IMAGE_BYTES:
        raise ValueError("Image must be 5 MB or smaller.")
    safe_name = secure_filename(file_storage.filename)
    if not safe_name:
        raise ValueError("Image filename is invalid.")
    try:
        file_storage.stream.seek(0)
        with Image.open(file_storage.stream) as image:
            image_format = image.format
            if image_format not in ALLOWED_IMAGE_FORMATS:
                raise ValueError("Only JPEG, PNG, and WebP images are accepted.")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("Image dimensions are too large.")
            image.verify()
        file_storage.stream.seek(0)
        with Image.open(file_storage.stream) as image:
            image.load()
            if image_format == "JPEG":
                image = image.convert("RGB")
            filename = f"{uuid.uuid4().hex}.{ALLOWED_IMAGE_FORMATS[image_format]}"
            image.save(safe_upload_path(upload_folder, filename), format=image_format, optimize=True)
            return filename
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("The uploaded file is not a valid supported image.") from error


def safe_upload_path(upload_folder, filename):
    path = Path(upload_folder).resolve()
    candidate = (path / filename).resolve()
    if candidate.parent != path:
        raise ValueError("Invalid image path.")
    return candidate


def data_url_to_file(value):
    import base64
    import io

    if not isinstance(value, str) or not value.startswith("data:image/") or "," not in value:
        raise ValueError("A legacy image must be a valid image data URL.")
    header, encoded = value.split(",", 1)
    if header.split(";")[0] not in {"data:image/jpeg", "data:image/png", "data:image/webp"}:
        raise ValueError("Legacy image type is not supported.")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ValueError("Legacy image data is invalid.") from error
    if not decoded or len(decoded) > MAX_IMAGE_BYTES:
        raise ValueError("Legacy image exceeds the 5 MB limit.")
    from werkzeug.datastructures import FileStorage

    extension = header.split(";")[0].split("/")[-1]
    return FileStorage(
        stream=__import__("io").BytesIO(decoded),
        filename=f"legacy.{extension}",
        content_length=len(decoded),
    )


def validate_imported_entry(entry):
    if not isinstance(entry, dict):
        return jsonify(error="Each legacy complaint must be a JSON object."), 400
    legacy_source_id = entry.get("id")
    if not isinstance(legacy_source_id, str) or not legacy_source_id.strip():
        return jsonify(error="Every legacy complaint must have its original complaint ID."), 400
    title = clean_text(entry.get("title"), "title", 3, 100)
    category = clean_text(entry.get("category"), "category", 1, 80)
    description = entry.get("description") or "Imported legacy report (no description was saved)."
    description = clean_text(description, "description", 10, 1200)
    location = clean_text(entry.get("location"), "location", 2, 300)
    for value in (title, category, description, location):
        if isinstance(value, tuple):
            return value
    if category not in CATEGORIES:
        return jsonify(error=f"Unsupported legacy complaint category: {category}."), 400
    department = DEPARTMENT_BY_CATEGORY.get(category)
    assignment_review_required = department is None
    status = entry.get("status", "Pending")
    if status not in STATUSES:
        return jsonify(error="Legacy complaint has an unsupported status."), 400
    return {
        "title": title,
        "category": category,
        "description": description,
        "location": location,
        "department": department or UNASSIGNED_DEPARTMENT,
        "assignment_review_required": assignment_review_required,
        "status": status,
        "legacy_source_id": legacy_source_id.strip()[:100],
        "image_data": entry.get("image") or "",
    }


def complaint_select():
    return """SELECT c.*, u.name AS citizen_name,
                     (SELECT n.note FROM complaint_progress_notes n
                      WHERE n.complaint_id = c.complaint_id
                      ORDER BY n.created_at DESC, n.id DESC LIMIT 1) AS latest_progress_note,
                     (SELECT f.rating FROM complaint_feedback f
                      WHERE f.complaint_id = c.complaint_id) AS feedback_rating,
                     (SELECT f.comment FROM complaint_feedback f
                      WHERE f.complaint_id = c.complaint_id) AS feedback_comment
              FROM complaints c JOIN users u ON u.id = c.citizen_id"""


def serialize_complaint(row):
    return {
        "id": row["complaint_id"],
        "title": row["title"],
        "citizen_id": row["citizen_id"],
        "citizen": row["citizen_name"],
        "category": row["category"],
        "selected_category": row["category"],
        "description": row["description"],
        "image_url": f"/api/complaints/{row['complaint_id']}/image" if row["image_path"] else "",
        "location": row["location"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "department": row["assigned_department"],
        "assigned_department": row["assigned_department"],
        "assignment_review_required": bool(row["assignment_review_required"]),
        "prediction_needs_review": bool(
            row["review_reason"] and "ML:" in row["review_reason"]
        ),
        "prediction_needs_review": bool(
            row["review_reason"] and row["review_reason"].startswith("ML:")
        ),
        "review_reason": row["review_reason"],
        "status": row["workflow_status"] or row["status"],
        "latest_progress_note": row["latest_progress_note"],
        "feedback_rating": row["feedback_rating"],
        "feedback_comment": row["feedback_comment"],
        "priority": row["priority"],
        "predicted_priority": row["predicted_priority"],
        "predicted_category": row["predicted_category"],
        "category_confidence": row["category_confidence"],
        "classifier_model": row["classifier_model"],
        "urgency_score": row["urgency_score"],
        "dissatisfaction_score": row["dissatisfaction_score"],
        "sentiment_score": row["sentiment_score"],
        "expected_completion_at": row["expected_completion_at"],
        "eta_method": row["eta_method"],
        "accepted_at": row["accepted_at"],
        "overdue": bool(row["overdue"]),
        "date": row["created_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def query_counts(database, field):
    if field not in {"category", "assigned_department"}:
        raise ValueError("Unsupported aggregation field.")
    rows = database.execute(
        f"SELECT {field} AS name, COUNT(*) AS count FROM complaints GROUP BY {field}"
    ).fetchall()
    return [dict(row) for row in rows]


def department_categories(department):
    return tuple(
        category
        for category, assigned_department in DEPARTMENT_BY_CATEGORY.items()
        if assigned_department == department
    )


def department_complaint_scope(department, alias=""):
    categories = department_categories(department)
    if not categories:
        return "0", ()
    prefix = f"{alias}." if alias else ""
    placeholders = ", ".join("?" for _ in categories)
    return (
        f"{prefix}assigned_department = ? AND {prefix}category IN ({placeholders})",
        (department, *categories),
    )


def monthly_complaint_counts(
    database, citizen_id=None, department=None, department_categories=None
):
    now = datetime.now(timezone.utc)
    first_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_month = first_month
    for _ in range(5):
        start_month = (start_month - timedelta(days=1)).replace(day=1)
    start = start_month.isoformat(timespec="seconds")
    citizen_filter = " AND c.citizen_id = ?" if citizen_id else ""
    citizen_params = (citizen_id,) if citizen_id else ()
    department_filter = " AND c.assigned_department = ?" if department else ""
    department_params = (department,) if department else ()
    category_filter = ""
    category_params = ()
    if department and department_categories:
        placeholders = ", ".join("?" for _ in department_categories)
        category_filter = f" AND c.category IN ({placeholders})"
        category_params = tuple(department_categories)

    received_rows = database.execute(
        f"""SELECT strftime('%Y-%m', c.created_at) AS month, COUNT(*) AS count
            FROM complaints c
            WHERE c.created_at >= ?{citizen_filter}{department_filter}{category_filter}
            GROUP BY month""",
        (start, *citizen_params, *department_params, *category_params),
    ).fetchall()
    resolved_rows = database.execute(
        f"""SELECT strftime('%Y-%m', history.changed_at) AS month, COUNT(*) AS count
            FROM (
                SELECT complaint_id, changed_at FROM complaint_status_history
                WHERE new_status = 'Resolved'
                UNION ALL
                SELECT complaint_id, changed_at FROM department_status_history
                WHERE new_status = 'Completed'
            ) history
            JOIN complaints c ON c.complaint_id = history.complaint_id
            WHERE history.changed_at >= ?{citizen_filter}{department_filter}{category_filter}
            GROUP BY month""",
        (start, *citizen_params, *department_params, *category_params),
    ).fetchall()
    received = {row["month"]: row["count"] for row in received_rows}
    resolved = {row["month"]: row["count"] for row in resolved_rows}

    months = []
    current_month = start_month
    for _ in range(6):
        month_key = current_month.strftime("%Y-%m")
        months.append({
            "month": current_month.strftime("%b"),
            "received": received.get(month_key, 0),
            "resolved": resolved.get(month_key, 0),
        })
        next_month = (current_month.replace(day=28) + timedelta(days=4)).replace(day=1)
        current_month = next_month
    return months


def public_user(user):
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": "department" if user.get("department") else user["role"],
        "department": user.get("department"),
    }


def create_token(user):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user["id"],
            "role": user["role"],
            "iat": now,
            "exp": now + timedelta(minutes=current_app_config("ACCESS_TOKEN_MINUTES")),
        },
        current_app_config("JWT_SECRET"),
        algorithm="HS256",
    )


def current_app_config(key):
    from flask import current_app

    return current_app.config[key]


def authenticated(*roles):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            scheme, _, token = header.partition(" ")
            if scheme.lower() != "bearer" or not token:
                return jsonify(error="A bearer access token is required."), 401
            try:
                claims = jwt.decode(
                    token,
                    current_app_config("JWT_SECRET"),
                    algorithms=["HS256"],
                    options={"require": ["sub", "role", "exp"]},
                )
            except jwt.ExpiredSignatureError:
                return jsonify(error="Access token expired. Please sign in again."), 401
            except jwt.InvalidTokenError:
                return jsonify(error="Access token is invalid."), 401
            user = get_database().execute(
                "SELECT id, name, email, role, department FROM users WHERE id = ?", (claims["sub"],)
            ).fetchone()
            if user is None or claims.get("role") != user["role"]:
                return jsonify(error="Account is no longer authorized."), 401
            effective_role = "department" if user["department"] else user["role"]
            if roles and effective_role not in roles:
                return jsonify(error="Your account is not authorized for this action."), 403
            g.current_user = dict(user)
            g.current_user["role"] = effective_role
            return view(*args, **kwargs)
        return wrapped
    return decorate


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
