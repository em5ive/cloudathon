"""Read-only deployed HTTPS, redirect, CORS, and anonymous authorization checks."""
import argparse
import json
import os
from pathlib import Path
import ssl
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, HTTPSHandler, Request


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, method="GET", headers=None):
    opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    req = Request(url, method=method, headers=headers or {})
    try:
        with opener.open(req, timeout=25) as response:
            return response.status, response.headers, response.read(1024 * 1024)
    except HTTPError as error:
        return error.code, error.headers, error.read(1024 * 1024)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloudfront-url", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--s3-url")
    parser.add_argument("--output", type=Path, default=Path("reports/https.json"))
    args = parser.parse_args()
    cf = args.cloudfront_url.rstrip("/")
    api = args.api_url.rstrip("/")
    for url, suffix in [(cf, ".cloudfront.net"), (api, ".execute-api.us-west-2.amazonaws.com")]:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(suffix) or parsed.username or parsed.query or parsed.fragment:
            parser.error(f"Expected default AWS HTTPS domain ending {suffix}")
    results = []

    def check(name, operation):
        try:
            passed, evidence = operation()
            results.append({"test": name, "status": "PASS" if passed else "FAIL", "evidence": evidence})
        except Exception as error:
            results.append({"test": name, "status": "FAIL", "evidence": str(error)})

    def status(url, expected, headers=None):
        actual, _, _ = request(url, headers=headers)
        return actual in expected, f"HTTP {actual}; expected {sorted(expected)}; TLS certificate/hostname verified for HTTPS"

    check("CloudFront HTTPS", lambda: status(cf + "/", {200}))

    def redirect():
        code, headers, _ = request("http://" + cf.split("://", 1)[1] + "/")
        target = headers.get("Location", "")
        return code in {301, 302, 307, 308} and target == cf + "/", {"status": code, "location": target}
    check("CloudFront HTTP redirects to HTTPS", redirect)
    check("API HTTPS product listing", lambda: status(api + "/api/products", {200}))
    check("Orders reject anonymous users", lambda: status(api + "/api/orders", {401, 403}))

    def cors():
        code, headers, _ = request(api + "/api/orders", "OPTIONS", {"Origin": cf, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type,idempotency-key"})
        allowed = {value.strip().lower() for value in headers.get("Access-Control-Allow-Headers", "").split(",")}
        return code in {200, 204} and headers.get("Access-Control-Allow-Origin") == cf and {"authorization", "content-type", "idempotency-key"} <= allowed, {"status": code, "origin": headers.get("Access-Control-Allow-Origin"), "headers": sorted(allowed)}
    check("Exact CloudFront CORS and required request headers", cors)

    def denied_cors():
        _, headers, _ = request(api + "/api/orders", "OPTIONS", {"Origin": "https://untrusted.invalid", "Access-Control-Request-Method": "POST"})
        return headers.get("Access-Control-Allow-Origin") not in {"*", "https://untrusted.invalid"}, "Untrusted origin not allowed"
    check("CORS rejects unrelated origin", denied_cors)
    if args.s3_url:
        s3 = urlsplit(args.s3_url)
        if s3.scheme != "https" or not (s3.hostname or "").endswith(".s3.us-west-2.amazonaws.com"):
            parser.error("S3 check requires an HTTPS us-west-2 S3 object URL")
        check("S3 object denies direct public access", lambda: status(args.s3_url, {403}))
    token = os.environ.get("ANYCO_ACCESS_TOKEN")
    if token:
        def private():
            code, headers, _ = request(api + "/api/orders", headers={"Authorization": f"Bearer {token}"})
            return code == 200 and "no-store" in headers.get("Cache-Control", ""), {"status": code, "cache_control": headers.get("Cache-Control")}
        check("Authenticated orders are not cacheable", private)
    else:
        results.append({"test": "Authenticated orders are not cacheable", "status": "NOT TESTED", "evidence": "ANYCO_ACCESS_TOKEN not supplied through environment"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    for result in results:
        print(f"{result['status']}: {result['test']}")
    return int(any(result["status"] == "FAIL" for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
