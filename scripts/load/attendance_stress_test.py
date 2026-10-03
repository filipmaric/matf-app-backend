# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Load-test the Android attendance HTTP flow with dedicated test accounts.

This tool intentionally does not use the Android UI. It reproduces the HTTP
requests made by the app so that backend, database, Gunicorn, and RADIUS
behavior can be measured with a controlled number of clients.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import hmac
import html
import json
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests


@dataclass(frozen=True)
class Account:
    username: str
    password: str
    device_id: str
    device_name: str = "Attendance stress-test device"


@dataclass
class FlowResult:
    username: str
    scheduled_at: float
    started_at: float | None = None
    finished_at: float | None = None
    status: str = "not_started"
    login_status: int | None = None
    challenge_status: int | None = None
    submit_status: int | None = None
    error: str | None = None
    login_ms: float | None = None
    challenge_ms: float | None = None
    submit_ms: float | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return round((self.finished_at - self.started_at) * 1000, 1)


def load_accounts(path: Path, require_password: bool = True) -> list[Account]:
    """Read load identities without ever printing their passwords."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"username", "password", "device_id"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"accounts CSV is missing columns: {', '.join(sorted(missing))}")
        accounts = []
        seen = set()
        for row_number, row in enumerate(reader, start=2):
            account = Account(
                username=(row.get("username") or "").strip(),
                password=row.get("password") or "",
                device_id=(row.get("device_id") or "").strip(),
                device_name=(row.get("device_name") or "Attendance stress-test device").strip(),
            )
            if not account.username or not account.device_id or (require_password and not account.password):
                raise ValueError(f"accounts CSV row {row_number} has an empty required value")
            if account.username in seen:
                raise ValueError(f"duplicate username in accounts CSV: {account.username}")
            seen.add(account.username)
            accounts.append(account)
    return accounts


def load_usernames(path: Path) -> list[str]:
    """Read one test username per line for cleanup without exposing passwords."""
    usernames = []
    seen = set()
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        username = raw_line.strip()
        if not username or username.startswith("#"):
            continue
        if username in seen:
            raise ValueError(f"duplicate username in usernames file: {username}")
        seen.add(username)
        usernames.append(username)
    return usernames


def response_payload(response: requests.Response) -> dict[str, Any]:
    """Return a small JSON payload for diagnostics without copying large bodies."""
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def response_error(response: requests.Response, phase: str) -> str:
    payload = response_payload(response)
    code = payload.get("error_code") or payload.get("error")
    if code:
        return f"{phase}: HTTP {response.status_code}: {code}"
    return f"{phase}: HTTP {response.status_code}"


def csrf_token_from_html(document: str) -> str | None:
    """Extract the browser CSRF token rendered on the guest join page."""
    match = re.search(
        r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']',
        document or "",
        re.IGNORECASE,
    )
    return html.unescape(match.group(1)) if match else None


def endpoint(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def join_token_for_time(
    secret: str,
    event_kind: str,
    event_id: int,
    event_date: str,
    timestamp: float,
    ttl: int = 8,
) -> str:
    """Derive the QR token for a time bucket without exposing the secret."""
    bucket = int(timestamp // ttl)
    payload = f"{event_kind}:{event_id}:{event_date}:{bucket}:join".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()[:48]


def run_flow(
    account: Account,
    args: argparse.Namespace,
    event_id: int,
    event_date: str,
    join_token: str,
    scheduled_at: float,
    stop_event: threading.Event,
    event_kind: str = "weekly",
) -> FlowResult:
    result = FlowResult(username=account.username, scheduled_at=scheduled_at)
    delay = scheduled_at - time.monotonic()
    if delay > 0:
        time.sleep(delay)
    if stop_event.is_set():
        result.status = "skipped_after_abort"
        return result

    result.started_at = time.monotonic()
    session = requests.Session()
    base = args.base_url
    try:
        effective_join_token = join_token
        if getattr(args, "rotate_join_token", False):
            effective_join_token = join_token_for_time(
                args.attendance_secret,
                event_kind,
                event_id,
                event_date,
                time.time() + getattr(args, "clock_offset_seconds", 0.0),
                args.join_token_ttl,
            )
        headers = {}
        if getattr(args, "registration_mode", "authenticated") == "guest":
            phase_started = time.monotonic()
            bootstrap = session.get(
                endpoint(base, f"/attendance/{event_kind}/{event_id}/{event_date}/join/{effective_join_token}"),
                allow_redirects=True,
                timeout=args.timeout,
            )
            result.login_ms = round((time.monotonic() - phase_started) * 1000, 1)
            result.login_status = bootstrap.status_code
            if not bootstrap.ok:
                result.status = "guest_bootstrap_failed"
                result.error = response_error(bootstrap, "guest bootstrap")
                return result
            csrf_token = csrf_token_from_html(bootstrap.text)
            if not csrf_token:
                result.status = "guest_bootstrap_failed"
                result.error = "guest bootstrap: response did not contain CSRF token"
                return result
            headers["X-CSRFToken"] = csrf_token
        else:
            phase_started = time.monotonic()
            login = session.post(
                endpoint(base, "/mobile/login"),
                json={
                    "username": account.username,
                    "password": account.password,
                    "device_id": account.device_id,
                    "device_name": account.device_name,
                },
                timeout=args.timeout,
            )
            result.login_ms = round((time.monotonic() - phase_started) * 1000, 1)
            result.login_status = login.status_code
            if not login.ok:
                result.status = "login_failed"
                result.error = response_error(login, "login")
                return result
            token = response_payload(login).get("token")
            if not token:
                result.status = "login_failed"
                result.error = "login: response did not contain token"
                return result
            headers = {"Authorization": f"Bearer {token}"}

        target = f"/attendance/{event_kind}/{event_id}/{event_date}/challenge"
        phase_started = time.monotonic()
        challenge = session.get(
            endpoint(base, target),
            params={} if getattr(args, "registration_mode", "authenticated") == "guest" else {"join_token": effective_join_token},
            headers=headers,
            timeout=args.timeout,
        )
        result.challenge_ms = round((time.monotonic() - phase_started) * 1000, 1)
        result.challenge_status = challenge.status_code
        if not challenge.ok:
            result.status = "challenge_failed"
            result.error = response_error(challenge, "challenge")
            return result
        challenge_payload = response_payload(challenge)
        challenge_data = challenge_payload.get("challenge") or {}
        attempt_token = challenge_payload.get("attendance_attempt_token")
        selected_code = challenge_data.get("current_code")
        if not attempt_token or selected_code is None:
            result.status = "challenge_failed"
            result.error = "challenge: response did not contain attempt token and current code"
            return result

        body: dict[str, Any] = {
            "selected_code": selected_code,
        }
        if getattr(args, "registration_mode", "authenticated") == "guest":
            body["username"] = account.username
        else:
            body["attendance_attempt_token"] = attempt_token
        if args.latitude is not None and args.longitude is not None:
            body["latitude"] = args.latitude
            body["longitude"] = args.longitude
        phase_started = time.monotonic()
        submit = session.post(
            endpoint(base, f"/attendance/{event_kind}/{event_id}/{event_date}/join"),
            json=body,
            headers=headers,
            timeout=args.timeout,
        )
        result.submit_ms = round((time.monotonic() - phase_started) * 1000, 1)
        result.submit_status = submit.status_code
        if not submit.ok:
            result.status = "submit_failed"
            result.error = response_error(submit, "submit")
            return result
        result.status = "success"
        return result
    except requests.RequestException as exc:
        result.status = "request_failed"
        result.error = f"request: {type(exc).__name__}"
        return result
    finally:
        result.finished_at = time.monotonic()
        session.close()


def run_stress_test(args: argparse.Namespace, accounts: list[Account]) -> dict[str, Any]:
    selected = accounts[: args.clients]
    stop_event = threading.Event()
    started = time.monotonic()
    interval = args.duration / max(len(selected), 1)
    futures = {}
    results: list[FlowResult] = []

    with ThreadPoolExecutor(max_workers=min(args.max_workers, len(selected))) as executor:
        for index, account in enumerate(selected):
            scheduled_at = started + index * interval
            future = executor.submit(
                run_flow,
                account,
                args,
                args.event_id,
                args.event_date,
                args.join_token,
                scheduled_at,
                stop_event,
                args.event_kind,
            )
            futures[future] = account.username

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            completed = len(results)
            failed = sum(item.status not in {"success", "skipped_after_abort"} for item in results)
            if completed >= args.abort_after and failed / completed > args.max_error_rate:
                stop_event.set()

    elapsed = time.monotonic() - started
    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
    durations = sorted(
        result.duration_ms for result in results if result.duration_ms is not None
    )
    login_latencies = sorted(result.login_ms for result in results if result.login_ms is not None)
    challenge_latencies = sorted(result.challenge_ms for result in results if result.challenge_ms is not None)
    submit_latencies = sorted(result.submit_ms for result in results if result.submit_ms is not None)
    return {
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "requested_clients": args.clients,
        "scheduled_clients": len(selected),
        "duration_seconds": args.duration,
        "event": {"kind": args.event_kind, "event_id": args.event_id, "event_date": args.event_date},
        "status_counts": status_counts,
        "latency_ms": percentile_report(durations),
        "phase_latency_ms": {
            "login": percentile_report(login_latencies),
            "challenge": percentile_report(challenge_latencies),
            "submit": percentile_report(submit_latencies),
        },
        "results": [asdict(result) | {"duration_ms": result.duration_ms} for result in results],
    }


def percentile_report(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "p50": None, "p95": None, "p99": None, "max": None}

    def percentile(percent: float) -> float:
        index = min(len(values) - 1, round((len(values) - 1) * percent))
        return values[index]

    return {
        "min": values[0],
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": values[-1],
    }


def cleanup_attendance(database: Path, event_id: int, event_date: str, usernames: list[str]) -> int:
    """Delete only attendance rows for the selected test event and accounts."""
    if not usernames:
        return 0
    placeholders = ",".join("?" for _ in usernames)
    with sqlite3.connect(database) as connection:
        cursor = connection.execute(
            f"""
            DELETE FROM attendance_records
            WHERE event_kind = 'weekly'
              AND event_id = ?
              AND event_date = ?
              AND username IN ({placeholders})
            """,
            (event_id, event_date, *usernames),
        )
        guest_devices_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'attendance_guest_devices'"
        ).fetchone()
        if guest_devices_table:
            connection.execute(
                f"""
                DELETE FROM attendance_guest_devices
                WHERE event_kind = 'weekly'
                  AND event_id = ?
                  AND event_date = ?
                  AND username IN ({placeholders})
                """,
                (event_id, event_date, *usernames),
            )
        return cursor.rowcount


def write_cleanup_sql(path: Path, event_id: int, event_date: str, usernames: list[str]) -> None:
    quoted = ", ".join("'" + username.replace("'", "''") + "'" for username in usernames)
    path.write_text(
        "BEGIN;\n"
        "DELETE FROM attendance_records\n"
        f"WHERE event_kind = 'weekly' AND event_id = {event_id}\n"
        f"  AND event_date = '{event_date}' AND username IN ({quoted});\n"
        "DELETE FROM attendance_guest_devices\n"
        f"WHERE event_kind = 'weekly' AND event_id = {event_id}\n"
        f"  AND event_date = '{event_date}' AND username IN ({quoted});\n"
        "COMMIT;\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cleanup", action="store_true", help="delete test attendance rows instead of running a load")
    parser.add_argument("--confirm-cleanup", action="store_true", help="required with --cleanup")
    parser.add_argument("--database", type=Path, help="SQLite database used with --cleanup")
    parser.add_argument("--base-url", help="server base URL, including the application root")
    parser.add_argument("--accounts-file", type=Path, help="private CSV with test identities")
    parser.add_argument("--usernames-file", type=Path, help="one username per line, for cleanup only")
    parser.add_argument("--event-id", type=int, required=True, help="weekly session ID from the test event")
    parser.add_argument(
        "--event-kind",
        choices=("weekly", "reservation"),
        default="weekly",
        help="attendance event kind",
    )
    parser.add_argument("--event-date", required=True, help="attendance date in YYYY-MM-DD format")
    parser.add_argument("--join-token", help="join_token from the QR code")
    parser.add_argument(
        "--rotate-join-token",
        action="store_true",
        help="derive the current QR token for each client from ATTENDANCE_SECRET",
    )
    parser.add_argument(
        "--join-token-ttl",
        type=int,
        default=8,
        help="QR token bucket length in seconds when --rotate-join-token is used",
    )
    parser.add_argument(
        "--clock-offset-seconds",
        type=float,
        default=0.0,
        help="add this offset to the load generator clock when deriving QR tokens",
    )
    parser.add_argument(
        "--registration-mode",
        choices=("authenticated", "guest"),
        default="authenticated",
        help="attendance flow to simulate (guest is username-only registration)",
    )
    parser.add_argument("--clients", type=int, default=300)
    parser.add_argument("--duration", type=float, default=60.0, help="seconds over which flows are started")
    parser.add_argument("--max-workers", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--max-error-rate", type=float, default=0.10)
    parser.add_argument("--abort-after", type=int, default=20)
    parser.add_argument("--latitude", type=float)
    parser.add_argument("--longitude", type=float)
    parser.add_argument("--report", type=Path, help="write a JSON report")
    parser.add_argument("--cleanup-sql", type=Path, help="write a reviewable cleanup SQL file")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--environment", choices=("local", "staging", "production"), default="local")
    parser.add_argument("--allow-remote", action="store_true", help="allow traffic to a non-local host")
    parser.add_argument("--allow-production", action="store_true", help="required for production runs")
    return parser


def validate_args(args: argparse.Namespace, accounts: list[Account], usernames: list[str] | None = None) -> None:
    if args.cleanup:
        if not args.confirm_cleanup:
            raise ValueError("--cleanup requires --confirm-cleanup")
        if args.database is None:
            raise ValueError("--cleanup requires --database")
        if not usernames and not accounts:
            raise ValueError("--cleanup requires --usernames-file or --accounts-file")
        return
    if not args.accounts_file:
        raise ValueError("--accounts-file is required for a load run")
    if args.clients < 1 or args.duration <= 0 or args.max_workers < 1:
        raise ValueError("clients, duration, and max-workers must be positive")
    if not 0 <= args.max_error_rate <= 1:
        raise ValueError("max-error-rate must be between 0 and 1")
    if len(accounts) < args.clients:
        raise ValueError(f"accounts CSV contains {len(accounts)} accounts, but {args.clients} are required")
    if (args.latitude is None) != (args.longitude is None):
        raise ValueError("latitude and longitude must be supplied together")
    if not args.base_url:
        raise ValueError("--base-url is required for a load run")
    if not args.join_token and not args.rotate_join_token:
        raise ValueError("--join-token is required for a load run")
    if args.rotate_join_token:
        args.attendance_secret = os.getenv("ATTENDANCE_SECRET", "")
        if not args.attendance_secret:
            raise ValueError("--rotate-join-token requires ATTENDANCE_SECRET")
        if args.join_token_ttl < 1:
            raise ValueError("--join-token-ttl must be positive")
    host = urlparse(args.base_url).hostname or ""
    if host not in {"localhost", "127.0.0.1", "::1"} and not (args.allow_remote or args.allow_production):
        raise ValueError("remote load runs require --allow-remote")
    if args.allow_production and args.environment != "production":
        raise ValueError("--allow-production requires --environment production")
    if args.environment == "production" and not args.allow_production:
        raise ValueError("production load runs require --allow-production")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    accounts = (
        load_accounts(
            args.accounts_file,
            require_password=args.registration_mode != "guest",
        )
        if args.accounts_file
        else []
    )
    usernames = load_usernames(args.usernames_file) if args.usernames_file else []
    validate_args(args, accounts, usernames)

    if args.cleanup:
        selected_usernames = usernames or [a.username for a in accounts]
        deleted = cleanup_attendance(args.database, args.event_id, args.event_date, selected_usernames)
        print(json.dumps({"deleted_attendance_records": deleted}, ensure_ascii=False))
        return 0

    selected = accounts[: args.clients]

    if args.cleanup_sql:
        write_cleanup_sql(args.cleanup_sql, args.event_id, args.event_date, [a.username for a in selected])
    if args.dry_run:
        print(json.dumps({"clients": len(selected), "duration_seconds": args.duration, "interval_seconds": args.duration / len(selected)}, ensure_ascii=False))
        return 0

    report = run_stress_test(args, accounts)
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
