"""State selection and saved-plan regression checks, without Terraform or AWS."""
from copy import deepcopy
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/retry-plan-guard.py"
GUARD = runpy.run_path(str(SCRIPT))
GuardError = GUARD["GuardError"]


def fixture_state():
    return {
        "version": 4, "terraform_version": "1.17.0", "serial": 116,
        "lineage": GUARD["EXPECTED_LINEAGE"], "outputs": {},
        "resources": [
            {"mode": "managed", "type": "aws_example", "name": "existing",
             "instances": [{"index_key": index, "attributes": {"id": f"resource-{index}"}}
                           for index in range(114)]},
            {"mode": "data", "type": "aws_example", "name": "lookup",
             "instances": [{"index_key": str(index), "attributes": {"id": f"data-{index}"}}
                           for index in range(3)]},
        ],
    }


def fixture_inputs():
    values = {name: "fixture" for name in GUARD["EXPECTED_VARIABLES"]}
    values.update(database_bootstrapped="false", enable_bootstrap="true",
                  aws_region="us-west-2", expected_account_id="708661874787")
    return {"variables": {name: {"value": value} for name, value in values.items()}}


class RecoveryGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.terraform = self.root / "terraform"
        self.terraform.mkdir()
        (self.terraform / "versions.tf").write_text('terraform {\n # backend comments are harmless\n}\n', encoding="utf-8")
        self.state = fixture_state()
        self.state_path = self.terraform / "terraform.tfstate"
        self.write_json(self.state_path, self.state)
        self.input_record = fixture_inputs()
        self.input_path = self.root / "original.json"
        self.write_json(self.input_path, self.input_record)
        self.plan_json = deepcopy(self.input_record)
        self.plan_json["variables"]["database_bootstrapped"]["value"] = False
        self.plan_json["variables"]["enable_bootstrap"]["value"] = True
        addresses = GUARD["state_instances"](self.state)
        self.plan_json.update({
            "applyable": True, "complete": True, "errored": False,
            "prior_state": {"values": {"root_module": {"resources": [
                {"address": address, "mode": item["mode"]} for address, item in addresses.items()
            ]}}},
            "resource_changes": [
                {"address": address, "mode": "managed", "change": {"actions": ["no-op"], "before": {"id": address}}}
                for address, item in addresses.items() if item["mode"] == "managed"
            ] + [{"address": GUARD["MISSING_ADDRESS"], "mode": "managed", "change": {"actions": ["create"], "before": None}}],
        })
        self.plan_path = self.root / "new.tfplan"
        self.json_path = self.root / "new.json"
        self.write_plan()

    @staticmethod
    def write_json(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def write_plan(self, previous=None, refreshed=None):
        previous = deepcopy(self.state) if previous is None else previous
        previous["lineage"] = ""
        previous["serial"] = 0
        refreshed = deepcopy(self.state) if refreshed is None else refreshed
        with zipfile.ZipFile(self.plan_path, "w") as archive:
            archive.writestr("tfstate-prev", json.dumps(previous))
            archive.writestr("tfstate", json.dumps(refreshed))
        self.write_json(self.json_path, self.plan_json)

    def selection(self, state=None, workspace="default", environment=None):
        return GUARD["audit_selection"](self.state_path, self.state if state is None else state,
                                        workspace, self.terraform, {} if environment is None else environment)

    def plan(self):
        return GUARD["audit_plan"](self.state_path, self.plan_path, self.json_path, self.input_path)

    def test_selection_accepts_117_indexed_instances(self):
        report = self.selection()
        self.assertTrue(report["approved"])
        self.assertEqual(117, report["instance_count"])
        self.assertIn('data.aws_example.lookup["2"]', report["addresses"])
        self.assertIn("aws_example.existing[113]", report["addresses"])

    def test_selection_rejects_wrong_lineage_serial_and_empty_state(self):
        for field, value in (("lineage", "different"), ("serial", 117), ("resources", [])):
            with self.subTest(field=field):
                effective = deepcopy(self.state)
                effective[field] = value
                with self.assertRaises(GuardError):
                    self.selection(effective)

    def test_selection_compares_resource_content_not_only_count(self):
        effective = deepcopy(self.state)
        effective["resources"][0]["instances"][0]["attributes"]["id"] = "another-deployment"
        with self.assertRaisesRegex(GuardError, "Effective Terraform state differs"):
            self.selection(effective)

    def test_selection_rejects_all_cli_argument_overrides_without_values(self):
        marker = "DO-NOT-PRINT-THIS-SECRET"
        for name in ("TF_WORKSPACE", "TF_DATA_DIR", "TF_CLI_ARGS", "TF_CLI_ARGS_plan", "TF_CLI_ARGS_state", "TF_CLI_ARGS_show"):
            with self.subTest(name=name), self.assertRaises(GuardError) as caught:
                self.selection(environment={name: marker})
            self.assertNotIn(marker, str(caught.exception))

    def test_selection_rejects_nondefault_workspace(self):
        with self.assertRaises(GuardError):
            self.selection(workspace="other")

    def test_selection_rejects_explicit_backend_and_cloud_blocks(self):
        for config in ('terraform { backend "s3" {} }', 'terraform { backend "local" {} }', 'terraform { cloud {} }'):
            with self.subTest(config=config):
                (self.terraform / "versions.tf").write_text(config, encoding="utf-8")
                with self.assertRaises(GuardError):
                    self.selection()

    def test_selection_rejects_json_backend_configuration(self):
        self.write_json(self.terraform / "backend.tf.json", {"terraform": {"backend": {"s3": {}}}})
        with self.assertRaises(GuardError):
            self.selection()

    def test_selection_rejects_wrong_cached_backend_and_path(self):
        cache = self.terraform / ".terraform"
        cache.mkdir()
        for backend in ({"type": "s3", "config": {}}, {"type": "local", "config": {"path": "other.tfstate"}}):
            with self.subTest(backend=backend):
                self.write_json(cache / "terraform.tfstate", {"backend": backend})
                with self.assertRaises(GuardError):
                    self.selection()

    def test_selection_accepts_cached_local_backend_pointing_at_actual_state(self):
        cache = self.terraform / ".terraform"
        cache.mkdir()
        self.write_json(cache / "terraform.tfstate", {"backend": {"type": "local", "config": {"path": str(self.state_path)}}})
        self.assertTrue(self.selection()["approved"])

    def test_selection_rejects_tainted_deposed_and_duplicate_instances(self):
        for modifier in (lambda s: s["resources"][0]["instances"][0].update(status="tainted"),
                         lambda s: s["resources"][0]["instances"][0].update(deposed="deadbeef"),
                         lambda s: s["resources"][0]["instances"][1].update(index_key=0)):
            state = deepcopy(self.state)
            modifier(state)
            with self.assertRaises(GuardError):
                GUARD["validate_recorded_state"](state)

    def test_plan_accepts_only_missing_sns_create_and_normalized_booleans(self):
        report = self.plan()
        self.assertTrue(report["approved"])
        self.assertEqual(114, report["tracked_managed_preserved"])
        self.assertEqual([{"address": GUARD["MISSING_ADDRESS"], "actions": ["create"]}], report["managed_changes"])

    def test_plan_rejects_create_for_tracked_address(self):
        self.plan_json["resource_changes"][0]["change"] = {"actions": ["create"], "before": None}
        self.write_plan()
        report = self.plan()
        self.assertFalse(report["approved"])
        self.assertTrue(any("already tracked" in issue for issue in report["violations"]))

    def test_plan_rejects_replacement_and_other_managed_update(self):
        for actions in (["delete", "create"], ["create", "delete"], ["update"]):
            with self.subTest(actions=actions):
                self.plan_json["resource_changes"][0]["change"]["actions"] = actions
                self.write_plan()
                self.assertFalse(self.plan()["approved"])

    def test_plan_rejects_different_embedded_prior_resources_or_outputs(self):
        for field, value in (("resources", []), ("outputs", {"unexpected": {"value": "secret"}})):
            with self.subTest(field=field):
                previous = deepcopy(self.state)
                previous[field] = value
                self.write_plan(previous=previous)
                with self.assertRaisesRegex(GuardError, "prior state differs"):
                    self.plan()

    def test_plan_rejects_wrong_refreshed_lineage_or_serial(self):
        for field, value in (("lineage", "other"), ("serial", 117)):
            with self.subTest(field=field):
                refreshed = deepcopy(self.state)
                refreshed[field] = value
                self.write_plan(refreshed=refreshed)
                with self.assertRaises(GuardError):
                    self.plan()

    def test_plan_rejects_missing_preserved_managed_address(self):
        self.plan_json["prior_state"]["values"]["root_module"]["resources"].pop(0)
        self.write_plan()
        with self.assertRaisesRegex(GuardError, "117 tracked"):
            self.plan()

    def test_plan_rejects_variable_changes_or_boolean_numeric_substitution(self):
        for name, value in (("owner", "different"), ("database_bootstrapped", 0)):
            with self.subTest(name=name):
                original = deepcopy(self.plan_json)
                self.plan_json["variables"][name]["value"] = value
                self.write_plan()
                with self.assertRaises(GuardError):
                    self.plan()
                self.plan_json = original

    def test_plan_rejects_errored_incomplete_and_unapplyable_plan(self):
        for field, value in (("errored", True), ("complete", False), ("applyable", False)):
            with self.subTest(field=field):
                original = self.plan_json[field]
                self.plan_json[field] = value
                self.write_plan()
                with self.assertRaises(GuardError):
                    self.plan()
                self.plan_json[field] = original

    def test_cli_accepts_state_from_stdin_and_writes_only_metadata(self):
        self.state["resources"][0]["instances"][0]["attributes"]["private_marker"] = "DO-NOT-PRINT-THIS-SECRET"
        self.write_json(self.state_path, self.state)
        report_path = self.root / "selection-audit.json"
        environment = {name: value for name, value in os.environ.items()
                       if name.upper() not in ("TF_WORKSPACE", "TF_DATA_DIR") and not name.upper().startswith("TF_CLI_ARGS")}
        result = subprocess.run([sys.executable, str(SCRIPT), "selection", "--state", str(self.state_path),
                                 "--effective-state", "-", "--workspace", "default", "--terraform-dir", str(self.terraform),
                                 "--report", str(report_path)], input=json.dumps(self.state), capture_output=True,
                                text=True, env=environment, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(report_path.read_text())["approved"])
        self.assertNotIn("DO-NOT-PRINT-THIS-SECRET", result.stdout + result.stderr + report_path.read_text())

    def test_parser_accepts_decoded_unicode_bom(self):
        self.assertEqual({"marker": "caf\u00e9"}, GUARD["parse_json"]('\ufeff{"marker": "caf\u00e9"}', "fixture JSON"))

    def test_cli_accepts_utf8_and_utf16_bom_state_pipes(self):
        self.state["resources"][0]["instances"][0]["attributes"]["private_marker"] = "PRIVATE caf\u00e9 \u6771\u4eac"
        self.write_json(self.state_path, self.state)
        document = json.dumps(self.state, ensure_ascii=False)
        environment = {name: value for name, value in os.environ.items()
                       if name.upper() not in ("TF_WORKSPACE", "TF_DATA_DIR") and not name.upper().startswith("TF_CLI_ARGS")}
        encodings = {
            "utf8-bom": document.encode("utf-8-sig"),
            "utf16-le-bom": b"\xff\xfe" + document.encode("utf-16-le"),
            "utf16-be-bom": b"\xfe\xff" + document.encode("utf-16-be"),
        }
        for encoding, payload in encodings.items():
            with self.subTest(encoding=encoding):
                report_path = self.root / f"selection-{encoding}.json"
                result = subprocess.run([sys.executable, str(SCRIPT), "selection", "--state", str(self.state_path),
                                         "--effective-state", "-", "--workspace", "default", "--terraform-dir", str(self.terraform),
                                         "--report", str(report_path)], input=payload, capture_output=True,
                                        env=environment, check=False)
                self.assertEqual(0, result.returncode, result.stderr.decode("utf-8", errors="replace"))
                report = report_path.read_bytes()
                self.assertTrue(json.loads(report)["approved"])
                self.assertNotIn(b"PRIVATE", result.stdout + result.stderr + report)

    def test_cli_rejects_malformed_encoded_state_without_printing_contents(self):
        report_path = self.root / "malformed-encoding.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "selection", "--state", str(self.state_path),
                                 "--effective-state", "-", "--workspace", "default", "--terraform-dir", str(self.terraform),
                                 "--report", str(report_path)], input=b"\xef\xbb\xbfPRIVATE\xff", capture_output=True,
                                check=False)
        self.assertEqual(1, result.returncode)
        report = report_path.read_bytes()
        self.assertFalse(json.loads(report)["approved"])
        self.assertNotIn(b"PRIVATE", result.stdout + result.stderr + report)

    def test_cli_rejects_unexpected_changes_with_review_report(self):
        self.plan_json["resource_changes"][0]["change"]["actions"] = ["update"]
        self.write_plan()
        report_path = self.root / "plan-audit.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "plan", "--state", str(self.state_path),
                                 "--plan", str(self.plan_path), "--json", str(self.json_path),
                                 "--input-record", str(self.input_path), "--report", str(report_path)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(1, result.returncode)
        self.assertFalse(json.loads(report_path.read_text())["approved"])

    def test_cli_does_not_overwrite_input_or_existing_reports(self):
        original = self.state_path.read_bytes()
        args = ["plan", "--state", str(self.state_path), "--plan", str(self.plan_path),
                "--json", str(self.json_path), "--input-record", str(self.input_path), "--report", str(self.state_path)]
        result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)
        self.assertEqual(1, result.returncode)
        self.assertEqual(original, self.state_path.read_bytes())
        report = self.root / "existing-report.json"
        report.write_text("preserve this review", encoding="utf-8")
        args[-1] = str(report)
        result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)
        self.assertEqual(1, result.returncode)
        self.assertEqual("preserve this review", report.read_text())

    def test_cli_never_creates_missing_input_as_error_report(self):
        missing_state = self.root / "missing.tfstate"
        result = subprocess.run([sys.executable, str(SCRIPT), "plan", "--state", str(missing_state),
                                 "--plan", str(self.plan_path), "--json", str(self.json_path),
                                 "--input-record", str(self.input_path), "--report", str(missing_state)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(1, result.returncode)
        self.assertFalse(missing_state.exists())


if __name__ == "__main__":
    unittest.main()
