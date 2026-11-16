import json
import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

os.environ.setdefault("SECRET_KEY", "test-secret-that-is-not-used-outside-tests")

from app import (
    CATEGORIES,
    DEPARTMENT_BY_CATEGORY,
    DEPARTMENTS,
    create_app,
)


class CivicApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.app = create_app({
            "TESTING": True,
            "JWT_SECRET": "test-secret-that-is-not-used-outside-tests",
            "DATABASE": str(root / "data.sqlite"),
            "UPLOAD_FOLDER": str(root / "uploads"),
            "FRONTEND_ORIGINS": {"http://localhost:5173"},
        })
        self.client = self.app.test_client()
        response = self.client.post("/api/auth/register", json={
            "name": "Citizen Tester",
            "email": "citizen@example.test",
            "password": "sample-test-password",
        })
        self.assertEqual(response.status_code, 201)
        self.citizen_token = response.json["token"]
        self.citizen_id = response.json["user"]["id"]
        self.citizen_headers = {"Authorization": f"Bearer {self.citizen_token}"}
        self._create_staff("officer@example.test", "municipal")
        self._create_staff("admin@example.test", "admin")

    def tearDown(self):
        self.temporary.cleanup()

    def _create_staff(self, email, role):
        from werkzeug.security import generate_password_hash
        import sqlite3
        import uuid
        from datetime import datetime, timezone

        connection = sqlite3.connect(self.app.config["DATABASE"])
        try:
            connection.execute(
                """INSERT INTO users (id, name, email, password_hash, role, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), role.title(), email, generate_password_hash("sample-staff-password"),
                 role, datetime.now(timezone.utc).isoformat()),
            )
            connection.commit()
        finally:
            connection.close()

    def _create_department_staff(self, email, department):
        from werkzeug.security import generate_password_hash
        import sqlite3
        import uuid
        from datetime import datetime, timezone

        connection = sqlite3.connect(self.app.config["DATABASE"])
        try:
            connection.execute(
                """INSERT INTO users
                   (id, name, email, password_hash, role, department, created_at)
                   VALUES (?, ?, ?, ?, 'municipal', ?, ?)""",
                (str(uuid.uuid4()), department + " Officer", email,
                 generate_password_hash("sample-staff-password"), department,
                 datetime.now(timezone.utc).isoformat()),
            )
            connection.commit()
        finally:
            connection.close()

    def _token(self, email, role):
        response = self.client.post("/api/auth/login", json={
            "email": email, "password": "sample-staff-password",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["user"]["role"], role)
        return {"Authorization": f"Bearer {response.json['token']}"}

    def test_citizen_complaint_is_shared_and_status_history_is_saved(self):
        response = self.client.post("/api/complaints", headers=self.citizen_headers, json={
            "title": "Road pothole near park",
            "category": "Roads & pathways",
            "description": "A large pothole is creating a hazard near the park.",
            "location": "Lakeview Road",
        })
        self.assertEqual(response.status_code, 201)
        complaint_id = response.json["id"]
        officer_headers = self._token("officer@example.test", "municipal")
        listing = self.client.get("/api/complaints", headers=officer_headers)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json["complaints"][0]["id"], complaint_id)

        update = self.client.patch(
            f"/api/complaints/{complaint_id}",
            headers=officer_headers,
            json={"status": "In progress", "department": "Roads & Transport"},
        )
        self.assertEqual(update.status_code, 403)
        self._create_department_staff("roads-work@example.test", "Roads & Transport")
        department_headers = self._token("roads-work@example.test", "department")
        accepted = self.client.patch(
            f"/api/department/complaints/{complaint_id}",
            headers=department_headers,
            json={"action": "accept"},
        )
        self.assertEqual(accepted.status_code, 200)
        update = self.client.patch(
            f"/api/department/complaints/{complaint_id}",
            headers=department_headers,
            json={"action": "in_progress"},
        )
        self.assertEqual(update.status_code, 200)
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            stored_status = connection.execute(
                "SELECT workflow_status FROM complaints WHERE complaint_id = ?", (complaint_id,)
            ).fetchone()[0]
        self.assertEqual(stored_status, "In progress")
        own_list = self.client.get("/api/complaints/mine", headers=self.citizen_headers)
        self.assertEqual(own_list.json["complaints"][0]["status"], "In progress")
        history = self.client.get(
            f"/api/complaints/{complaint_id}/history", headers=self.citizen_headers
        )
        self.assertEqual(
            [item["new_status"] for item in history.json["history"]],
            ["In progress", "Accepted", "Pending"],
        )

    def test_complaint_and_status_history_survive_database_reopen(self):
        response = self.client.post("/api/complaints", headers=self.citizen_headers, json={
            "title": "Persistent road repair",
            "category": "Roads & pathways",
            "description": "A damaged road section needs inspection near the library.",
            "location": "Library Avenue",
        })
        self.assertEqual(response.status_code, 201)
        complaint_id = response.json["id"]

        admin_headers = self._token("admin@example.test", "admin")
        update = self.client.patch(
            f"/api/complaints/{complaint_id}",
            headers=admin_headers,
            json={"status": "Resolved"},
        )
        self.assertEqual(update.status_code, 403)
        self._create_department_staff("persistent-roads@example.test", "Roads & Transport")
        department_headers = self._token("persistent-roads@example.test", "department")
        self.assertEqual(self.client.patch(
            f"/api/department/complaints/{complaint_id}",
            headers=department_headers,
            json={"action": "accept"},
        ).status_code, 200)
        self.assertEqual(self.client.patch(
            f"/api/department/complaints/{complaint_id}",
            headers=department_headers,
            json={"action": "in_progress"},
        ).status_code, 200)

        database_path = self.app.config["DATABASE"]
        self.assertTrue(Path(database_path).is_absolute())
        with closing(sqlite3.connect(database_path)) as first_connection:
            first_complaint = first_connection.execute(
                """SELECT title, category, description, location, workflow_status
                   FROM complaints WHERE complaint_id = ?""",
                (complaint_id,),
            ).fetchone()
            first_history = first_connection.execute(
                """SELECT old_status, new_status FROM complaint_status_history
                   WHERE complaint_id = ? ORDER BY id""",
                (complaint_id,),
            ).fetchall()

        with closing(sqlite3.connect(database_path)) as reopened_connection:
            saved_complaint = reopened_connection.execute(
                """SELECT title, category, description, location, workflow_status
                   FROM complaints WHERE complaint_id = ?""",
                (complaint_id,),
            ).fetchone()
            saved_history = reopened_connection.execute(
                """SELECT old_status, new_status FROM complaint_status_history
                   WHERE complaint_id = ? ORDER BY id""",
                (complaint_id,),
            ).fetchall()

        self.assertEqual(saved_complaint, first_complaint)
        self.assertEqual(saved_complaint, (
            "Persistent road repair",
            "Roads & pathways",
            "A damaged road section needs inspection near the library.",
            "Library Avenue",
            "In progress",
        ))
        self.assertEqual(saved_history, first_history)
        self.assertEqual(
            saved_history,
            [(None, "Pending")],
        )
        with closing(sqlite3.connect(database_path)) as connection:
            workflow_history = connection.execute(
                """SELECT old_status, new_status FROM department_status_history
                   WHERE complaint_id = ? ORDER BY id""",
                (complaint_id,),
            ).fetchall()
        self.assertEqual(workflow_history, [("Pending", "Accepted"), ("Accepted", "In progress")])

    def test_account_complaint_and_priority_survive_app_restart(self):
        response = self.client.post("/api/complaints", headers=self.citizen_headers, json={
            "title": "Restart persistence check",
            "category": "Water supply",
            "description": "A persistent leak needs an inspection near the library.",
            "location": "Library Avenue",
        })
        self.assertEqual(response.status_code, 201)
        complaint_id = response.json["id"]
        self.assertEqual(response.json["priority"], "Medium")

        admin_headers = self._token("admin@example.test", "admin")
        update = self.client.patch(
            f"/api/complaints/{complaint_id}",
            headers=admin_headers,
            json={
                "department": "Water Works",
                "priority": "High",
            },
        )
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.json["priority"], "High")
        self.assertEqual(update.json["status"], "Pending")
        self._create_department_staff("restart-water@example.test", "Water Works")
        department_headers = self._token("restart-water@example.test", "department")
        self.assertEqual(self.client.patch(
            f"/api/department/complaints/{complaint_id}",
            headers=department_headers,
            json={"action": "accept"},
        ).status_code, 200)
        self.assertEqual(self.client.patch(
            f"/api/department/complaints/{complaint_id}",
            headers=department_headers,
            json={"action": "in_progress"},
        ).status_code, 200)

        restarted_app = create_app({
            "TESTING": True,
            "JWT_SECRET": "test-secret-that-is-not-used-outside-tests",
            "DATABASE": self.app.config["DATABASE"],
            "UPLOAD_FOLDER": self.app.config["UPLOAD_FOLDER"],
            "FRONTEND_ORIGINS": {"http://localhost:5173"},
        })
        restarted_client = restarted_app.test_client()
        login = restarted_client.post("/api/auth/login", json={
            "email": "citizen@example.test",
            "password": "sample-test-password",
        })
        self.assertEqual(login.status_code, 200)
        citizen_headers = {"Authorization": f"Bearer {login.json['token']}"}
        complaints = restarted_client.get(
            "/api/complaints/mine", headers=citizen_headers
        )
        persisted = next(
            complaint for complaint in complaints.json["complaints"]
            if complaint["id"] == complaint_id
        )
        self.assertEqual(persisted["category"], "Water supply")
        self.assertEqual(persisted["description"], "A persistent leak needs an inspection near the library.")
        self.assertEqual(persisted["location"], "Library Avenue")
        self.assertEqual(persisted["citizen_id"], self.citizen_id)
        self.assertEqual(persisted["status"], "In progress")
        self.assertEqual(persisted["department"], "Water Works")
        self.assertEqual(persisted["priority"], "High")
        self.assertTrue(persisted["created_at"])

        history = restarted_client.get(
            f"/api/complaints/{complaint_id}/history", headers=citizen_headers
        )
        self.assertEqual(
            [item["new_status"] for item in history.json["history"]],
            ["In progress", "Accepted", "Pending"],
        )
        summary = restarted_client.get(
            "/api/dashboard/summary", headers=citizen_headers
        )
        self.assertEqual(len(summary.json["monthly"]), 6)
        self.assertEqual(sum(item["received"] for item in summary.json["monthly"]), 1)

    def test_status_update_rolls_back_if_history_write_fails(self):
        response = self.client.post("/api/complaints", headers=self.citizen_headers, json={
            "title": "Atomic status change",
            "category": "Street lighting",
            "description": "The streetlight is out near the north entrance.",
            "location": "North Entrance",
        })
        self.assertEqual(response.status_code, 201)
        complaint_id = response.json["id"]
        self._create_department_staff("atomic-electrical@example.test", "Electrical")
        department_headers = self._token("atomic-electrical@example.test", "department")

        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            connection.execute(
                """CREATE TRIGGER reject_department_status_history
                   BEFORE INSERT ON department_status_history
                   BEGIN SELECT RAISE(ABORT, 'test status history failure'); END"""
            )
            connection.commit()

        failed_update = self.client.patch(
            f"/api/department/complaints/{complaint_id}",
            headers=department_headers,
            json={"action": "accept"},
        )
        self.assertEqual(failed_update.status_code, 409)

        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            status = connection.execute(
                "SELECT workflow_status FROM complaints WHERE complaint_id = ?", (complaint_id,)
            ).fetchone()[0]
            history_count = connection.execute(
                """SELECT COUNT(*) FROM complaint_status_history
                   WHERE complaint_id = ?""",
                (complaint_id,),
            ).fetchone()[0]
        self.assertIsNone(status)
        self.assertEqual(history_count, 1)

    def test_citizen_cannot_access_or_update_another_citizens_complaint(self):
        response = self.client.post("/api/complaints", headers=self.citizen_headers, json={
            "title": "Broken street light",
            "category": "Street lighting",
            "description": "The street lamp near the corner is not working.",
            "location": "Park Street",
        })
        update = self.client.patch(
            f"/api/complaints/{response.json['id']}",
            headers=self.citizen_headers,
            json={"status": "Resolved"},
        )
        self.assertEqual(update.status_code, 403)
        forbidden_list = self.client.get("/api/complaints", headers=self.citizen_headers)
        self.assertEqual(forbidden_list.status_code, 403)
        unauthenticated_list = self.client.get("/api/complaints")
        self.assertEqual(unauthenticated_list.status_code, 401)

    def test_municipal_is_read_only_and_admin_cannot_change_operational_status(self):
        response = self.client.post("/api/complaints", headers=self.citizen_headers, json={
            "title": "Municipal role boundary check",
            "category": "Roads & pathways",
            "description": "A damaged road needs inspection near the school entrance.",
            "location": "School Road",
        })
        self.assertEqual(response.status_code, 201)
        complaint_id = response.json["id"]
        municipal_headers = self._token("officer@example.test", "municipal")
        for update in (
            {"status": "In progress"},
            {"department": "Sanitation"},
            {"priority": "High"},
        ):
            result = self.client.patch(
                f"/api/complaints/{complaint_id}",
                headers=municipal_headers,
                json=update,
            )
            self.assertEqual(result.status_code, 403)

        self._create_department_staff("boundary-roads@example.test", "Roads & Transport")
        department_headers = self._token("boundary-roads@example.test", "department")
        for action in ("accept", "in_progress"):
            result = self.client.patch(
                f"/api/department/complaints/{complaint_id}",
                headers=department_headers,
                json={"action": action},
            )
            self.assertEqual(result.status_code, 200)

        admin_headers = self._token("admin@example.test", "admin")
        forbidden_status = self.client.patch(
            f"/api/complaints/{complaint_id}",
            headers=admin_headers,
            json={"status": "Completed"},
        )
        self.assertEqual(forbidden_status.status_code, 403)
        reassign = self.client.patch(
            f"/api/complaints/{complaint_id}",
            headers=admin_headers,
            json={"department": "Roads & Transport", "priority": "High"},
        )
        self.assertEqual(reassign.status_code, 200)
        self.assertEqual(reassign.json["status"], "In progress")
        self.assertEqual(reassign.json["department"], "Roads & Transport")
        self.assertEqual(reassign.json["priority"], "High")

    def test_image_upload_is_validated_and_requires_authorized_access(self):
        image_bytes = io.BytesIO()
        Image.new("RGB", (12, 12), "blue").save(image_bytes, format="PNG")
        image_bytes.seek(0)
        response = self.client.post(
            "/api/complaints",
            headers=self.citizen_headers,
            data={
                "title": "Damaged road surface",
                "category": "Roads & pathways",
                "description": "The road surface has broken near the crossing.",
                "location": "Central Avenue",
                "image": (image_bytes, "../../unsafe.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json["image_url"])
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            image_path = connection.execute(
                "SELECT image_path FROM complaints WHERE complaint_id = ?",
                (response.json["id"],),
            ).fetchone()[0]
        self.assertTrue(image_path)
        self.assertTrue((Path(self.app.config["UPLOAD_FOLDER"]) / image_path).is_file())
        fetched = self.client.get(response.json["image_url"], headers=self.citizen_headers)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.mimetype, "image/png")
        fetched.close()

    def test_legacy_import_requires_explicit_backup_and_assigns_authenticated_citizen(self):
        backup = {"complaints": [{
            "id": "CIV-2025-1039",
            "title": "Garbage not collected",
            "category": "Waste management",
            "description": "Household waste has not been collected from the bins.",
            "location": "Green Park, Ward 07",
            "status": "Resolved",
            "citizen": "A legacy display name",
        }]}
        response = self.client.post(
            "/api/complaints/import", headers=self.citizen_headers, json=backup
        )
        self.assertEqual(response.status_code, 201)
        own = self.client.get("/api/complaints/mine", headers=self.citizen_headers)
        complaint = own.json["complaints"][0]
        self.assertEqual(complaint["citizen_id"], self.citizen_id)
        self.assertNotEqual(complaint["id"], "CIV-2025-1039")
        repeated = self.client.post(
            "/api/complaints/import", headers=self.citizen_headers, json=backup
        )
        self.assertEqual(repeated.status_code, 409)

    def test_dashboard_statistics_and_citizen_progress_require_admin_role(self):
        self.client.post("/api/complaints", headers=self.citizen_headers, json={
            "title": "Broken street light",
            "category": "Street lighting",
            "description": "The street lamp near the crossing does not turn on.",
            "location": "Park Street",
        })
        municipal_headers = self._token("officer@example.test", "municipal")
        admin_headers = self._token("admin@example.test", "admin")
        self.assertEqual(
            self.client.get("/api/admin/citizens", headers=municipal_headers).status_code,
            403,
        )
        citizens = self.client.get("/api/admin/citizens", headers=admin_headers)
        self.assertEqual(citizens.status_code, 200)
        self.assertEqual(citizens.json["citizens"][0]["complaint_count"], 1)
        summary = self.client.get("/api/dashboard/summary", headers=admin_headers)
        self.assertEqual(summary.json["total"], 1)
        self.assertEqual(summary.json["pending"], 1)
        self.assertEqual(summary.json["by_department"][0]["name"], "Electrical")

    def test_existing_database_adds_legacy_import_column(self):
        root = Path(self.temporary.name)
        database_path = root / "existing.sqlite"
        schema = (Path(__file__).resolve().parents[1] / "schema.sql").read_text(
            encoding="utf-8"
        )
        schema = schema.replace("    message TEXT,\n    progress_note TEXT,\n", "")
        schema = schema.replace("     legacy_source_id TEXT,\n", "")
        schema = schema.replace(
            "    priority TEXT NOT NULL DEFAULT 'Medium' CHECK (priority IN ('Low', 'Medium', 'High')),\n",
            "",
        )
        schema = schema.replace(
            "    assignment_review_required INTEGER NOT NULL DEFAULT 0 CHECK (assignment_review_required IN (0, 1)),\n",
            "",
        )
        schema = schema.replace(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_complaints_legacy_source\n"
            "    ON complaints(citizen_id, legacy_source_id)\n"
            "    WHERE legacy_source_id IS NOT NULL;\n",
            "",
        )
        with closing(sqlite3.connect(database_path)) as connection:
            connection.executescript(schema)
            connection.execute(
                """INSERT INTO users
                   (id, name, email, phone, password_hash, role, created_at)
                   VALUES ('legacy-citizen', 'Legacy Citizen', 'legacy@example.test',
                           '+91 98765 43210', 'hash', 'citizen', '2025-01-01T00:00:00+00:00')"""
            )
            (root / "existing-uploads").mkdir()
            (root / "existing-uploads" / "legacy-image.png").write_bytes(b"existing-image")
            connection.execute(
                """INSERT INTO complaints (
                       complaint_id, citizen_id, title, category, description, image_path,
                       location, latitude, longitude, assigned_department,
                       status, overdue, created_at, updated_at
                   ) VALUES (
                       'CIV-2025-LEGACY', 'legacy-citizen', 'Legacy report',
                       'Roads & pathways', 'Existing report data must remain unchanged.', 'legacy-image.png',
                       'Legacy Street', NULL, NULL, 'Roads & Transport',
                       'In progress', 0, '2025-01-01T00:00:00+00:00',
                       '2025-01-02T00:00:00+00:00'
                   )"""
            )
            connection.execute(
                   """INSERT INTO notification_deliveries
                      (user_id, complaint_id, channel, event_key, status,
                       provider_response, attempts, created_at, updated_at)
                      VALUES (
                          'legacy-citizen', 'CIV-2025-LEGACY', 'sms',
                          'CIV-2025-LEGACY:accepted', 'sent',
                          '{"request_id":"prior-delivery"}', 1,
                          '2025-01-02T00:00:00+00:00', '2025-01-02T00:00:00+00:00'
                      )"""
            )
            connection.commit()

        create_app({
            "TESTING": True,
            "JWT_SECRET": "test-secret-that-is-not-used-outside-tests",
            "DATABASE": str(database_path),
            "UPLOAD_FOLDER": str(root / "existing-uploads"),
        })

        with closing(sqlite3.connect(database_path)) as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(complaints)")
            }
            user_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(users)")
            }
            indexes = {
                row[1] for row in connection.execute("PRAGMA index_list(complaints)")
            }
            user_count = connection.execute(
                "SELECT COUNT(*) FROM users WHERE id = 'legacy-citizen'"
            ).fetchone()[0]
            complaint_count = connection.execute(
                "SELECT COUNT(*) FROM complaints WHERE complaint_id = 'CIV-2025-LEGACY'"
            ).fetchone()[0]
            delivery_table = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'notification_deliveries'"
            ).fetchone()[0]
            delivery_columns = {
                row[1] for row in connection.execute(
                    "PRAGMA table_info(notification_deliveries)"
                )
            }
            preserved_delivery = connection.execute(
                """SELECT status, provider_response, attempts
                   FROM notification_deliveries
                   WHERE event_key = 'CIV-2025-LEGACY:accepted'"""
            ).fetchone()
        self.assertIn("legacy_source_id", columns)
        self.assertIn("priority", columns)
        self.assertIn("assignment_review_required", columns)
        self.assertIn("predicted_category", columns)
        self.assertIn("expected_completion_at", columns)
        self.assertIn("sms_consent", user_columns)
        self.assertIn("idx_complaints_legacy_source", indexes)
        self.assertEqual(delivery_table, 1)
        self.assertIn("message", delivery_columns)
        self.assertIn("progress_note", delivery_columns)
        self.assertEqual(
            preserved_delivery,
            ("sent", '{"request_id":"prior-delivery"}', 1),
        )
        self.assertEqual((user_count, complaint_count), (1, 1))
        with closing(sqlite3.connect(database_path)) as connection:
            preserved = connection.execute(
                """SELECT title, status, assigned_department, priority, image_path
                   FROM complaints WHERE complaint_id = 'CIV-2025-LEGACY'"""
            ).fetchone()
            assignment_count = connection.execute(
                """SELECT COUNT(*) FROM complaint_department_history
                   WHERE complaint_id = 'CIV-2025-LEGACY'"""
            ).fetchone()[0]
        self.assertEqual(
            preserved,
            ("Legacy report", "In progress", "Roads & Transport", "Medium", "legacy-image.png"),
        )
        self.assertEqual(
            (root / "existing-uploads" / "legacy-image.png").read_bytes(),
            b"existing-image",
        )
        with closing(sqlite3.connect(database_path)) as connection:
            preserved_user_count = connection.execute(
                "SELECT COUNT(*) FROM users WHERE id = 'legacy-citizen'"
            ).fetchone()[0]
            review_flag = connection.execute(
                """SELECT assignment_review_required FROM complaints
                   WHERE complaint_id = 'CIV-2025-LEGACY'"""
            ).fetchone()[0]
        self.assertEqual(preserved_user_count, 1)
        with closing(sqlite3.connect(database_path)) as connection:
            preserved_phone, sms_consent = connection.execute(
                """SELECT phone, sms_consent FROM users
                   WHERE id = 'legacy-citizen'"""
            ).fetchone()
        self.assertEqual(preserved_phone, "+91 98765 43210")
        self.assertEqual(sms_consent, 0)
        self.assertEqual(review_flag, 0)
        self.assertEqual(assignment_count, 1)

    def test_department_workflow_is_scoped_persistent_and_notifies_citizen(self):
        self._create_department_staff("roads@example.test", "Roads & Transport")
        self._create_department_staff("water@example.test", "Water Works")
        roads_headers = self._token("roads@example.test", "department")
        water_headers = self._token("water@example.test", "department")
        complaint = self.client.post("/api/complaints", headers=self.citizen_headers, json={
            "title": "Road repair request",
            "category": "Roads & pathways",
            "description": "A damaged road section needs attention near the school.",
            "location": "School Road",
        }).json
        complaint_id = complaint["id"]

        roads_queue = self.client.get("/api/department/complaints", headers=roads_headers)
        water_queue = self.client.get("/api/department/complaints", headers=water_headers)
        self.assertEqual([item["id"] for item in roads_queue.json["complaints"]], [complaint_id])
        self.assertEqual(water_queue.json["complaints"], [])
        forbidden = self.client.patch(
            f"/api/department/complaints/{complaint_id}",
            headers=water_headers,
            json={"action": "accept"},
        )
        self.assertEqual(forbidden.status_code, 403)

        accepted = self.client.patch(
            f"/api/department/complaints/{complaint_id}",
            headers=roads_headers,
            json={"action": "accept"},
        )
        self.assertEqual(accepted.json["status"], "Accepted")
        started = self.client.patch(
            f"/api/department/complaints/{complaint_id}",
            headers=roads_headers,
            json={"action": "in_progress", "note": "Crew dispatched to inspect the site."},
        )
        self.assertEqual(started.json["status"], "In progress")
        completed = self.client.patch(
            f"/api/department/complaints/{complaint_id}",
            headers=roads_headers,
            json={"action": "complete", "note": "Road surface repaired and inspected."},
        )
        self.assertEqual(completed.json["status"], "Completed")
        own_list = self.client.get("/api/complaints/mine", headers=self.citizen_headers)
        self.assertEqual(own_list.json["complaints"][0]["department"], "Roads & Transport")
        self.assertEqual(own_list.json["complaints"][0]["status"], "Completed")
        self.assertEqual(
            own_list.json["complaints"][0]["latest_progress_note"],
            "Road surface repaired and inspected.",
        )
        notices = self.client.get("/api/notifications", headers=self.citizen_headers)
        self.assertEqual(
            [item["kind"] for item in notices.json["notifications"]],
            [
                "progress_note_added", "work_completed", "progress_note_added",
                "work_started", "complaint_accepted", "assigned",
            ],
        )
        history = self.client.get(
            f"/api/complaints/{complaint_id}/history", headers=self.citizen_headers
        )
        self.assertEqual(
            [item["new_status"] for item in history.json["history"][:3]],
            ["Completed", "In progress", "Accepted"],
        )
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            saved_notes = connection.execute(
                "SELECT COUNT(*) FROM complaint_progress_notes WHERE complaint_id = ?",
                (complaint_id,),
            ).fetchone()[0]
            saved_assignments = connection.execute(
                "SELECT COUNT(*) FROM complaint_department_history WHERE complaint_id = ?",
                (complaint_id,),
            ).fetchone()[0]
        self.assertEqual(saved_notes, 2)
        self.assertEqual(saved_assignments, 1)

    def test_every_category_routes_only_to_its_configured_department(self):
        expected_mapping = {
            "Roads & pathways": "Roads & Transport",
            "Waste management": "Sanitation",
            "Water supply": "Water Works",
            "Drainage & flooding": "Water Works",
            "Street lighting": "Electrical",
            "Public health": "Public Health",
            "Parks & gardens": "Parks & Gardens",
            "Other": "Municipal ward office",
        }
        self.assertEqual(CATEGORIES, set(expected_mapping))
        self.assertEqual(DEPARTMENT_BY_CATEGORY, expected_mapping)
        self.assertEqual(set(expected_mapping.values()), {
            "Roads & Transport", "Sanitation", "Water Works", "Electrical",
            "Public Health", "Parks & Gardens", "Municipal ward office",
        })

        headers_by_department = {}
        for index, department in enumerate(sorted(DEPARTMENTS)):
            email = f"department-{index}@example.test"
            self._create_department_staff(email, department)
            headers_by_department[department] = self._token(email, "department")

        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            connection.execute(
                """UPDATE category_department_mappings
                   SET department = 'Sanitation'
                   WHERE category = 'Roads & pathways'"""
            )
            connection.commit()

        complaint_ids = {}
        for index, (category, department) in enumerate(expected_mapping.items()):
            response = self.client.post("/api/complaints", headers=self.citizen_headers, json={
                "title": f"Category routing report {index}",
                "category": category,
                "description": f"Please inspect this {category.lower()} issue near the community center.",
                "location": "Community Center Road",
            })
            self.assertEqual(response.status_code, 201, response.json)
            self.assertEqual(response.json["department"], department)
            self.assertEqual(response.json["selected_category"], category)
            self.assertEqual(response.json["assigned_department"], department)
            if response.json["assignment_review_required"]:
                self.assertEqual(
                    response.json["classifier_model"], "tfidf-logistic-regression"
                )
            complaint_ids[category] = response.json["id"]

        for department, headers in headers_by_department.items():
            response = self.client.get("/api/department/complaints", headers=headers)
            self.assertEqual(response.status_code, 200)
            actual_ids = {item["id"] for item in response.json["complaints"]}
            expected_ids = {
                complaint_ids[category]
                for category, assigned in expected_mapping.items()
                if assigned == department
            }
            self.assertEqual(actual_ids, expected_ids)
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            for complaint_id in complaint_ids.values():
                self.assertEqual(
                    connection.execute(
                        """SELECT COUNT(*) FROM complaint_department_history
                           WHERE complaint_id = ?""",
                        (complaint_id,),
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        """SELECT COUNT(*) FROM notifications
                           WHERE user_id = ? AND complaint_id = ? AND kind = 'assigned'""",
                        (self.citizen_id, complaint_id),
                    ).fetchone()[0],
                    1,
                )

    def test_photo_only_and_photo_plus_text_complaints_route_by_category(self):
        self._create_department_staff("water-photo@example.test", "Water Works")
        self._create_department_staff("sanitation-photo@example.test", "Sanitation")
        water_headers = self._token("water-photo@example.test", "department")
        sanitation_headers = self._token("sanitation-photo@example.test", "department")

        image_only = io.BytesIO()
        Image.new("RGB", (12, 12), "blue").save(image_only, format="PNG")
        image_only.seek(0)
        photo_only_response = self.client.post(
            "/api/complaints",
            headers=self.citizen_headers,
            data={
                "title": "Water leak shown in photo",
                "category": "Water supply",
                "description": "",
                "location": "Central Avenue",
                "image": (image_only, "water-leak.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(photo_only_response.status_code, 201, photo_only_response.json)
        self.assertEqual(photo_only_response.json["department"], "Water Works")
        self.assertTrue(photo_only_response.json["image_url"])
        self.assertEqual(photo_only_response.json["description"], "")
        self.assertFalse(photo_only_response.json["assignment_review_required"])
        self.assertTrue(photo_only_response.json["prediction_needs_review"])
        self.assertEqual(photo_only_response.json["assigned_department"], "Water Works")
        self.assertIsNone(photo_only_response.json["category_confidence"])
        self.assertEqual(
            photo_only_response.json["review_reason"],
            "ML: no evaluated advisory model is available; manual verification requested.",
        )

        image_and_text = io.BytesIO()
        Image.new("RGB", (12, 12), "green").save(image_and_text, format="PNG")
        image_and_text.seek(0)
        photo_and_text_response = self.client.post(
            "/api/complaints",
            headers=self.citizen_headers,
            data={
                "title": "Waste collection photo",
                "category": "Waste management",
                "description": "Trash has not been collected for several days.",
                "location": "Market Street",
                "image": (image_and_text, "waste.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(photo_and_text_response.status_code, 201, photo_and_text_response.json)
        self.assertEqual(photo_and_text_response.json["department"], "Sanitation")
        self.assertTrue(photo_and_text_response.json["image_url"])

        water_queue = self.client.get("/api/department/complaints", headers=water_headers)
        sanitation_queue = self.client.get("/api/department/complaints", headers=sanitation_headers)
        self.assertEqual(
            [item["id"] for item in water_queue.json["complaints"]],
            [photo_only_response.json["id"]],
        )
        self.assertEqual(
            [item["id"] for item in sanitation_queue.json["complaints"]],
            [photo_and_text_response.json["id"]],
        )
        no_description = self.client.post(
            "/api/complaints",
            headers=self.citizen_headers,
            json={
                "title": "Text-only report",
                "category": "Water supply",
                "description": "",
                "location": "Central Avenue",
            },
        )
        self.assertEqual(no_description.status_code, 400)

    def test_unsupported_categories_are_not_assigned_by_fallback(self):
        response = self.client.post("/api/complaints", headers=self.citizen_headers, json={
            "title": "Unmapped category report",
            "category": "Unmapped pilot category",
            "description": "This category has no approved department mapping.",
            "location": "Civic Center",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("supported complaint categories", response.json["error"])

    def test_department_summary_counts_and_notes_survive_backend_restart(self):
        self._create_department_staff("counts-roads@example.test", "Roads & Transport")
        roads_headers = self._token("counts-roads@example.test", "department")
        complaint_ids = []
        for index in range(2):
            response = self.client.post("/api/complaints", headers=self.citizen_headers, json={
                "title": f"Persistent workflow report {index}",
                "category": "Roads & pathways",
                "description": "The road needs inspection near the public library.",
                "location": "Library Avenue",
            })
            self.assertEqual(response.status_code, 201)
            complaint_ids.append(response.json["id"])

        self.client.patch(
            f"/api/department/complaints/{complaint_ids[0]}",
            headers=roads_headers,
            json={"action": "accept"},
        )
        self.client.patch(
            f"/api/department/complaints/{complaint_ids[0]}",
            headers=roads_headers,
            json={"action": "in_progress", "note": "The crew has started the repair."},
        )
        summary = self.client.get("/api/dashboard/summary", headers=roads_headers).json
        self.assertEqual(
            (summary["total"], summary["pending"], summary["in_progress"], summary["completed"]),
            (2, 1, 1, 0),
        )

        self.client.patch(
            f"/api/department/complaints/{complaint_ids[0]}",
            headers=roads_headers,
            json={"action": "complete", "note": "The repair has been completed."},
        )
        summary = self.client.get("/api/dashboard/summary", headers=roads_headers).json
        self.assertEqual(
            (summary["total"], summary["pending"], summary["in_progress"], summary["completed"]),
            (2, 1, 0, 1),
        )

        restarted_app = create_app({
            "TESTING": True,
            "JWT_SECRET": "test-secret-that-is-not-used-outside-tests",
            "DATABASE": self.app.config["DATABASE"],
            "UPLOAD_FOLDER": self.app.config["UPLOAD_FOLDER"],
        })
        restarted_client = restarted_app.test_client()
        citizen_complaints = restarted_client.get(
            "/api/complaints/mine", headers=self.citizen_headers
        ).json["complaints"]
        completed = next(item for item in citizen_complaints if item["id"] == complaint_ids[0])
        self.assertEqual(completed["department"], "Roads & Transport")
        self.assertEqual(completed["status"], "Completed")
        self.assertEqual(completed["latest_progress_note"], "The repair has been completed.")
        history = restarted_client.get(
            f"/api/complaints/{complaint_ids[0]}/history",
            headers=self.citizen_headers,
        ).json["history"]
        self.assertIn("Completed", [entry["new_status"] for entry in history])
        self.assertIn("In progress", [entry["new_status"] for entry in history])

    def test_department_assignment_notifies_only_the_canonical_department(self):
        self._create_department_staff("electrical@example.test", "Electrical")
        self._create_department_staff("roads@example.test", "Roads & Transport")
        electrical_headers = self._token("electrical@example.test", "department")
        roads_headers = self._token("roads@example.test", "department")
        complaint = self.client.post("/api/complaints", headers=self.citizen_headers, json={
            "title": "Lighting repair",
            "category": "Street lighting",
            "description": "The street lamp has stopped working near the library.",
            "location": "Library Lane",
        }).json
        admin_headers = self._token("admin@example.test", "admin")
        update = self.client.patch(
            f"/api/complaints/{complaint['id']}",
            headers=admin_headers,
            json={"department": "Roads & Transport"},
        )
        self.assertEqual(update.status_code, 409)
        electrical_notices = self.client.get(
            "/api/notifications", headers=electrical_headers
        )
        self.assertEqual(
            electrical_notices.json["notifications"][0]["kind"], "assigned"
        )
        notices = self.client.get("/api/notifications", headers=roads_headers)
        self.assertEqual(notices.json["notifications"], [])
        citizen_notices = self.client.get("/api/notifications", headers=self.citizen_headers)
        self.assertEqual(citizen_notices.json["notifications"][0]["kind"], "assigned")

    def test_backend_overdue_reminder_job_is_persistent_and_throttled(self):
        from app import send_overdue_reminders
        from datetime import datetime, timedelta, timezone

        complaint = self.client.post("/api/complaints", headers=self.citizen_headers, json={
            "title": "Overdue street repair",
            "category": "Roads & pathways",
            "description": "A damaged road section needs urgent repair near the clinic.",
            "location": "Clinic Road",
        }).json
        old_date = (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat(timespec="seconds")
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            connection.execute(
                "UPDATE complaints SET created_at = ? WHERE complaint_id = ?",
                (old_date, complaint["id"]),
            )
            connection.commit()
        send_overdue_reminders(self.app)
        send_overdue_reminders(self.app)
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            overdue, reminder_count = connection.execute(
                """SELECT overdue,
                          (SELECT COUNT(*) FROM notifications
                           WHERE complaint_id = ? AND kind = 'overdue')
                   FROM complaints WHERE complaint_id = ?""",
                (complaint["id"], complaint["id"]),
            ).fetchone()
        self.assertEqual(overdue, 1)
        self.assertEqual(reminder_count, 1)
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            escalation_count = connection.execute(
                """SELECT COUNT(*) FROM notifications
                   WHERE complaint_id = ? AND kind = 'unaccepted_escalation'""",
                (complaint["id"],),
            ).fetchone()[0]
            delivery_count = connection.execute(
                """SELECT COUNT(*) FROM notification_deliveries
                   WHERE complaint_id = ? AND event_key LIKE ?""",
                (complaint["id"], f"{complaint['id']}:escalation_reminder:%"),
            ).fetchone()[0]
        self.assertEqual(escalation_count, 2)
        self.assertEqual(delivery_count, 2)

    def test_classifier_priority_and_eta_are_advisory_and_persisted(self):
        from civic_services import classify_complaint, predict_priority

        model = classify_complaint("water leak on the street", [
            {"description": "water pipe leaking by the road", "category": "Water supply"},
            {"description": "water supply is interrupted", "category": "Water supply"},
            {"description": "pothole on road is dangerous", "category": "Roads & pathways"},
            {"description": "road surface is damaged", "category": "Roads & pathways"},
        ])
        self.assertTrue(model["trained"])
        self.assertIn(model["category"], {"Water supply", "Roads & pathways"})
        self.assertGreaterEqual(model["confidence"], 0)
        self.assertLessEqual(model["confidence"], 1)
        self.assertEqual(
            predict_priority("Water supply", "There is contaminated water at a school.")["priority"],
            "Critical",
        )
        response = self.client.post("/api/complaints", headers=self.citizen_headers, json={
            "title": "Potentially unsafe water",
            "category": "Water supply",
            "description": "Contaminated water is coming from the tap near the school.",
            "location": "School Road",
        })
        self.assertEqual(response.status_code, 201, response.json)
        complaint = response.json
        self.assertEqual(complaint["department"], "Water Works")
        self.assertEqual(complaint["predicted_priority"], "Critical")
        self.assertEqual(complaint["priority"], "High")
        self.assertTrue(complaint["expected_completion_at"])
        self.assertEqual(complaint["eta_method"], "configurable rule-based fallback")
        insights = self.client.get(
            f"/api/complaints/{complaint['id']}/insights",
            headers=self.citizen_headers,
        )
        self.assertEqual(insights.status_code, 200)
        self.assertFalse(insights.json["eta"]["is_guarantee"])
        admin_headers = self._token("admin@example.test", "admin")
        metrics = self.client.get("/api/admin/ml-metrics", headers=admin_headers)
        self.assertEqual(metrics.status_code, 200)
        self.assertEqual(metrics.json["training_samples"], 0)
        self.assertEqual(metrics.json["status"], "insufficient_data")
        self.assertEqual(metrics.json["evaluation"], "stratified k-fold cross-validation")
        self.assertIsNone(metrics.json["accuracy"])

    def test_verified_dataset_audit_permissions_and_retraining_is_disabled(self):
        municipal_headers = self._token("officer@example.test", "municipal")
        added = self.client.post("/api/municipal/ml-dataset", headers=municipal_headers, json={
            "category": "Water supply",
            "description": "A verified water pipe leak near the community library.",
            "verification_note": "Confirmed against municipal inspection record.",
        })
        self.assertEqual(added.status_code, 201, added.json)
        example_id = added.json["id"]
        metrics = self.client.get("/api/admin/ml-metrics", headers=municipal_headers)
        self.assertEqual(metrics.status_code, 200)
        self.assertEqual(metrics.json["training_samples"], 1)
        self.assertEqual(metrics.json["status"], "insufficient_data")
        self.assertIsNone(metrics.json["accuracy"])

        updated = self.client.patch(
            f"/api/municipal/ml-dataset/{example_id}",
            headers=municipal_headers,
            json={
                "category": "Water supply",
                "description": "Verified water pipe leak near the community library.",
                "verification_note": "Confirmed by a second municipal inspection.",
            },
        )
        self.assertEqual(updated.status_code, 200, updated.json)
        self._create_department_staff("dataset-roads@example.test", "Roads & Transport")
        department_headers = self._token("dataset-roads@example.test", "department")
        self.assertEqual(self.client.get(
            "/api/municipal/ml-dataset", headers=department_headers
        ).status_code, 403)
        self.assertEqual(self.client.post(
            "/api/municipal/ml-model/retrain", headers=department_headers, json={}
        ).status_code, 403)
        self.assertEqual(self.client.get(
            "/api/admin/ml-metrics", headers=department_headers
        ).status_code, 403)

        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            model_run_count = connection.execute(
                "SELECT COUNT(*) FROM ml_model_runs"
            ).fetchone()[0]
        retrain_response = self.client.post(
            "/api/municipal/ml-model/retrain", headers=municipal_headers, json={}
        )
        self.assertEqual(retrain_response.status_code, 409, retrain_response.json)
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM ml_model_runs").fetchone()[0],
                model_run_count,
            )
            actions = connection.execute(
                """SELECT action FROM verified_training_history
                   WHERE example_id = ? ORDER BY id""",
                (example_id,),
            ).fetchall()
        self.assertEqual([row[0] for row in actions], ["added", "updated"])

        removed = self.client.delete(
            f"/api/municipal/ml-dataset/{example_id}", headers=municipal_headers
        )
        self.assertEqual(removed.status_code, 200, removed.json)
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            remaining = connection.execute(
                "SELECT COUNT(*) FROM verified_training_examples WHERE id = ?", (example_id,)
            ).fetchone()[0]
            history = connection.execute(
                """SELECT action FROM verified_training_history
                   WHERE example_id = ? ORDER BY id""",
                (example_id,),
            ).fetchall()
        self.assertEqual(remaining, 0)
        self.assertEqual([row[0] for row in history], ["added", "updated", "removed"])

    def test_category_routing_cannot_be_remapped_or_manually_misassigned(self):
        municipal_headers = self._token("officer@example.test", "municipal")
        admin_headers = self._token("admin@example.test", "admin")
        mappings_before = self.client.get(
            "/api/municipal/category-mappings", headers=municipal_headers
        )
        self.assertEqual(
            {
                item["category"]: item["department"]
                for item in mappings_before.json["mappings"]
            },
            DEPARTMENT_BY_CATEGORY,
        )
        mapping = self.client.patch(
            "/api/municipal/category-mappings",
            headers=municipal_headers,
            json={
                "category": "Roads & pathways",
                "department": "Sanitation",
            },
        )
        self.assertEqual(mapping.status_code, 409)

        complaint = self.client.post("/api/complaints", headers=self.citizen_headers, json={
            "title": "Road routing integrity report",
            "category": "Roads & pathways",
            "description": "Please inspect the damaged road near Civic Center.",
            "location": "Civic Center",
        })
        self.assertEqual(complaint.status_code, 201, complaint.json)
        reassignment = self.client.patch(
            f"/api/complaints/{complaint.json['id']}",
            headers=admin_headers,
            json={"department": "Sanitation"},
        )
        self.assertEqual(reassignment.status_code, 409)
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT assigned_department FROM complaints WHERE complaint_id = ?",
                    (complaint.json["id"],),
                ).fetchone()[0],
                "Roads & Transport",
            )

    def test_department_queues_exclude_historical_misassignments_without_rewriting_them(self):
        complaint = self.client.post("/api/complaints", headers=self.citizen_headers, json={
            "title": "Historical road assignment",
            "category": "Roads & pathways",
            "description": "Please inspect a damaged road near the civic center.",
            "location": "Civic Center",
        })
        self.assertEqual(complaint.status_code, 201, complaint.json)
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            connection.execute(
                "UPDATE complaints SET assigned_department = 'Sanitation' WHERE complaint_id = ?",
                (complaint.json["id"],),
            )
            connection.commit()
        self._create_department_staff("historic-sanitation@example.test", "Sanitation")
        self._create_department_staff("historic-roads@example.test", "Roads & Transport")
        headers = [
            self._token("historic-sanitation@example.test", "department"),
            self._token("historic-roads@example.test", "department"),
        ]
        for department_headers in headers:
            queue = self.client.get(
                "/api/department/complaints", headers=department_headers
            )
            self.assertEqual(queue.status_code, 200)
            self.assertNotIn(
                complaint.json["id"], {item["id"] for item in queue.json["complaints"]}
            )
            summary = self.client.get(
                "/api/dashboard/summary", headers=department_headers
            )
            self.assertEqual(summary.json["total"], 0)
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT assigned_department FROM complaints WHERE complaint_id = ?",
                    (complaint.json["id"],),
                ).fetchone()[0],
                "Sanitation",
            )
            self.assertEqual(
                connection.execute(
                    """SELECT COUNT(*) FROM complaint_department_history
                       WHERE complaint_id = ?""",
                    (complaint.json["id"],),
                ).fetchone()[0],
                1,
            )

    def test_stratified_evaluation_requires_minimum_examples_and_covers_each_example(self):
        from civic_services import MIN_EXAMPLES_PER_CATEGORY, evaluate_classifier

        insufficient = [
            {"id": 1, "description": "water pipe leak", "category": "Water supply"},
            {"id": 2, "description": "road pothole", "category": "Roads & pathways"},
        ]
        result = evaluate_classifier(insufficient)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["accuracy"])
        training_rows = [
            {
                "id": index,
                "description": f"water supply pipe leak inspection report {index}",
                "category": "Water supply",
            }
            for index in range(MIN_EXAMPLES_PER_CATEGORY)
        ] + [
            {
                "id": index + MIN_EXAMPLES_PER_CATEGORY,
                "description": f"road pavement pothole repair report {index}",
                "category": "Roads & pathways",
            }
            for index in range(MIN_EXAMPLES_PER_CATEGORY)
        ]
        evaluated = evaluate_classifier(training_rows)
        self.assertEqual(evaluated["status"], "evaluated_advisory")
        self.assertEqual(evaluated["evaluation"], "5-fold stratified cross-validation")
        self.assertEqual(evaluated["evaluated_samples"], len(training_rows))
        self.assertFalse(evaluated["reliability_claim"])
        self.assertEqual(
            sum(sum(row.values()) for row in evaluated["confusion_matrix"].values()),
            len(training_rows),
        )

    def test_sms_consent_and_delivery_deduplication(self):
        registration = self.client.post("/api/auth/register", json={
            "name": "SMS Citizen",
            "email": "sms-citizen@example.test",
            "password": "sample-test-password",
            "phone": "+91 98765 43210",
            "sms_consent": True,
        })
        self.assertEqual(registration.status_code, 201, registration.json)
        citizen_headers = {"Authorization": f"Bearer {registration.json['token']}"}
        sent = []
        self.app.config["SMS_SENDER"] = lambda *args: (sent.append("sms") or ("sent", "mock-sms", None))
        self.app.config["BREVO_SENDER"] = lambda *args: ("sent", "mock-email", None)
        complaint = self.client.post("/api/complaints", headers=citizen_headers, json={
            "title": "Street light outage",
            "category": "Street lighting",
            "description": "The street light is out near the bus stop.",
            "location": "Bus Stop Road",
        })
        self.assertEqual(complaint.status_code, 201, complaint.json)
        complaint_id = complaint.json["id"]
        from civic_services import dispatch_citizen_notification
        self.assertEqual(
            dispatch_citizen_notification(
                self.app, complaint_id, f"{complaint_id}:assigned", "assigned", "Already sent."
            ),
            [],
        )
        self.assertEqual(sent, ["sms"])
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            rows = connection.execute(
                """SELECT channel, status, attempts FROM notification_deliveries
                   WHERE complaint_id = ? ORDER BY channel""",
                (complaint_id,),
            ).fetchall()
            consent = connection.execute(
                "SELECT sms_consent FROM users WHERE email = 'sms-citizen@example.test'"
            ).fetchone()[0]
            phone = connection.execute(
                "SELECT phone FROM users WHERE email = 'sms-citizen@example.test'"
            ).fetchone()[0]
        self.assertEqual(consent, 1)
        self.assertEqual(phone, "+919876543210")
        self.assertEqual(rows, [("email", "sent", 1), ("sms", "sent", 1)])

        preferences = self.client.patch(
            "/api/account/notification-preferences",
            headers=citizen_headers,
            json={"sms_consent": False},
        )
        self.assertEqual(preferences.status_code, 200)
        self.assertFalse(preferences.json["sms_consent"])

    def test_msg91_submission_and_status_update_use_mocked_api_and_persist_responses(self):
        registration = self.client.post("/api/auth/register", json={
            "name": "MSG91 Citizen",
            "email": "msg91-citizen@example.test",
            "password": "sample-test-password",
            "phone": "98765-43210",
            "sms_consent": True,
        })
        self.assertEqual(registration.status_code, 201, registration.json)
        citizen_headers = {"Authorization": "Bearer " + registration.json["token"]}
        self.app.config.update({
            "MSG91_AUTH_KEY": "test-auth-key",
            "MSG91_TEMPLATE_ID": "flow-template-id",
            "MSG91_SENDER_ID": "CIVICAI",
            "MSG91_DLT_PE_ID": "principal-entity-id",
            "MSG91_DLT_TEMPLATE_ID": "dlt-template-id",
            "BREVO_SENDER": lambda *args: ("sent", "mock-email", None),
        })

        def provider_acknowledgement():
            response = MagicMock()
            response.status = 200
            response.read.return_value = b'{"type":"success","message":"Request received","request_id":"mock-request"}'
            response.__enter__.return_value = response
            return response

        with patch(
            "urllib.request.urlopen",
            side_effect=[provider_acknowledgement(), provider_acknowledgement()],
        ) as urlopen:
            complaint = self.client.post("/api/complaints", headers=citizen_headers, json={
                "title": "Street light update",
                "category": "Street lighting",
                "description": "The street light is out near the bus stop.",
                "location": "Bus Stop Road",
            })
            self.assertEqual(complaint.status_code, 201, complaint.json)
            complaint_id = complaint.json["id"]
            department = "Electrical"
            self._create_department_staff("msg91-electrical@example.test", department)
            department_headers = self._token("msg91-electrical@example.test", "department")
            updated = self.client.patch(
                f"/api/department/complaints/{complaint_id}",
                headers=department_headers,
                json={"action": "accept"},
            )
            self.assertEqual(updated.status_code, 200, updated.json)

        self.assertEqual(urlopen.call_count, 2)
        request = urlopen.call_args_list[0].args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://control.msg91.com/api/v5/flow/")
        self.assertEqual(request.get_header("Authkey"), "test-auth-key")
        self.assertEqual(payload["template_id"], "flow-template-id")
        self.assertEqual(payload["sender"], "CIVICAI")
        self.assertEqual(payload["recipients"][0]["mobiles"], "919876543210")
        self.assertEqual(payload["recipients"][0]["VAR1"], complaint_id)
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            rows = connection.execute(
                """SELECT event_key, status, provider_response, failure_detail,
                          attempts, created_at, updated_at
                   FROM notification_deliveries
                   WHERE complaint_id = ? AND channel = 'sms'
                   ORDER BY created_at""",
                (complaint_id,),
            ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row[1] == "sent" for row in rows))
        self.assertTrue(all(
            json.loads(row[2])["request_id"] == "mock-request" for row in rows
        ))
        self.assertTrue(all(row[3] is None and row[4] == 1 for row in rows))
        self.assertTrue(all(row[5] and row[6] for row in rows))

    def test_progress_note_creates_in_app_notice_and_brevo_email(self):
        registration = self.client.post("/api/auth/register", json={
            "name": "Progress Note Citizen",
            "email": "progress-note@example.test",
            "password": "sample-test-password",
        })
        self.assertEqual(registration.status_code, 201, registration.json)
        citizen_headers = {"Authorization": "Bearer " + registration.json["token"]}
        sent_emails = []
        self.app.config["BREVO_SENDER"] = lambda *args: (
            sent_emails.append(args)
            or ("sent", '{"messageId":"<mock-brevo-id>"}', None)
        )
        self._create_department_staff("progress-electrical@example.test", "Electrical")
        department_headers = self._token("progress-electrical@example.test", "department")
        progress_note = "Inspected the damaged pole; replacement is scheduled for Friday."

        with patch("urllib.request.urlopen") as urlopen:
            complaint = self.client.post("/api/complaints", headers=citizen_headers, json={
                "title": "Damaged street light pole",
                "category": "Street lighting",
                "description": "A damaged street light pole needs repair.",
                "location": "Bus Stop Road",
            })
            self.assertEqual(complaint.status_code, 201, complaint.json)
            complaint_id = complaint.json["id"]
            accepted = self.client.patch(
                f"/api/department/complaints/{complaint_id}",
                headers=department_headers,
                json={"action": "accept"},
            )
            self.assertEqual(accepted.status_code, 200, accepted.json)
            started = self.client.patch(
                f"/api/department/complaints/{complaint_id}",
                headers=department_headers,
                json={"action": "in_progress", "note": progress_note},
            )
            self.assertEqual(started.status_code, 200, started.json)
            completed = self.client.patch(
                f"/api/department/complaints/{complaint_id}",
                headers=department_headers,
                json={"action": "complete"},
            )
            self.assertEqual(completed.status_code, 200, completed.json)

            from civic_services import dispatch_citizen_notification
            with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
                delivery = connection.execute(
                    """SELECT event_key, status, message, provider_response,
                              created_at, updated_at
                       FROM notification_deliveries
                       WHERE complaint_id = ? AND channel = 'email'
                         AND event_key LIKE '%:progress_note:%'""",
                    (complaint_id,),
                ).fetchone()
                in_app_note_count = connection.execute(
                    """SELECT COUNT(*) FROM notifications
                       WHERE complaint_id = ? AND kind = 'progress_note_added'
                         AND message LIKE ?""",
                    (complaint_id, f"%{progress_note}%"),
                ).fetchone()[0]
            self.assertIsNotNone(delivery)
            self.assertEqual(delivery[1], "sent")
            self.assertIn(f": {progress_note}", delivery[2])
            self.assertEqual(json.loads(delivery[3])["messageId"], "<mock-brevo-id>")
            self.assertTrue(delivery[4] and delivery[5])
            self.assertEqual(in_app_note_count, 1)
            self.assertIn(progress_note, sent_emails[-2][3])
            self.assertEqual(
                dispatch_citizen_notification(
                    self.app, complaint_id, delivery[0], "progress_note_added",
                    f"A progress note was added: {progress_note}",
                    channels=("email",),
                ),
                [],
            )
            self.assertEqual(urlopen.call_count, 0)
            self.assertEqual(len(sent_emails), 5)

    def test_brevo_email_uses_backend_credentials_and_persists_provider_response(self):
        registration = self.client.post("/api/auth/register", json={
            "name": "Brevo Citizen",
            "email": "brevo@example.test",
            "password": "sample-test-password",
        })
        self.assertEqual(registration.status_code, 201, registration.json)
        headers = {"Authorization": "Bearer " + registration.json["token"]}
        self.app.config.update({
            "BREVO_API_KEY": "test-brevo-api-key",
            "BREVO_SENDER_EMAIL": "notifications@example.test",
            "BREVO_SENDER_NAME": "SmartCivicAI Test",
        })
        response = MagicMock()
        response.status = 201
        response.read.return_value = b'{"messageId":"<mock-message-id>"}'
        response.__enter__.return_value = response
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            complaint = self.client.post("/api/complaints", headers=headers, json={
                "title": "Brevo email notification",
                "category": "Water supply",
                "description": "A water pipe has been leaking near the bus stop.",
                "location": "Bus Stop Road",
            })
        self.assertEqual(complaint.status_code, 201, complaint.json)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.brevo.com/v3/smtp/email")
        self.assertEqual(request.get_header("Api-key"), "test-brevo-api-key")
        payload = json.loads(request.data)
        self.assertEqual(payload["sender"], {
            "name": "SmartCivicAI Test",
            "email": "notifications@example.test",
        })
        self.assertEqual(payload["to"], [{"email": "brevo@example.test"}])
        self.assertEqual(payload["subject"], f"SmartCivicAI complaint {complaint.json['id']}: Assigned")
        self.assertIn(complaint.json["id"], payload["textContent"])
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            delivery = connection.execute(
                """SELECT status, provider_response, failure_detail, created_at, updated_at
                   FROM notification_deliveries
                   WHERE complaint_id = ? AND channel = 'email'""",
                (complaint.json["id"],),
            ).fetchone()
        self.assertEqual(delivery[0], "sent")
        self.assertEqual(json.loads(delivery[1])["messageId"], "<mock-message-id>")
        self.assertIsNone(delivery[2])
        self.assertTrue(delivery[3] and delivery[4])

    def test_brevo_missing_credentials_and_failures_are_not_successful(self):
        from civic_services import send_brevo_email

        with patch("urllib.request.urlopen") as urlopen:
            status, response, error = send_brevo_email(
                self.app, "citizen@example.test", "Notice", "Complaint update"
            )
        self.assertEqual(status, "not_configured")
        self.assertIsNone(response)
        self.assertIn("BREVO_API_KEY", error)
        self.assertIn("BREVO_SENDER_EMAIL", error)
        urlopen.assert_not_called()

        self.app.config.update({
            "BREVO_API_KEY": "test-brevo-api-key",
            "BREVO_SENDER_EMAIL": "notifications@example.test",
            "BREVO_SENDER_NAME": "SmartCivicAI",
        })
        with patch("urllib.request.urlopen", side_effect=TimeoutError("provider timeout")):
            status, response, error = send_brevo_email(
                self.app, "citizen@example.test", "Notice", "Complaint update"
            )
        self.assertEqual(status, "failed")
        self.assertIsNone(response)
        self.assertIn("provider timeout", error)

        import urllib.error

        rejected = urllib.error.HTTPError(
            "https://api.brevo.com/v3/smtp/email",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"message":"Invalid test-brevo-api-key"}'),
        )
        with patch("urllib.request.urlopen", side_effect=rejected):
            status, response, error = send_brevo_email(
                self.app, "citizen@example.test", "Notice", "Complaint update"
            )
        rejected.close()
        self.assertEqual(status, "failed")
        self.assertIn("[redacted]", response)
        self.assertNotIn("test-brevo-api-key", response)
        self.assertNotIn("test-brevo-api-key", error)

    def test_msg91_error_responses_and_missing_dlt_config_are_not_successful(self):
        from civic_services import send_msg91

        configured = {
            "MSG91_AUTH_KEY": "test-auth-key",
            "MSG91_TEMPLATE_ID": "flow-template-id",
            "MSG91_SENDER_ID": "CIVICAI",
            "MSG91_DLT_PE_ID": "principal-entity-id",
            "MSG91_DLT_TEMPLATE_ID": "dlt-template-id",
        }
        error_response = MagicMock()
        error_response.status = 200
        error_response.read.return_value = b'{"type":"error","message":"Template rejected"}'
        error_response.__enter__.return_value = error_response
        self.app.config.update(configured)
        with patch("urllib.request.urlopen", return_value=error_response):
            state, provider_body, error = send_msg91(
                self.app, "+91 98765 43210", "test", "CIV-TEST",
                "Electrical", "Pending", None,
            )
        self.assertEqual(state, "failed")
        self.assertIn("Template rejected", error)
        self.assertIn('"type":"error"', provider_body)

        self.app.config["MSG91_DLT_PE_ID"] = ""
        state, provider_body, error = send_msg91(
            self.app, "+91 98765 43210", "test", "CIV-TEST",
            "Electrical", "Pending", None,
        )
        self.assertEqual(state, "not_configured")
        self.assertIsNone(provider_body)
        self.assertIn("MSG91_DLT_PE_ID", error)

    def test_msg91_provider_rejection_is_persisted_as_failed(self):
        registration = self.client.post("/api/auth/register", json={
            "name": "Rejected SMS Citizen",
            "email": "rejected-sms@example.test",
            "password": "sample-test-password",
            "phone": "+919876543210",
            "sms_consent": True,
        })
        self.assertEqual(registration.status_code, 201, registration.json)
        citizen_headers = {"Authorization": "Bearer " + registration.json["token"]}
        self.app.config.update({
            "MSG91_AUTH_KEY": "test-auth-key",
            "MSG91_TEMPLATE_ID": "flow-template-id",
            "MSG91_SENDER_ID": "CIVICAI",
            "MSG91_DLT_PE_ID": "principal-entity-id",
            "MSG91_DLT_TEMPLATE_ID": "dlt-template-id",
            "BREVO_SENDER": lambda *args: ("sent", "mock-email", None),
        })
        response = MagicMock()
        response.status = 200
        response.read.return_value = (
            b'{"type":"error","message":"Template rejected test-auth-key"}'
        )
        response.__enter__.return_value = response
        with patch("urllib.request.urlopen", return_value=response):
            complaint = self.client.post("/api/complaints", headers=citizen_headers, json={
                "title": "Rejected SMS report",
                "category": "Water supply",
                "description": "A water pipe has been leaking near the bus stop.",
                "location": "Bus Stop Road",
            })
        self.assertEqual(complaint.status_code, 201, complaint.json)
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            delivery = connection.execute(
                """SELECT status, provider_response, failure_detail, updated_at
                   FROM notification_deliveries
                   WHERE complaint_id = ? AND channel = 'sms'""",
                (complaint.json["id"],),
            ).fetchone()
        self.assertEqual(delivery[0], "failed")
        self.assertIn("[redacted]", delivery[1])
        self.assertNotIn("test-auth-key", delivery[1])
        self.assertNotIn("test-auth-key", delivery[2])
        self.assertIn("Template rejected", delivery[2])
        self.assertTrue(delivery[3])

    def test_msg91_timeout_is_failed_and_never_reported_as_sent(self):
        from civic_services import send_msg91

        self.app.config.update({
            "MSG91_AUTH_KEY": "test-auth-key",
            "MSG91_TEMPLATE_ID": "flow-template-id",
            "MSG91_SENDER_ID": "CIVICAI",
            "MSG91_DLT_PE_ID": "principal-entity-id",
            "MSG91_DLT_TEMPLATE_ID": "dlt-template-id",
        })
        with patch("urllib.request.urlopen", side_effect=TimeoutError("provider timeout")):
            state, provider_body, error = send_msg91(
                self.app, "9876543210", "test", "CIV-TEST",
                "Electrical", "Pending", None,
            )
        self.assertEqual(state, "failed")
        self.assertIsNone(provider_body)
        self.assertIn("provider timeout", error)

    def test_msg91_marks_delivered_only_when_provider_explicitly_confirms(self):
        from civic_services import send_msg91

        self.app.config.update({
            "MSG91_AUTH_KEY": "test-auth-key",
            "MSG91_TEMPLATE_ID": "flow-template-id",
            "MSG91_SENDER_ID": "CIVICAI",
            "MSG91_DLT_PE_ID": "principal-entity-id",
            "MSG91_DLT_TEMPLATE_ID": "dlt-template-id",
        })
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"type":"success","delivery_status":"delivered"}'
        response.__enter__.return_value = response
        with patch("urllib.request.urlopen", return_value=response):
            state, _, error = send_msg91(
                self.app, "9876543210", "test", "CIV-TEST",
                "Electrical", "Pending", None,
            )
        self.assertEqual(state, "delivered")
        self.assertIsNone(error)

    def test_registration_sms_consent_requires_phone_and_explicit_boolean(self):
        missing_phone = self.client.post("/api/auth/register", json={
            "name": "No Phone",
            "email": "no-phone@example.test",
            "password": "sample-test-password",
            "sms_consent": True,
        })
        self.assertEqual(missing_phone.status_code, 400)
        invalid_consent = self.client.post("/api/auth/register", json={
            "name": "Invalid Consent",
            "email": "invalid-consent@example.test",
            "password": "sample-test-password",
            "phone": "9876543210",
            "sms_consent": "yes",
        })
        self.assertEqual(invalid_consent.status_code, 400)

    def test_sms_is_not_sent_without_explicit_citizen_consent(self):
        registration = self.client.post("/api/auth/register", json={
            "name": "No Consent Citizen",
            "email": "no-consent@example.test",
            "password": "sample-test-password",
            "phone": "9876543210",
        })
        self.assertEqual(registration.status_code, 201, registration.json)
        citizen_headers = {"Authorization": "Bearer " + registration.json["token"]}
        with patch("urllib.request.urlopen") as urlopen:
            complaint = self.client.post("/api/complaints", headers=citizen_headers, json={
                "title": "No consent SMS report",
                "category": "Water supply",
                "description": "A water pipe has been leaking by the bus stop.",
                "location": "Bus Stop Road",
            })
        self.assertEqual(complaint.status_code, 201, complaint.json)
        urlopen.assert_not_called()
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as connection:
            status = connection.execute(
                """SELECT status FROM notification_deliveries
                   WHERE complaint_id = ? AND channel = 'sms'""",
                (complaint.json["id"],),
            ).fetchone()[0]
        self.assertEqual(status, "skipped")

    def test_department_eta_feedback_ownership_and_municipal_analytics(self):
        self._create_department_staff("eta-roads@example.test", "Roads & Transport")
        roads_headers = self._token("eta-roads@example.test", "department")
        complaint = self.client.post("/api/complaints", headers=self.citizen_headers, json={
            "title": "Road repair feedback",
            "category": "Roads & pathways",
            "description": "The road surface has a pothole near the public library.",
            "location": "Library Avenue",
            "latitude": 12.9716,
            "longitude": 77.5946,
        }).json
        complaint_id = complaint["id"]
        not_completed = self.client.post(
            f"/api/complaints/{complaint_id}/feedback",
            headers=self.citizen_headers,
            json={"rating": 5},
        )
        self.assertEqual(not_completed.status_code, 409)
        eta = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        updated_eta = self.client.patch(
            f"/api/department/complaints/{complaint_id}",
            headers=roads_headers,
            json={"expected_completion_at": eta},
        )
        self.assertEqual(updated_eta.status_code, 200)
        self.assertEqual(updated_eta.json["eta_method"], "department officer estimate")
        for action in ("accept", "in_progress", "complete"):
            result = self.client.patch(
                f"/api/department/complaints/{complaint_id}",
                headers=roads_headers,
                json={"action": action},
            )
            self.assertEqual(result.status_code, 200)
        feedback = self.client.post(
            f"/api/complaints/{complaint_id}/feedback",
            headers=self.citizen_headers,
            json={"rating": 4, "comment": "Repair was completed."},
        )
        self.assertEqual(feedback.status_code, 201)
        duplicate = self.client.post(
            f"/api/complaints/{complaint_id}/feedback",
            headers=self.citizen_headers,
            json={"rating": 5},
        )
        self.assertEqual(duplicate.status_code, 409)
        own_complaint = self.client.get(
            "/api/complaints/mine", headers=self.citizen_headers
        ).json["complaints"][0]
        self.assertEqual(own_complaint["feedback_rating"], 4)

        municipal_headers = self._token("officer@example.test", "municipal")
        analytics = self.client.get("/api/municipal/analytics", headers=municipal_headers)
        self.assertEqual(analytics.status_code, 200)
        self.assertTrue(any(
            item["department"] == "Roads & Transport"
            for item in analytics.json["departments"]
        ))
        forbidden = self.client.patch(
            f"/api/department/complaints/{complaint_id}",
            headers=municipal_headers,
            json={"action": "accept"},
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_failed_notification_retry_is_admin_only_and_deduplicated(self):
        registration = self.client.post("/api/auth/register", json={
            "name": "Retry Citizen",
            "email": "retry@example.test",
            "password": "sample-test-password",
        })
        headers = {"Authorization": f"Bearer {registration.json['token']}"}
        self.app.config["BREVO_SENDER"] = lambda *args: ("failed", None, "provider unavailable")
        complaint = self.client.post("/api/complaints", headers=headers, json={
            "title": "Waste collection",
            "category": "Waste management",
            "description": "Waste was not collected by the scheduled service.",
            "location": "Market Road",
        }).json
        admin_headers = self._token("admin@example.test", "admin")
        deliveries = self.client.get("/api/admin/notification-deliveries", headers=admin_headers)
        failed = next(
            item for item in deliveries.json["deliveries"]
            if item["complaint_id"] == complaint["id"] and item["channel"] == "email"
        )
        self.app.config["BREVO_SENDER"] = lambda *args: ("sent", "mock-email", None)
        retried = self.client.post(
            f"/api/admin/notification-deliveries/{failed['id']}/retry",
            headers=admin_headers,
            json={},
        )
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json["delivery"]["status"], "sent")
        self.assertEqual(self.client.post(
            f"/api/admin/notification-deliveries/{failed['id']}/retry",
            headers=admin_headers,
            json={},
        ).json["delivery"]["status"], "sent")
        municipal_headers = self._token("officer@example.test", "municipal")
        forbidden = self.client.post(
            f"/api/admin/notification-deliveries/{failed['id']}/retry",
            headers=municipal_headers,
            json={},
        )
        self.assertEqual(forbidden.status_code, 403)


if __name__ == "__main__":
    unittest.main()
