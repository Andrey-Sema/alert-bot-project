"""Compile independently provisioned Redis passwords; never print secrets."""

import argparse
import json
import os
from pathlib import Path

from alert_bot_project.core_shared.redis_acl import USERS, build_acl
from alert_bot_project.core_shared.secrets import read_secret_file


def compile_credentials(password_dir: Path, acl_output: Path, exporter_output: Path) -> None:
    passwords = {
        role: read_secret_file(str(password_dir / f"redis_{role}_password"), f"Redis {role} password", max_bytes=128)
        for role in USERS
    }
    content = build_acl(passwords)
    outputs = (
        (acl_output, content),
        (exporter_output, json.dumps({"redis://alert_monitor@redis:6379": passwords["monitor"]}) + "\n"),
    )
    if acl_output.resolve() == exporter_output.resolve():
        raise ValueError("Redis credential output paths must differ")
    created: list[Path] = []
    try:
        for path, value in outputs:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            created.append(path)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(value)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--password-dir", type=Path, required=True)
    parser.add_argument("--acl-output", type=Path, required=True)
    parser.add_argument("--exporter-output", type=Path, required=True)
    args = parser.parse_args()
    compile_credentials(args.password_dir, args.acl_output, args.exporter_output)
    print("Redis credential files created; protect their filesystem permissions")


if __name__ == "__main__":
    main()
