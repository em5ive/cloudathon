"""Regression checks for artifact classification and redacted credential detection."""
from pathlib import Path
import runpy
import unittest

CHECK = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/check-repository-safety.py"))


class RepositorySafetyTests(unittest.TestCase):
    def test_generated_and_private_paths_are_rejected(self):
        for name in ("terraform/.terraform/provider", ".build/profile/Network/Cookies", "terraform/state.tfstate.backup",
                     "terraform/terraform.tfvars", "User Data/Default/Cookies", "reports/session.json", "session-token.txt"):
            with self.subTest(name=name):
                self.assertTrue(CHECK["private_path"](name))

    def test_templates_lock_and_public_roots_remain_source(self):
        for name in ("terraform/terraform.tfvars.example", "terraform/.terraform.lock.hcl", ".env.example",
                     "backend/shared/certs/AmazonRootCA1.pem", "backend/shared/db.py"):
            with self.subTest(name=name):
                self.assertFalse(CHECK["private_path"](name))

    def test_credentials_detected_without_printing_values(self):
        synthetic = "ASIA" + "A" * 16
        self.assertIsNotNone(CHECK["RULES"]["AWS access key ID"].search(synthetic))
        self.assertIsNotNone(CHECK["RULES"]["Private key PEM"].search("-----BEGIN " + "PRIVATE KEY-----\nfixture"))
        self.assertIsNotNone(CHECK["RULES"]["AWS credential assignment"].search("aws_session_token=" + "A" * 40))


if __name__ == "__main__":
    unittest.main()
