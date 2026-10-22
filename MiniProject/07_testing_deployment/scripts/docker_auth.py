"""Production auth factory + real HTTPS proxy on isolated state/network; no false attestation."""

import json
import subprocess
from pathlib import Path
from uuid import uuid4

MODULE = Path(__file__).resolve().parents[1]

# HTTPS uses localhost SNI/Host while connecting to the web container on the internal net.
# Only this disposable local CA is unverified; public HTTPS acceptance stays false.
PROBE = """
import http.client, json, socket, ssl
def request(path):
    c = http.client.HTTPSConnection('localhost',
        context=ssl._create_unverified_context(), timeout=10)
    c._create_connection = lambda *args: socket.create_connection(('web',443), 10)
    c.request('GET', path)
    r = c.getresponse()
    result = (r.status, dict(r.getheaders()), r.read().decode())
    c.close()
    return result
status, _, body = request('/health')
h = json.loads(body)
assert status == 200 and h['authentication_required'] and not h['single_user']
assert h['schema_revision'] == '0002' and h['full_pair_preflight']
assert h['mode'] == 'custom' and h['integration_profile'] == 'live'
assert not h['live_provider_verified']
assert all(v == 'available' for v in h['capabilities'].values())
status, headers, body = request('/api/videos')
assert status == 401 and 'authentication_required' in body and '<html' not in body
assert headers.get('Cache-Control') == 'no-store'
status, headers, body = request('/api/auth/challenge')
assert status == 200 and all(k in json.loads(body) for k in ('nonce','csrf_token','client_id'))
cookie = headers.get('Set-Cookie','')
assert all(value in cookie for value in ('__Host-', 'Secure', 'HttpOnly', 'SameSite=lax'))
status, _, body = request('/api/unknown')
assert status == 401 and '<html' not in body
status, _, body = request('/api')
assert status == 404 and '<html' not in body
status, _, body = request('/admin')
assert status == 200 and '<div id="root">' in body
print(json.dumps(dict(health=h, tls_proxy_verified=True,
    secure_login_cookie_verified=True, unauthorized_api_verified=True)))
"""


def main():
    if not (MODULE.parent / "candidate.json").is_file():
        raise SystemExit("Run only in the pinned candidate with its committed lock")
    project = f"yk07-auth-{uuid4().hex[:10]}"
    output = MODULE / "runtime" / project
    output.mkdir(parents=True)
    compose = [
        "docker",
        "compose",
        "-p",
        project,
        "-f",
        str(MODULE / "compose.yaml"),
        "-f",
        str(MODULE / "compose.auth-drill.yaml"),
    ]
    report = dict(
        passed=False,
        real_google_verified=False,
        public_https_verified=False,
        release_attestation_created=False,
        candidate=json.loads((MODULE.parent / "candidate.json").read_text(encoding="utf-8")),
    )

    def run(*args, required=True):
        result = subprocess.run(
            [*compose, *args],
            capture_output=True,
            timeout=200,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        with (output / "docker.log").open("a", encoding="utf-8") as log:
            log.write(f"COMMAND {args[0]}\n{result.stdout}\n{result.stderr}\n")
        if required and result.returncode:
            raise RuntimeError(f"Docker {args[0]} failed")
        return result

    try:
        run("up", "-d", "--no-build", "--wait", "api", "worker", "web")
        result = run("exec", "-T", "worker", "python", "-c", PROBE)
        report.update(json.loads(result.stdout), passed=True)
        report["images"] = json.loads(run("images", "--format", "json").stdout)
    except Exception as exc:
        report["error_type"] = type(exc).__name__
    finally:
        try:
            run("logs", "--no-color", required=False)
        finally:
            report["cleanup_passed"] = (
                run("down", "--volumes", "--remove-orphans", required=False).returncode == 0
            )
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output / "report.json")
    return int(not report["passed"] or not report["cleanup_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
