# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Shared helpers for the manual teacher and student RADIUS checks."""

from __future__ import annotations

import getpass
import os
import socket
import sys
from pathlib import Path

import pyrad.packet
from pyrad.client import Client
from pyrad.dictionary import Dictionary


def load_env_file(path):
    """Load simple KEY=value pairs from a deployment environment file."""
    values = {}
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_value(name, env_file_values, fallback=None):
    """Read a value from the env file, then from the process environment."""
    value = env_file_values.get(name) or os.getenv(name)
    return value if value else fallback


def check_radius(
    *,
    auth_mode_name,
    server_name,
    secret_name,
    dictionary_name,
    username,
    password,
    env_file_values,
    label,
    verbose=False,
):
    """Send one RADIUS authentication request and return a process exit code."""
    backend = env_value(auth_mode_name, env_file_values, "mock").lower()
    server = env_value(server_name, env_file_values)
    secret = env_value(secret_name, env_file_values)
    dictionary_path = env_value(dictionary_name, env_file_values)

    if verbose:
        print(f"Environment file values loaded for {label} authentication.")
        print(f"  {auth_mode_name}={backend!r}")
        print(f"  {server_name}={server!r}")
        print(f"  {secret_name}=<set, {len(secret or '')} characters>")
        print(f"  {dictionary_name}={dictionary_path!r}")

    missing = [
        name
        for name, value in (
            (server_name, server),
            (secret_name, secret),
            (dictionary_name, dictionary_path),
        )
        if not value
    ]
    if missing:
        print(f"Missing required values in env file: {', '.join(missing)}", file=sys.stderr)
        return 2

    if backend != "radius":
        print(f"{auth_mode_name} is set to {backend!r}, not 'radius'.", file=sys.stderr)
        return 2

    dictionary = Path(dictionary_path)
    if verbose:
        print(
            f"  dictionary exists={dictionary.exists()} "
            f"readable={os.access(dictionary, os.R_OK)}"
        )
        try:
            addresses = sorted(
                {item[4][0] for item in socket.getaddrinfo(server, 1812, type=socket.SOCK_DGRAM)}
            )
            print(f"  DNS addresses for {server}: {', '.join(addresses)}")
        except OSError as exc:
            print(f"  DNS lookup failed: {type(exc).__name__}: {exc}")

    if password is None:
        password = getpass.getpass(f"{label} password: ")

    try:
        client = Client(
            server=server,
            secret=secret.encode("utf-8"),
            dict=Dictionary(dictionary_path),
        )
    except Exception as exc:
        print(
            f"Could not initialize RADIUS client: {type(exc).__name__}: {exc!r}",
            file=sys.stderr,
        )
        return 1
    request = client.CreateAuthPacket(
        code=pyrad.packet.AccessRequest,
        User_Name=username,
    )
    request["User-Password"] = request.PwCrypt(password)

    try:
        reply = client.SendPacket(request)
    except Exception as exc:
        print(
            f"RADIUS request failed: {type(exc).__name__}: {exc!r}",
            file=sys.stderr,
        )
        if verbose:
            print(
                "Check DNS, UDP port 1812, firewall rules, shared secret, "
                "and whether this client IP is registered in the RADIUS server.",
                file=sys.stderr,
            )
        return 1

    if reply.code == pyrad.packet.AccessAccept:
        print("Access-Accept")
        return 0
    if reply.code == pyrad.packet.AccessReject:
        print("Access-Reject")
        return 1

    print(f"Unexpected RADIUS reply: {reply.code}")
    return 1
