"""Tests for the restricted local secret loader."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_env import load_local_environment


class LocalEnvironmentTests(unittest.TestCase):
    def test_careeronestop_credentials_load_but_unknown_values_do_not(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "CAREERONESTOP_USER_ID=approved-user\n"
                "CAREERONESTOP_API_TOKEN=approved-token\n"
                "UNSUPPORTED_SECRET=do-not-load\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                loaded = load_local_environment(path)
                self.assertEqual(loaded, 2)
                self.assertEqual(os.environ["CAREERONESTOP_USER_ID"], "approved-user")
                self.assertEqual(os.environ["CAREERONESTOP_API_TOKEN"], "approved-token")
                self.assertNotIn("UNSUPPORTED_SECRET", os.environ)


if __name__ == "__main__":
    unittest.main()
