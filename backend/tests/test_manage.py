import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from manage import reset_municipal_password


class AccountManagementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "accounts.sqlite"
        self.connection = sqlite3.connect(self.database_path)
        self.connection.executescript("""
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                department TEXT
            );
            CREATE TABLE complaints (
                complaint_id TEXT PRIMARY KEY,
                citizen_id TEXT NOT NULL
            );
        """)
        self.officer_id = str(uuid.uuid4())
        self.department_id = str(uuid.uuid4())
        self.citizen_id = str(uuid.uuid4())
        self.admin_id = str(uuid.uuid4())
        self.connection.executemany(
            """INSERT INTO users (id, email, password_hash, role, department)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    self.officer_id,
                    "officer@smartcivicai.com",
                    generate_password_hash("old-officer-password"),
                    "municipal",
                    None,
                ),
                (
                    self.department_id,
                    "department@smartcivicai.com",
                    generate_password_hash("old-department-password"),
                    "municipal",
                    "Roads & Transport",
                ),
                (
                    self.citizen_id,
                    "citizen@example.test",
                    generate_password_hash("citizen-password"),
                    "citizen",
                    None,
                ),
                (
                    self.admin_id,
                    "admin@example.test",
                    generate_password_hash("admin-password"),
                    "admin",
                    None,
                ),
            ],
        )
        self.connection.execute(
            "INSERT INTO complaints (complaint_id, citizen_id) VALUES (?, ?)",
            ("CIV-2026-TEST", self.citizen_id),
        )
        self.connection.commit()
        self.connection.close()
        self.officer_hash_before = self._account_hash(self.officer_id)
        self.department_hash_before = self._account_hash(self.department_id)
        self.citizen_hash_before = self._account_hash(self.citizen_id)
        self.admin_hash_before = self._account_hash(self.admin_id)

    def tearDown(self):
        self.temporary.cleanup()

    def _account_hash(self, account_id):
        with closing(sqlite3.connect(self.database_path)) as connection:
            return connection.execute(
                "SELECT password_hash FROM users WHERE id = ?", (account_id,)
            ).fetchone()[0]

    def test_reset_changes_only_existing_municipal_password_and_preserves_records(self):
        self.assertTrue(reset_municipal_password(
            self.database_path,
            "OFFICER@SMARTCIVICAI.COM",
            "new-secure-officer-password",
        ))

        officer_hash_after = self._account_hash(self.officer_id)
        self.assertNotEqual(officer_hash_after, self.officer_hash_before)
        self.assertTrue(check_password_hash(
            officer_hash_after, "new-secure-officer-password"
        ))
        self.assertEqual(self._account_hash(self.citizen_id), self.citizen_hash_before)
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 4
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM complaints WHERE complaint_id = ?",
                    ("CIV-2026-TEST",),
                ).fetchone()[0],
                1,
            )

    def test_reset_changes_department_account_password_and_preserves_other_records(self):
        self.assertTrue(reset_municipal_password(
            self.database_path,
            "DEPARTMENT@SMARTCIVICAI.COM",
            "new-secure-department-password",
        ))

        department_hash_after = self._account_hash(self.department_id)
        self.assertNotEqual(department_hash_after, self.department_hash_before)
        self.assertTrue(check_password_hash(
            department_hash_after, "new-secure-department-password"
        ))
        self.assertEqual(self._account_hash(self.officer_id), self.officer_hash_before)
        self.assertEqual(self._account_hash(self.citizen_id), self.citizen_hash_before)
        self.assertEqual(self._account_hash(self.admin_id), self.admin_hash_before)
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 4
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM complaints").fetchone()[0], 1
            )

    def test_reset_refuses_non_municipal_accounts_and_invalid_passwords(self):
        self.assertFalse(reset_municipal_password(
            self.database_path, "citizen@example.test", "new-citizen-password"
        ))
        self.assertFalse(reset_municipal_password(
            self.database_path, "admin@example.test", "new-admin-password"
        ))
        self.assertEqual(self._account_hash(self.citizen_id), self.citizen_hash_before)
        self.assertEqual(self._account_hash(self.admin_id), self.admin_hash_before)
        with self.assertRaises(ValueError):
            reset_municipal_password(
                self.database_path, "officer@smartcivicai.com", "short"
            )
        self.assertEqual(self._account_hash(self.officer_id), self.officer_hash_before)


if __name__ == "__main__":
    unittest.main()
