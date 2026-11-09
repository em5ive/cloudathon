"""Fail closed when a recovery plan does not use the recorded partial state.

Only local files and the captured output of read-only Terraform commands are
inspected. State attributes and input values are never included in reports or
diagnostics. This command never invokes Terraform or AWS.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import zipfile


EXPECTED_LINEAGE = "63898c23-df79-bbe8-2583-c2dc39531dfe"
EXPECTED_SERIAL = 116
EXPECTED_MANAGED = 114
EXPECTED_DATA = 3
MISSING_ADDRESS = "aws_sns_topic_policy.operations"
EXPECTED_VARIABLES = frozenset((
    "alarm_email", "aurora_engine_version", "aws_region", "bedrock_model_arn",
    "bedrock_model_id", "database_bootstrapped", "enable_bootstrap",
    "expected_account_id", "lambda_canary_versions", "lambda_live_versions",
    "lambda_reserved_concurrency", "log_retention_days", "max_acu", "min_acu",
    "owner", "project_name",
))


class GuardError(ValueError):
    """A diagnostic that contains no state attributes or input values."""


def require(condition, message):
    if not condition:
        raise GuardError(message)


def parse_json(data, description):
    try:
        # json.loads detects UTF-8/16/32 and their BOMs from bytes. A text
        # stream may have already decoded the BOM to a Unicode character.
        if isinstance(data, str):
            data = data.removeprefix("\ufeff")
        value = json.loads(data)
    except (ValueError, UnicodeError):
        raise GuardError(f"Cannot parse {description}; contents were not printed.") from None
    require(isinstance(value, dict), f"{description} must contain a JSON object.")
    return value


def read_json(path, description):
    try:
        data = Path(path).read_bytes()
    except OSError:
        raise GuardError(f"Cannot read {description}.") from None
    return parse_json(data, description), data


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def semantic_equal(left, right):
    # JSON booleans must not compare equal to numeric zero/one in Python.
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(semantic_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(semantic_equal(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right or (
        isinstance(left, (int, float)) and isinstance(right, (int, float)) and left == right
    )


def state_instances(state):
    require(isinstance(state.get("resources"), list), "State resources are absent or malformed.")
    result = {}
    for resource in state["resources"]:
        require(isinstance(resource, dict), "A state resource is malformed.")
        mode = resource.get("mode")
        require(mode in ("managed", "data"), "A state resource has an unsupported mode.")
        parts = []
        module = resource.get("module")
        if module:
            require(isinstance(module, str), "A state module address is malformed.")
            parts.append(module)
        if mode == "data":
            parts.append("data")
        for field in ("type", "name"):
            require(isinstance(resource.get(field), str) and bool(resource[field]), "A state resource address is malformed.")
            parts.append(resource[field])
        base = ".".join(parts)
        instances = resource.get("instances")
        require(isinstance(instances, list), "State resource instances are malformed.")
        for instance in instances:
            require(isinstance(instance, dict), "A state instance is malformed.")
            require(instance.get("status") != "tainted", "The recorded state contains a tainted instance.")
            require(not instance.get("deposed"), "The recorded state contains a deposed instance.")
            require(instance.get("status") in (None, "ready"), "A state instance has an unexpected status.")
            address = base
            if "index_key" in instance:
                key = instance["index_key"]
                require(type(key) in (int, str), "A state instance index is malformed.")
                address += "[" + json.dumps(key, ensure_ascii=False, separators=(",", ":")) + "]"
            require(address not in result, "The recorded state contains duplicate instance addresses.")
            require(isinstance(instance.get("attributes"), dict), "A state instance has no attribute record.")
            result[address] = {"mode": mode, "instance": instance}
    return result


def validate_recorded_state(state):
    require(state.get("version") == 4, "Unexpected Terraform state format.")
    require(state.get("lineage") == EXPECTED_LINEAGE, "State lineage differs from the recorded partial deployment.")
    require(type(state.get("serial")) is int and state["serial"] == EXPECTED_SERIAL,
            "State serial differs from the recorded partial deployment.")
    instances = state_instances(state)
    managed = {address for address, item in instances.items() if item["mode"] == "managed"}
    data = set(instances) - managed
    require(len(managed) == EXPECTED_MANAGED and len(data) == EXPECTED_DATA,
            "State does not contain the recorded 114 managed and 3 data instances.")
    require(MISSING_ADDRESS not in instances, "The SNS policy is already tracked; this recovery scope no longer applies.")
    require(isinstance(state.get("outputs"), dict), "State outputs are absent or malformed.")
    return instances, managed, data


def reject_selection_environment(environment):
    unsafe = sorted(name for name, value in environment.items() if value and (
        name.upper() in ("TF_WORKSPACE", "TF_DATA_DIR") or name.upper().startswith("TF_CLI_ARGS")
    ))
    require(not unsafe, "Terraform selection or argument overrides are set: " + ", ".join(unsafe) + ". Values were not printed.")


def validate_backend(terraform_dir, state_path):
    directory = Path(terraform_dir).resolve()
    expected_path = Path(state_path).resolve()
    require(directory.is_dir(), "Terraform directory does not exist.")
    require(expected_path == directory / "terraform.tfstate", "The expected state is not the Terraform directory's existing local state.")
    # This recovery supports the repository's implicit local backend only.
    # A configured backend requires a separately reviewed recovery procedure.
    comment_or_string = re.compile(r'"(?:[^"\\]|\\.)*"|//[^\r\n]*|\#[^\r\n]*|/\*.*?\*/', re.S)
    for source in directory.glob("*.tf"):
        try:
            text = source.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            raise GuardError("Cannot inspect Terraform backend configuration.") from None
        text = comment_or_string.sub(lambda match: match.group() if match.group().startswith('"') else " ", text)
        require(not re.search(r'\bbackend\s*"[^"\r\n]+"\s*\{|\bcloud\s*\{', text),
                "An explicit backend or cloud block requires separate recovery review.")
    for source in directory.glob("*.tf.json"):
        config, _ = read_json(source, "Terraform JSON configuration")
        blocks = config.get("terraform", [])
        if isinstance(blocks, dict):
            blocks = [blocks]
        require(isinstance(blocks, list), "Terraform JSON configuration is malformed.")
        require(all(isinstance(block, dict) and not ({"backend", "cloud"} & block.keys()) for block in blocks),
                "An explicit backend or cloud block requires separate recovery review.")
    cache_dir = directory / ".terraform"
    workspace_file = cache_dir / "environment"
    if workspace_file.exists():
        try:
            workspace = workspace_file.read_text(encoding="utf-8-sig").strip()
        except (OSError, UnicodeError):
            raise GuardError("Cannot inspect the cached Terraform workspace.") from None
        require(workspace == "default", "The cached Terraform workspace is not default.")
    metadata_path = cache_dir / "terraform.tfstate"
    if metadata_path.exists():
        metadata, _ = read_json(metadata_path, "cached backend metadata")
        backend = metadata.get("backend")
        require(isinstance(backend, dict) and backend.get("type") == "local", "The cached Terraform backend is not local.")
        config = backend.get("config")
        require(isinstance(config, dict), "The cached local backend configuration is malformed.")
        selected_path = config.get("path") or "terraform.tfstate"
        require(isinstance(selected_path, str), "The cached local backend state path is malformed.")
        path = Path(selected_path)
        if not path.is_absolute():
            path = directory / path
        require(path.resolve() == expected_path, "The cached local backend selects another state file.")
        workspace_dir = config.get("workspace_dir")
        require(workspace_dir in (None, "", "terraform.tfstate.d"), "The cached local backend has an unexpected workspace directory.")


def audit_selection(state_path, effective_state, workspace, terraform_dir, environment=None):
    reject_selection_environment(os.environ if environment is None else environment)
    require(workspace == "default", "The effective Terraform workspace is not default.")
    validate_backend(terraform_dir, state_path)
    state, raw = read_json(state_path, "existing partial-deployment state")
    instances, managed, data = validate_recorded_state(state)
    validate_recorded_state(effective_state)
    for field in ("lineage", "serial", "resources", "outputs"):
        require(semantic_equal(state.get(field), effective_state.get(field)),
                "Effective Terraform state differs from the existing partial-deployment state.")
    return {
        "approved": True, "phase": "selection", "backend": "local", "workspace": workspace,
        "state_path": str(Path(state_path).resolve()), "state_sha256": sha256(raw),
        "lineage": state["lineage"], "serial": state["serial"],
        "managed_instances": len(managed), "data_instances": len(data),
        "instance_count": len(instances), "addresses": sorted(instances),
    }


def normalize_variables(record):
    variables = record.get("variables")
    require(isinstance(variables, dict) and set(variables) == EXPECTED_VARIABLES,
            "Plan input names differ from the recorded 16 recovery inputs.")
    result = {}
    for name, item in variables.items():
        require(isinstance(item, dict) and "value" in item, "A recorded plan input is malformed.")
        value = item["value"]
        if name in ("database_bootstrapped", "enable_bootstrap"):
            if isinstance(value, str) and value.strip().lower() in ("true", "false"):
                value = value.strip().lower() == "true"
            require(type(value) is bool, "A recovery stage flag is not a boolean.")
        result[name] = value
    require(result["database_bootstrapped"] is False and result["enable_bootstrap"] is True,
            "The recorded inputs do not describe the reviewed first-stage bootstrap deployment.")
    require(result["aws_region"] == "us-west-2" and result["expected_account_id"] == "708661874787",
            "The recorded inputs differ from the reviewed AWS account or region.")
    return result


def values_instances(module):
    require(isinstance(module, dict), "The plan's prior-state module is malformed.")
    result = {}
    resources = module.get("resources", [])
    children = module.get("child_modules", [])
    require(isinstance(resources, list) and isinstance(children, list), "The plan's prior-state resources are malformed.")
    for resource in resources:
        require(isinstance(resource, dict) and isinstance(resource.get("address"), str)
                and resource.get("mode") in ("managed", "data"), "The plan's prior-state address is malformed.")
        address = resource["address"]
        require(address not in result, "The plan's prior state has duplicate addresses.")
        result[address] = resource
    for child in children:
        for address, resource in values_instances(child).items():
            require(address not in result, "The plan's prior state has duplicate addresses.")
            result[address] = resource
    return result


def audit_plan(state_path, plan_path, json_path, input_record):
    state, raw = read_json(state_path, "existing partial-deployment state")
    instances, managed, data = validate_recorded_state(state)
    try:
        binary = Path(plan_path).read_bytes()
        with zipfile.ZipFile(io.BytesIO(binary)) as archive:
            require(archive.namelist().count("tfstate-prev") == 1 and archive.namelist().count("tfstate") == 1,
                    "Saved plan must contain exactly one prior and refreshed state snapshot.")
            previous = parse_json(archive.read("tfstate-prev"), "embedded prior state")
            refreshed = parse_json(archive.read("tfstate"), "embedded refreshed state")
    except (OSError, KeyError, zipfile.BadZipFile, RuntimeError):
        raise GuardError("Cannot inspect the saved plan's embedded state; contents were not printed.") from None
    # Terraform intentionally clears lineage/serial in tfstate-prev. Compare the
    # resource/output payload, while validating refreshed snapshot metadata.
    for field in ("resources", "outputs"):
        require(semantic_equal(previous.get(field), state.get(field)),
                "Saved plan prior state differs from the existing partial-deployment state.")
    refreshed_instances, refreshed_managed, refreshed_data = validate_recorded_state(refreshed)
    require(refreshed_managed == managed and refreshed_data == data,
            "Saved plan refresh does not preserve every recorded state address.")
    for address in managed:
        before_id = instances[address]["instance"]["attributes"].get("id")
        after_id = refreshed_instances[address]["instance"]["attributes"].get("id")
        require(semantic_equal(before_id, after_id), "Saved plan refresh changed a tracked resource identity.")
    plan, _ = read_json(json_path, "rendered plan JSON")
    original, _ = read_json(input_record, "original plan input record")
    require(plan.get("applyable") is True and plan.get("errored") is False and plan.get("complete") is True,
            "The saved plan is not complete and applyable without errors.")
    require(semantic_equal(normalize_variables(original), normalize_variables(plan)),
            "Retry plan variables differ from the original 16 inputs.")
    prior_state = plan.get("prior_state", {})
    require(isinstance(prior_state, dict) and isinstance(prior_state.get("values"), dict), "The plan has no prior-state values.")
    prior = values_instances(prior_state["values"].get("root_module"))
    prior_managed = {address for address, item in prior.items() if item["mode"] == "managed"}
    prior_data = set(prior) - prior_managed
    require(prior_managed == managed and prior_data == data, "Rendered plan prior state does not preserve all 117 tracked addresses.")
    changes = plan.get("resource_changes")
    require(isinstance(changes, list), "The rendered plan has no resource change list.")
    observed = set()
    observed_managed = set()
    changed = []
    violations = []
    sns_creates = 0
    for change in changes:
        require(isinstance(change, dict) and isinstance(change.get("address"), str), "A planned resource address is malformed.")
        address = change["address"]
        require(address not in observed, "The plan contains duplicate resource change addresses.")
        observed.add(address)
        mode = change.get("mode")
        require(mode in ("managed", "data") and isinstance(change.get("change"), dict), "A planned resource change is malformed.")
        actions = change["change"].get("actions")
        require(isinstance(actions, list) and actions and all(isinstance(action, str) for action in actions),
                "A planned action is malformed.")
        if mode == "managed":
            observed_managed.add(address)
        if "delete" in actions:
            violations.append("A resource deletion or replacement is planned.")
        if address in instances and "create" in actions:
            violations.append("A create is planned for an address already tracked in state.")
        if mode == "managed" and actions != ["no-op"]:
            changed.append({"address": address, "actions": actions})
            if address == MISSING_ADDRESS and actions == ["create"] and change["change"].get("before") is None:
                sns_creates += 1
            else:
                violations.append("Managed changes extend beyond creation of the missing SNS policy.")
        elif mode == "managed" and address not in managed:
            violations.append("An unknown managed address appears as an existing resource.")
        elif mode == "data" and actions not in (["read"], ["no-op"]):
            violations.append("A data resource has an unexpected planned action.")
    require(managed <= observed_managed, "The plan omits tracked managed resources from its change records.")
    if sns_creates != 1:
        violations.append("Exactly one missing SNS policy creation is required.")
    return {
        "approved": not violations, "phase": "plan", "state_sha256": sha256(raw),
        "plan_sha256": sha256(binary), "lineage": state["lineage"], "serial": state["serial"],
        "managed_instances": len(managed), "data_instances": len(data),
        "original_variables_match": True, "embedded_prior_state_matches": True,
        "tracked_managed_preserved": len(managed), "managed_changes": changed,
        "violations": sorted(set(violations)),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    selection = subparsers.add_parser("selection")
    selection.add_argument("--state", required=True)
    selection.add_argument("--effective-state", required=True, help="Captured state-pull JSON, or - for stdin")
    selection.add_argument("--workspace", required=True)
    selection.add_argument("--terraform-dir", required=True)
    selection.add_argument("--report", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--state", required=True)
    plan.add_argument("--plan", required=True)
    plan.add_argument("--json", required=True)
    plan.add_argument("--input-record", required=True)
    plan.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    report_path = Path(args.report)
    sources = [args.state]
    if args.command == "selection":
        if args.effective_state != "-":
            sources.append(args.effective_state)
    else:
        sources += [args.plan, args.json, args.input_record]
    if report_path.resolve() in {Path(path).resolve() for path in sources} or report_path.exists():
        print("FAIL: The guard report must be a fresh path distinct from every input. No input files were changed.", file=sys.stderr)
        return 1
    try:
        if args.command == "selection":
            if args.effective_state == "-":
                # Read the pipe as bytes so a PowerShell encoding/BOM does
                # not pass through Python's console codepage first.
                effective = parse_json(sys.stdin.buffer.read(), "captured effective state")
            else:
                effective, _ = read_json(args.effective_state, "captured effective state")
            report = audit_selection(args.state, effective, args.workspace, args.terraform_dir)
        else:
            report = audit_plan(args.state, args.plan, args.json, args.input_record)
    except GuardError as error:
        report = {"approved": False, "phase": args.command, "violations": [str(error)]}
    try:
        # Exclusive creation also protects against concurrent runs and input
        # path aliases; no existing state, plan, or report is overwritten.
        with report_path.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(report, output, indent=2, ensure_ascii=False)
            output.write("\n")
    except OSError:
        print("FAIL: Cannot create a fresh guard report. No input files were changed.", file=sys.stderr)
        return 1
    if report["approved"]:
        print(f"PASS: Recovery {args.command} guard; metadata report saved.")
        return 0
    print(f"FAIL: Recovery {args.command} guard rejected the selection or plan. Review the metadata report.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
