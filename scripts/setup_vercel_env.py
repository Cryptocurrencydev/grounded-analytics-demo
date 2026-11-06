"""Copies server-side settings to Vercel without printing them."""
import os
import secrets
import subprocess

from grounded.env import load_env_file

load_env_file()
values = {"PSEUDONYM_SALT": secrets.token_hex(24)}
if key := os.environ.get("ANTHROPIC_API_KEY"):
    values["ANTHROPIC_API_KEY"] = key
for name, value in values.items():
    subprocess.run(["vercel", "env", "rm", name, "production", "--yes"], capture_output=True)
    r = subprocess.run(["vercel", "env", "add", name, "production"], input=value.encode(), capture_output=True)
    print(name, "set" if r.returncode == 0 else f"FAILED: {r.stderr.decode()[:200]}")
