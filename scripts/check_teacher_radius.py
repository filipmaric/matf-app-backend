#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Manually check teacher authentication against the configured RADIUS server."""

import argparse

from radius_check_common import check_radius, load_env_file


def main():
    parser = argparse.ArgumentParser(
        description="Send a teacher RADIUS login request using matf.env."
    )
    parser.add_argument(
        "--env-file",
        default="/var/www/matf-app/matf.env",
        help="Path to the matf.env file",
    )
    parser.add_argument("--username", required=True, help="Teacher username")
    parser.add_argument("--verbose", action="store_true", help="Print diagnostic details")
    parser.add_argument(
        "--password",
        help="Teacher password. If omitted, the script will prompt for it.",
    )
    args = parser.parse_args()
    return check_radius(
        auth_mode_name="TEACHER_AUTH_MODE",
        server_name="TEACHER_RADIUS_SERVER",
        secret_name="TEACHER_RADIUS_SECRET",
        dictionary_name="TEACHER_RADIUS_DICTIONARY",
        username=args.username,
        password=args.password,
        env_file_values=load_env_file(args.env_file),
        label="Teacher",
        verbose=args.verbose,
    )


if __name__ == "__main__":
    raise SystemExit(main())
