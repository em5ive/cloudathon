"""Offline tests: authentication is distinct from authorization and feature support."""
import argparse
from contextlib import redirect_stdout
import io
from pathlib import Path
import runpy
import subprocess
import unittest
from unittest.mock import patch

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/aws-preflight.py"))


class PreflightTests(unittest.TestCase):
    def args(self, *values):
        return MODULE["parser"]().parse_args(values)

    def fixture_read(self, *arguments, unreserved=110, **kwargs):
        command = arguments[1]
        data = []
        if command == "get-caller-identity":
            data = {"Account": "123456789012"}
        elif command == "describe-availability-zones":
            data = ["us-west-2a", "us-west-2b"]
        elif command == "describe-orderable-db-instance-options":
            data = [{"Version": "17.4", "Class": "db.serverless", "AZs": ["us-west-2a", "us-west-2b"]}]
        elif command == "describe-vpc-endpoint-services":
            data = [{"Types": ["Interface"], "PrivateDNS": "example.amazonaws.com", "AZs": ["us-west-2a", "us-west-2b"]}]
        elif command == "get-account-settings":
            data = {"Concurrent": unreserved, "Unreserved": unreserved}
        return {"status": "PASS", "data": data}

    def quota_denied_fixture(self, *arguments, **kwargs):
        if arguments[:2] == ("service-quotas", "list-service-quotas"):
            return {"status": "BLOCKED", "category": "READ_PERMISSION_DENIED", "error": "AccessDeniedException: servicequotas:ListServiceQuotas is denied"}
        return self.fixture_read(*arguments, **kwargs)

    def test_no_credentials_does_not_assert_service_denial(self):
        calls = []
        def invoke(*args, **kwargs):
            calls.append(args)
            return {"status": "BLOCKED", "category": "AUTHENTICATION_UNAVAILABLE", "error": "NoCredentials"}
        report = MODULE["collect"](self.args(), None, invoke)
        self.assertEqual(len(calls), 1)
        self.assertFalse(report["ready_for_authenticated_terraform_plan"])
        self.assertFalse(report["checks"]["db_proxies"]["attempted"])
        self.assertNotIn("READ_PERMISSION_DENIED", str(report))

    def test_wrong_account_stops_inventory(self):
        calls = []
        def invoke(*args, **kwargs):
            calls.append(args)
            return {"status": "PASS", "data": {"Account": "999999999999"}}
        report = MODULE["collect"](self.args("--expected-account-id", "123456789012"), "us-west-2", invoke)
        self.assertEqual(len(calls), 1)
        self.assertEqual(report["checks"]["account_verification"]["status"], "FAIL")
        self.assertFalse(report["ready_for_deployment"])

    def test_no_model_invocation_or_secret_values_in_read_commands(self):
        commands = MODULE["read_calls"]("17.4", "example.model-v1:0")
        for command in commands.values():
            self.assertNotIn(command[1], ("converse", "invoke-model", "get-secret-value", "create-db-proxy", "put-secret-value"))
        self.assertIn("bedrock_model_availability", commands)
        self.assertIn("bedrock_model_details", commands)
        self.assertIn("secretsmanager_endpoint", commands)

    def test_authentication_and_read_denial_categories_are_distinct(self):
        self.assertEqual(MODULE["error_category"]("NoCredentials: Unable to locate credentials"), "AUTHENTICATION_UNAVAILABLE")
        self.assertEqual(MODULE["error_category"]("AccessDeniedException: not authorized to perform rds:DescribeDBProxies"), "READ_PERMISSION_DENIED")

    def test_expired_login_session_is_authentication_unavailable(self):
        self.assertEqual(MODULE["error_category"]("Your session has expired. Please reauthenticate using aws login"), "AUTHENTICATION_UNAVAILABLE")

    def test_published_proxy_compatibility_has_correct_scope(self):
        self.assertEqual(MODULE["proxy_compatibility"]("17.3")["status"], "FAIL")
        compatible = MODULE["proxy_compatibility"]("17.4")
        self.assertEqual(compatible["status"], "PASS")
        self.assertEqual(compatible["scope"], "DOCUMENTED_FEATURE_SUPPORT")
        self.assertEqual(MODULE["proxy_compatibility"](None)["status"], "NOT TESTED")

    def test_cli_missing_returns_blocked_without_crashing(self):
        with patch.object(subprocess, "run", side_effect=FileNotFoundError):
            result = MODULE["aws"]("sts", "get-caller-identity")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["category"], "CLI_MISSING")

    def test_unsupported_az_or_insufficient_concurrency_cannot_pass(self):
        args = self.args("--engine-version", "17.4")
        checks = {name: {"status": "PASS", "data": []} for name in MODULE["read_calls"]()}
        checks["availability_zones"]["data"] = ["us-west-2a", "us-west-2b"]
        checks["serverless_classes"]["data"] = [{"Version": "17.4", "Class": "db.serverless", "AZs": ["us-west-2a"]}]
        checks["lambda_account_limits"]["data"] = {"Concurrent": 100, "Unreserved": 100}
        report = {"checks": checks}
        MODULE["add_capability_checks"](report, args)
        self.assertEqual(checks["selected_serverless_version"]["status"], "FAIL")
        self.assertEqual(checks["lambda_reserved_capacity"]["status"], "FAIL")

    def test_read_evidence_can_enable_plan_but_never_deployment(self):
        args = self.args("--engine-version", "17.4", "--expected-account-id", "123456789012")
        def invoke(*arguments, **kwargs):
            command = arguments[1]
            data = []
            if command == "get-caller-identity":
                data = {"Account": "123456789012"}
            elif command == "describe-availability-zones":
                data = ["us-west-2a", "us-west-2b"]
            elif command == "describe-orderable-db-instance-options":
                data = [{"Version": "17.4", "Class": "db.serverless", "AZs": ["us-west-2a", "us-west-2b"]}]
            elif command == "describe-vpc-endpoint-services":
                data = [{"Types": ["Interface"], "PrivateDNS": "example.amazonaws.com", "AZs": ["us-west-2a", "us-west-2b"]}]
            elif command == "get-account-settings":
                data = {"Concurrent": 1000, "Unreserved": 1000}
            return {"status": "PASS", "data": data}
        with redirect_stdout(io.StringIO()):
            report = MODULE["collect"](args, None, invoke)
        self.assertTrue(report["ready_for_authenticated_terraform_plan"])
        self.assertFalse(report["ready_for_deployment"])
        self.assertEqual(report["checks"]["converse_runtime_inference"]["status"], "NOT TESTED")
        self.assertEqual(report["checks"]["provisioning_permissions"]["status"], "NOT TESTED")

    def test_existing_runtime_reservations_are_not_subtracted_twice(self):
        args = self.args("--runtime-only")
        checks = {
            "lambda_account_limits": {"status": "PASS", "data": {"Unreserved": 100}},
            "functions": {"status": "PASS", "data": ["uh-retail-poc-products", "uh-retail-poc-orders", "uh-retail-poc-support"]},
        }
        for service, amount in (("products", 5), ("orders", 5), ("support", 3)):
            checks[f"existing_concurrency_{service}"] = {"status": "PASS", "data": {"ReservedConcurrentExecutions": amount}}
        capacity = MODULE["reservation_capacity"](checks, args)
        self.assertEqual(capacity["status"], "PASS")
        self.assertEqual(capacity["required_additional_reservations"], 0)
        self.assertEqual(capacity["unreserved_after_increases"], 100)

    def test_only_positive_reservation_changes_consume_headroom(self):
        args = self.args("--runtime-only")
        checks = {
            "lambda_account_limits": {"status": "PASS", "data": {"Unreserved": 101}},
            "functions": {"status": "PASS", "data": ["uh-retail-poc-products", "uh-retail-poc-orders", "uh-retail-poc-support"]},
            "existing_concurrency_products": {"status": "PASS", "data": {"ReservedConcurrentExecutions": 9}},
            "existing_concurrency_orders": {"status": "PASS", "data": {"ReservedConcurrentExecutions": 2}},
            "existing_concurrency_support": {"status": "PASS", "data": {"ReservedConcurrentExecutions": 3}},
        }
        capacity = MODULE["reservation_capacity"](checks, args)
        self.assertEqual(capacity["status"], "PASS")
        self.assertEqual(capacity["required_additional_reservations"], 1)

    def test_unreadable_existing_reservations_require_review_instead_of_false_failure(self):
        checks = {
            "lambda_account_limits": {"status": "PASS", "data": {"Unreserved": 100}},
            "functions": {"status": "PASS", "data": ["uh-retail-poc-products"]},
            "existing_concurrency_products": {"status": "BLOCKED", "error": "AccessDenied"},
        }
        capacity = MODULE["reservation_capacity"](checks, self.args("--runtime-only"))
        self.assertEqual(capacity["status"], "NOT TESTED")

    def test_default_nine_slots_fit_recorded_110_headroom_without_reinterpreting_report(self):
        # This is offline arithmetic using a fixture drawn from saved evidence;
        # it does not claim that the current account still has this headroom.
        args = self.args()
        self.assertEqual(sum(MODULE["desired_reservations"](args).values()), 9)
        self.assertEqual(sum(MODULE["desired_reservations"](self.args("--runtime-only")).values()), 8)
        checks = {
            "lambda_account_limits": {"status": "PASS", "data": {"Unreserved": 110}},
            "functions": {"status": "PASS", "data": []},
        }
        capacity = MODULE["reservation_capacity"](checks, args)
        self.assertEqual(capacity["status"], "PASS")
        self.assertEqual(capacity["required_additional_reservations"], 9)
        self.assertEqual(capacity["unreserved_after_increases"], 101)

    def test_custom_reservations_match_configuration_and_remain_quota_checked(self):
        args = self.args("--products-concurrency", "4", "--orders-concurrency", "4", "--support-concurrency", "3")
        checks = {
            "lambda_account_limits": {"status": "PASS", "data": {"Unreserved": 110}},
            "functions": {"status": "PASS", "data": []},
        }
        capacity = MODULE["reservation_capacity"](checks, args)
        self.assertEqual(capacity["status"], "FAIL")
        self.assertEqual(capacity["required_additional_reservations"], 12)
        with self.assertRaises(argparse.ArgumentTypeError):
            MODULE["reservation_argument"]("1.5")
        with self.assertRaises(argparse.ArgumentTypeError):
            MODULE["reservation_argument"]("0")

    def test_service_quota_read_denials_are_warnings_and_allow_plan(self):
        args = self.args("--engine-version", "17.4", "--expected-account-id", "123456789012")
        with redirect_stdout(io.StringIO()):
            report = MODULE["collect"](args, "us-west-2", self.quota_denied_fixture)
        self.assertTrue(report["ready_for_authenticated_terraform_plan"])
        self.assertEqual(len(report["warnings"]), 8)
        for key, check in report["checks"].items():
            if key.startswith("quota_"):
                self.assertEqual(check["status"], "UNVERIFIED")
                self.assertEqual(check["severity"], "warning")
                self.assertIn("AccessDenied", check["error"])
                self.assertIn("before applying", check["required_follow_up"])

    def test_confirmed_capacity_failure_still_blocks_plan_with_quota_visibility_warnings(self):
        args = self.args("--engine-version", "17.4", "--expected-account-id", "123456789012")
        def invoke(*arguments, **kwargs):
            return self.quota_denied_fixture(*arguments, unreserved=108, **kwargs)
        with redirect_stdout(io.StringIO()):
            report = MODULE["collect"](args, "us-west-2", invoke)
        self.assertFalse(report["ready_for_authenticated_terraform_plan"])
        self.assertEqual(report["checks"]["lambda_reserved_capacity"]["status"], "FAIL")
        self.assertEqual(len(report["warnings"]), 8)

    def test_other_read_permission_denials_remain_blockers(self):
        args = self.args("--engine-version", "17.4", "--expected-account-id", "123456789012")
        def invoke(*arguments, **kwargs):
            if arguments[:2] == ("rds", "describe-db-clusters"):
                return {"status": "BLOCKED", "category": "READ_PERMISSION_DENIED", "error": "AccessDeniedException"}
            return self.quota_denied_fixture(*arguments, **kwargs)
        with redirect_stdout(io.StringIO()):
            report = MODULE["collect"](args, "us-west-2", invoke)
        self.assertFalse(report["ready_for_authenticated_terraform_plan"])
        self.assertEqual(report["checks"]["db_clusters"]["status"], "BLOCKED")
        self.assertEqual(report["checks"]["naming_conflict_review"]["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
