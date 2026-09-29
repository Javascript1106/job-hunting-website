"""Regression tests for one-time authentication verification codes."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import auth
from database import get_connection, initialize_database


class AuthenticationVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = str(
            Path(self.temporary_directory.name) / "verification-tests.db"
        )
        initialize_database(self.database_path)
        connection = get_connection(self.database_path)
        cursor = connection.execute(
            """INSERT INTO users (username, email, password, role)
               VALUES (?, ?, ?, 'job_seeker')""",
            (
                "verification_user",
                "verification@example.com",
                auth.hash_password("A unique verification test passphrase"),
            ),
        )
        self.user_id = cursor.lastrowid
        connection.commit()
        connection.close()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def create_known_code(self, purpose="email_verification"):
        connection = get_connection(self.database_path)
        with patch("auth.secrets.randbelow", return_value=123456):
            code = auth.create_account_code(
                connection.cursor(), self.user_id, purpose
            )
        connection.commit()
        connection.close()
        return code

    def test_valid_code_can_only_be_used_once(self):
        code = self.create_known_code()
        connection = get_connection(self.database_path)
        cursor = connection.cursor()

        self.assertTrue(
            auth.verify_account_code(
                cursor, self.user_id, "email_verification", code
            )
        )
        connection.commit()
        self.assertFalse(
            auth.verify_account_code(
                cursor, self.user_id, "email_verification", code
            )
        )
        connection.close()

    def test_expired_code_is_rejected(self):
        code = self.create_known_code("password_reset")
        connection = get_connection(self.database_path)
        connection.execute(
            """UPDATE account_tokens SET expires_at = datetime('now', '-1 minute')
               WHERE user_id = ? AND purpose = 'password_reset'""",
            (self.user_id,),
        )
        connection.commit()

        self.assertFalse(
            auth.verify_account_code(
                connection.cursor(), self.user_id, "password_reset", code
            )
        )
        connection.close()

    def test_wrong_code_or_purpose_is_rejected(self):
        code = self.create_known_code("sensitive_action")
        connection = get_connection(self.database_path)
        cursor = connection.cursor()

        self.assertFalse(
            auth.verify_account_code(
                cursor, self.user_id, "sensitive_action", "000000"
            )
        )
        self.assertFalse(
            auth.verify_account_code(
                cursor, self.user_id, "email_verification", code
            )
        )
        connection.close()


if __name__ == "__main__":
    unittest.main()
