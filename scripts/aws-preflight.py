"""Read-only AWS capability evidence. Never invokes models or reads secret values."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

REGION = "us-west-2"
PROXY_SUPPORT_SOURCE = "https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Concepts.Aurora_Fea_Regions_DB-eng.Feature.RDS_Proxy.html"
CONVERSE_SUPPORT_SOURCE = "https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference-supported-models-features.html"


def error_category(message):
    if any(term in message.lower() for term in ("nocredentials", "unable to locate credentials", "expiredtoken", "invalidclienttokenid", "sso session", "token has expired", "your session has expired", "reauthenticate using aws login")):
        return "AUTHENTICATION_UNAVAILABLE"
    if any(term in message for term in ("AccessDenied", "UnauthorizedOperation", "not authorized to perform")):
        return "READ_PERMISSION_DENIED"
    if any(term in message.lower() for term in ("could not connect", "timed out", "ssl validation", "connection", "endpoint url", "socket")):
        return "CONNECTIVITY"
    return "CLI_OR_SERVICE_ERROR"


def aws(*arguments, region=REGION):
    command = ["aws", *arguments, "--region", region, "--output", "json", "--no-cli-pager", "--cli-connect-timeout", "5", "--cli-read-timeout", "15"]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=45)
    except FileNotFoundError:
        return {"status": "BLOCKED", "category": "CLI_MISSING", "command": command, "error": "AWS CLI executable was not found"}
    except subprocess.TimeoutExpired:
        return {"status": "BLOCKED", "category": "CONNECTIVITY", "command": command, "error": "AWS read-only command exceeded 45 seconds"}
    if completed.returncode:
        message = completed.stderr.strip()
        return {"status": "BLOCKED", "category": error_category(message), "command": command, "error": message}
    try:
        return {"status": "PASS", "command": command, "data": json.loads(completed.stdout)}
    except json.JSONDecodeError:
        return {"status": "BLOCKED", "category": "UNEXPECTED_OUTPUT", "command": command, "error": "Expected JSON output from the AWS CLI"}


def result(status, evidence, **extra):
    return {"status": status, "evidence": evidence, **extra}


def normalize_service_quota_read(command, observed):
    # Visibility into Service Quotas is separate from quota exhaustion. Apply
    # the user's warning rule only to this read action, never other denials.
    if command[:2] == ["service-quotas", "list-service-quotas"] and observed.get("status") == "BLOCKED" and (
        observed.get("category") == "READ_PERMISSION_DENIED" or error_category(observed.get("error", "")) == "READ_PERMISSION_DENIED"
    ):
        return {**observed, "status": "UNVERIFIED", "severity": "warning", "evidence": "ListServiceQuotas visibility was denied. Quota capacity is unverified, not exhausted; this does not block an authenticated Terraform plan.", "required_follow_up": "Have the competition administrator verify applicable quota and current usage before applying; retain their evidence. No IAM change or bypass is attempted."}
    return observed


def proxy_compatibility(version):
    # Published Oregon table checked Nov 7, 2026. Recheck it before applying.
    # This scope is feature support, not account permission or orderability.
    if not version:
        return result("NOT TESTED", "No exact Aurora PostgreSQL version selected", source=PROXY_SUPPORT_SOURCE)
    parts = tuple(int(part) for part in version.split("."))
    supported = (parts[0] == 16 and parts[1] >= 1) or (parts[0] == 17 and parts[1] >= 4)
    return result("PASS" if supported else "FAIL", f"Published Oregon Proxy compatibility for PostgreSQL {version}; account provisioning still unverified", source=PROXY_SUPPORT_SOURCE, scope="DOCUMENTED_FEATURE_SUPPORT", table_checked="2026-11-07")


def read_calls(engine_version=None, model_id=None, project="uh-retail-poc"):
    calls = {
        "availability_zones": ["ec2", "describe-availability-zones", "--filters", "Name=state,Values=available", "Name=opt-in-status,Values=opt-in-not-required,opted-in", "--query", "AvailabilityZones[].ZoneName"],
        "aurora_versions": ["rds", "describe-db-engine-versions", "--engine", "aurora-postgresql", "--query", "DBEngineVersions[].{Version:EngineVersion,Family:DBParameterGroupFamily,Status:Status,Serverless:ServerlessV2FeaturesSupport}"],
        "serverless_classes": ["rds", "describe-orderable-db-instance-options", "--engine", "aurora-postgresql", "--db-instance-class", "db.serverless", "--query", "OrderableDBInstanceOptions[].{Version:EngineVersion,Class:DBInstanceClass,AZs:AvailabilityZones[].Name}"],
        "secretsmanager_endpoint": ["ec2", "describe-vpc-endpoint-services", "--service-names", f"com.amazonaws.{REGION}.secretsmanager", "--query", "ServiceDetails[].{Name:ServiceName,Types:ServiceType[].ServiceType,AZs:AvailabilityZones,PrivateDNS:PrivateDnsName}"],
        "bedrock_runtime_endpoint": ["ec2", "describe-vpc-endpoint-services", "--service-names", f"com.amazonaws.{REGION}.bedrock-runtime", "--query", "ServiceDetails[].{Name:ServiceName,Types:ServiceType[].ServiceType,AZs:AvailabilityZones,PrivateDNS:PrivateDnsName}"],
        "bedrock_catalog": ["bedrock", "list-foundation-models", "--by-output-modality", "TEXT"],
        "bedrock_profiles": ["bedrock", "list-inference-profiles"],
        "db_clusters": ["rds", "describe-db-clusters", "--query", "DBClusters[].{Name:DBClusterIdentifier,Engine:Engine,Version:EngineVersion,Status:Status}"],
        "db_instances": ["rds", "describe-db-instances", "--query", "DBInstances[].{Name:DBInstanceIdentifier,Class:DBInstanceClass,Engine:Engine,Version:EngineVersion,AZ:AvailabilityZone}"],
        "db_proxies": ["rds", "describe-db-proxies", "--query", "DBProxies[].{Name:DBProxyName,Engine:EngineFamily,Status:Status}"],
        "db_subnet_groups": ["rds", "describe-db-subnet-groups", "--query", "DBSubnetGroups[].DBSubnetGroupName"],
        "db_parameter_groups": ["rds", "describe-db-cluster-parameter-groups", "--query", "DBClusterParameterGroups[].DBClusterParameterGroupName"],
        "vpcs": ["ec2", "describe-vpcs", "--query", "Vpcs[].{Id:VpcId,CIDR:CidrBlock,Tags:Tags}"],
        "functions": ["lambda", "list-functions", "--query", "Functions[].FunctionName"],
        "lambda_account_limits": ["lambda", "get-account-settings", "--query", "{Concurrent:AccountLimit.ConcurrentExecutions,Unreserved:AccountLimit.UnreservedConcurrentExecutions}"],
        "apis": ["apigatewayv2", "get-apis", "--query", "Items[].{Name:Name,Id:ApiId}"],
        "distributions": ["cloudfront", "list-distributions", "--query", "DistributionList.Items[].{Id:Id,Domain:DomainName,Comment:Comment}"],
        "origin_access_controls": ["cloudfront", "list-origin-access-controls", "--query", "OriginAccessControlList.Items[].Name"],
        "buckets": ["s3api", "list-buckets", "--query", "Buckets[].Name"],
        "user_pools": ["cognito-idp", "list-user-pools", "--max-results", "60", "--query", "UserPools[].Name"],
        "secret_names": ["secretsmanager", "list-secrets", "--include-planned-deletion", "--query", "SecretList[].Name"],
        "role_names": ["iam", "list-roles", "--query", "Roles[].RoleName"],
        "log_group_names": ["logs", "describe-log-groups", "--log-group-name-prefix", f"/aws/lambda/{project}", "--query", "logGroups[].logGroupName"],
    }
    if engine_version:
        calls["serverless_classes"].extend(["--engine-version", engine_version])
    if model_id:
        calls["bedrock_model_availability"] = ["bedrock", "get-foundation-model-availability", "--model-id", model_id]
        calls["bedrock_model_details"] = ["bedrock", "get-foundation-model", "--model-identifier", model_id]
    for code in ("rds", "lambda", "vpc", "ec2", "apigateway", "bedrock", "cognito-idp", "cloudfront"):
        calls[f"quota_{code}"] = ["service-quotas", "list-service-quotas", "--service-code", code]
    return calls


def desired_reservations(args):
    desired = {"products": args.products_concurrency, "orders": args.orders_concurrency, "support": args.support_concurrency}
    if not args.runtime_only:
        desired["bootstrap"] = 1
    return desired


def add_reservation_reads(report, args, invoke):
    checks = report["checks"]
    inventory = checks["functions"]
    if inventory["status"] != "PASS":
        return
    existing_names = set(inventory.get("data") or [])
    for service in desired_reservations(args):
        function_name = f"{args.project_name}-{service}"
        if function_name in existing_names:
            # A same-name function may still belong to another deployment;
            # naming/ownership review remains separate from quota arithmetic.
            key = f"existing_concurrency_{service}"
            checks[key] = invoke("lambda", "get-function-concurrency", "--function-name", function_name, region=args.region)
            print(f"{checks[key]['status']}: {key}")


def reservation_capacity(checks, args):
    limits = checks["lambda_account_limits"]
    if limits["status"] != "PASS":
        return result("BLOCKED", "Lambda account concurrency limits could not be read")
    inventory = checks["functions"]
    if inventory["status"] != "PASS":
        return result("NOT TESTED", "Existing function inventory is unavailable; cannot calculate incremental reservations without double-counting")
    existing_names = set(inventory.get("data") or [])
    desired = desired_reservations(args)
    observed = {}
    for service in desired:
        name = f"{args.project_name}-{service}"
        if name not in existing_names:
            observed[service] = 0
            continue
        current = checks.get(f"existing_concurrency_{service}", {})
        if current.get("status") != "PASS":
            return result("NOT TESTED", "Existing same-name function reservation could not be read; manual quota/ownership review is required", function_name=name)
        reservation = (current.get("data") or {}).get("ReservedConcurrentExecutions", 0)
        if type(reservation) is not int or reservation < 0:
            return result("NOT TESTED", "Unexpected existing reservation value; manual quota review is required", function_name=name)
        observed[service] = reservation
    additional = sum(max(desired[service] - observed[service], 0) for service in desired)
    available = (limits.get("data") or {}).get("Unreserved")
    if type(available) is not int or available < 0:
        return result("NOT TESTED", "Unreserved account concurrency was not returned as a valid integer")
    return result("PASS" if available - additional >= 100 else "FAIL", "Only positive reservation increases consume current unreserved headroom; no credit is taken for pending reductions/removal. Ownership review and apply-time quotas remain required", desired_reservations=desired, observed_same_name_reservations=observed, required_additional_reservations=additional, unreserved_before=available, unreserved_after_increases=available - additional)


def add_capability_checks(report, args):
    checks = report["checks"]
    zone_result = checks["availability_zones"]
    zones = sorted(zone_result.get("data") or [])[:2] if zone_result["status"] == "PASS" else []
    checks["two_az_availability"] = result("PASS" if len(zones) == 2 else "BLOCKED", "First two sorted available AZs match the Terraform selection strategy", selected_azs=zones)
    orderable = checks["serverless_classes"]
    if not args.engine_version:
        checks["selected_serverless_version"] = result("NOT TESTED", "Select an exact version from authenticated engine/orderable results and rerun with --engine-version")
    elif orderable["status"] != "PASS":
        checks["selected_serverless_version"] = result("BLOCKED", "Orderable instance options could not be read; no support conclusion")
    else:
        matching = [item for item in orderable["data"] or [] if item["Version"] == args.engine_version and item["Class"] == "db.serverless"]
        covered = set().union(*(set(item.get("AZs") or []) for item in matching)) if matching else set()
        checks["selected_serverless_version"] = result("PASS" if len(zones) == 2 and set(zones) <= covered else "FAIL", "Exact engine/class must be orderable in both selected AZs", engine_version=args.engine_version, selected_azs=zones, orderable_azs=sorted(covered))
    for key in ("secretsmanager", "bedrock_runtime"):
        source = checks[f"{key}_endpoint"]
        if source["status"] != "PASS":
            checks[f"{key}_two_az_endpoint"] = result("BLOCKED", "Service offerings could not be read; no compatibility conclusion")
        else:
            offerings = source["data"] or []
            allowed = any("Interface" in item.get("Types", []) and item.get("PrivateDNS") and set(zones) <= set(item.get("AZs") or []) for item in offerings)
            checks[f"{key}_two_az_endpoint"] = result("PASS" if len(zones) == 2 and allowed else "FAIL", "Interface service must advertise private DNS and both selected AZs", selected_azs=zones)
    checks["lambda_reserved_capacity"] = reservation_capacity(checks, args)
    if args.model_id:
        availability = checks["bedrock_model_availability"]
        data = availability.get("data", {})
        accessible = data.get("authorizationStatus") == "AUTHORIZED" and data.get("entitlementAvailability") == "AVAILABLE" and data.get("regionAvailability") == "AVAILABLE" and data.get("agreementAvailability", {}).get("status") == "AVAILABLE"
        checks["selected_model_access_metadata"] = result("PASS" if availability["status"] == "PASS" and accessible else "BLOCKED", "Availability/authorization metadata only; runtime invocation and Converse support are not established")
        details = checks["bedrock_model_details"]
        modes = details.get("data", {}).get("modelDetails", {}).get("inferenceTypesSupported", [])
        checks["selected_model_inference_mode"] = result("PASS" if "ON_DEMAND" in modes else "BLOCKED", "Current Terraform accepts regional foundation-model IDs; provisioned throughput or inference profiles require a reviewed change", inference_types=modes)
    checks["converse_runtime_inference"] = result("NOT TESTED", "No paid invocation attempted. Confirm model Converse compatibility, system messages/JSON support, permission and entitlement; a bounded invocation needs approval", source=CONVERSE_SUPPORT_SOURCE)
    inventories = ("db_clusters", "db_instances", "db_proxies", "db_subnet_groups", "db_parameter_groups", "functions", "apis", "distributions", "origin_access_controls", "buckets", "user_pools", "secret_names", "role_names", "log_group_names")
    candidates = []
    for key in inventories:
        if checks[key]["status"] == "PASS":
            for item in checks[key].get("data") or []:
                name = item if isinstance(item, str) else item.get("Name", item.get("Comment", ""))
                if args.project_name in name:
                    candidates.append({"inventory": key, "name": name})
    unreadable = [key for key in inventories if checks[key]["status"] != "PASS"]
    checks["naming_conflict_review"] = result("BLOCKED" if unreadable else "FAIL" if candidates else "PASS", "Prefix matches need ownership review; no imports, changes or name reservations performed. A clear inventory cannot reserve globally unique names", possible_conflicts=candidates, incomplete_inventories=unreadable)


def collect(args, configured_region, invoke=aws):
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "target_region": args.region, "configured_region": configured_region, "expected_account_id": args.expected_account_id, "checks": {}}
    checks = report["checks"]
    checks["explicit_region"] = result("PASS", f"Every AWS query explicitly targets {args.region}")
    checks["configured_region"] = result("PASS" if configured_region == args.region else "NOT TESTED", "No matching default region configured; explicit --region remains authoritative" if configured_region != args.region else "Default and explicit target regions match")
    checks["identity"] = invoke("sts", "get-caller-identity", region=args.region)
    checks["proxy_documented_compatibility"] = proxy_compatibility(args.engine_version)
    calls = read_calls(args.engine_version, args.model_id, args.project_name)
    if checks["identity"]["status"] != "PASS":
        reason = "Authentication unavailable; service queries were not attempted. This is not evidence that any service permission was denied."
        checks["account_verification"] = result("BLOCKED", reason)
        for name in calls:
            checks[name] = result("BLOCKED", reason, category="AUTHENTICATION_PREREQUISITE", attempted=False)
    else:
        account = checks["identity"]["data"].get("Account")
        checks["account_verification"] = result("NOT TESTED" if not args.expected_account_id else "PASS" if account == args.expected_account_id else "FAIL", "Compare STS identity with independently verified competition account ID", observed_account_id=account)
        if args.expected_account_id and account != args.expected_account_id:
            for name in calls:
                checks[name] = result("BLOCKED", "Wrong AWS account; no service inventory performed", attempted=False)
        else:
            for name, call in calls.items():
                checks[name] = normalize_service_quota_read(call, invoke(*call, region=args.region))
                print(f"{checks[name]['status']}: {name}")
            add_reservation_reads(report, args, invoke)
            add_capability_checks(report, args)
    checks["quota_cloudfront"].update(scope="GLOBAL_SERVICE_QUERY_AT_TARGET_REGION", requested_region=args.region, limitation="CloudFront is global. This Service Quotas read targets Oregon to preserve the requested query scope; global quotas may require separate review in us-east-1. Success here does not establish global quota headroom.")
    checks["provisioning_permissions"] = result("NOT TESTED", "Read permissions and STS identity do not prove Create/PassRole permissions, policy boundaries, SCPs or remaining quotas. No resource mutation was attempted.")
    required = ["identity", "account_verification", "aurora_versions", "two_az_availability", "selected_serverless_version", "proxy_documented_compatibility", "lambda_reserved_capacity", "naming_conflict_review"]
    quota_checks = [f"quota_{code}" for code in ("rds", "lambda", "vpc", "ec2", "apigateway", "cognito-idp", "cloudfront")]
    if not args.runtime_only:
        required.append("secretsmanager_two_az_endpoint")
    if args.model_id:
        required.extend(["bedrock_runtime_two_az_endpoint", "selected_model_access_metadata", "selected_model_inference_mode"])
        quota_checks.append("quota_bedrock")
    report["warnings"] = [{"check": key, "severity": "warning", "message": check["evidence"], "required_follow_up": check["required_follow_up"]} for key, check in checks.items() if check.get("status") == "UNVERIFIED" and check.get("severity") == "warning"]
    report["ready_for_authenticated_terraform_plan"] = all(checks.get(key, {}).get("status") == "PASS" for key in required) and all(checks.get(key, {}).get("status") in {"PASS", "UNVERIFIED"} for key in quota_checks)
    report["ready_for_deployment"] = False
    report["limits"] = "This report supports plan review only. It does not establish deployed functionality, runtime inference, actual quotas at apply time, resource-create permissions, or approval to deploy. No secret values were read."
    return report


def reservation_argument(value):
    try:
        count = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Reserved concurrency must be a whole number between 1 and 20") from None
    if not 1 <= count <= 20:
        raise argparse.ArgumentTypeError("Reserved concurrency must be a whole number between 1 and 20")
    return count


def parser():
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--region", choices=[REGION], default=REGION)
    argument_parser.add_argument("--expected-account-id", help="Independently verified competition account ID; never a credential")
    argument_parser.add_argument("--engine-version")
    argument_parser.add_argument("--model-id", help="Optional regional foundation-model ID; inference is never invoked")
    argument_parser.add_argument("--project-name", default="uh-retail-poc")
    argument_parser.add_argument("--runtime-only", action="store_true", help="Evaluate post-bootstrap reservations/endpoints")
    argument_parser.add_argument("--products-concurrency", type=reservation_argument, default=3, help="Match Terraform products reservation (default 3)")
    argument_parser.add_argument("--orders-concurrency", type=reservation_argument, default=3, help="Match Terraform orders reservation (default 3)")
    argument_parser.add_argument("--support-concurrency", type=reservation_argument, default=2, help="Match Terraform support reservation (default 2)")
    argument_parser.add_argument("--output", type=Path, default=Path("reports/aws-preflight.json"))
    return argument_parser


def main():
    argument_parser = parser()
    args = argument_parser.parse_args()
    if args.expected_account_id and not re.fullmatch(r"\d{12}", args.expected_account_id):
        argument_parser.error("--expected-account-id must be a verified 12-digit account ID")
    if args.engine_version and not re.fullmatch(r"(?:16|17)\.\d+(?:\.\d+)?", args.engine_version):
        argument_parser.error("--engine-version must be an exact Aurora PostgreSQL 16.x or 17.x version")
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,23}", args.project_name):
        argument_parser.error("--project-name must match Terraform's 3–24 character namespace")
    try:
        configured = subprocess.run(["aws", "configure", "get", "region"], capture_output=True, text=True, check=False, timeout=15).stdout.strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        configured = None
    report = collect(args, configured)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    identity = report["checks"]["identity"]
    if identity["status"] != "PASS":
        print(identity.get("error", identity.get("evidence")), file=sys.stderr)
    if report["warnings"]:
        print(f"WARNING: {len(report['warnings'])} Service Quotas visibility checks are UNVERIFIED; confirm quotas/usage before apply. These warnings do not block Terraform planning.", file=sys.stderr)
    print(f"Evidence saved to {args.output}. Ready for authenticated Terraform plan: {report['ready_for_authenticated_terraform_plan']}")
    return 0 if report["ready_for_authenticated_terraform_plan"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
