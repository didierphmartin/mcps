"""Prints UPDATE statements that install components/*.py into SynergyAI's code_components table.

Usage: python3 components_sql.py <user_id> > components.sql   (then run the file yourself; this only prints)
"""
import sys
from pathlib import Path

COMPONENTS = {"get_new_job": "ServiceNow: get new job", "complete_job": "ServiceNow: complete job",
              "hand_back": "ServiceNow: hand back"}
_ESCAPES = {"\\": "\\\\", "'": "\\'", "\n": "\\n", "\r": "\\r", "\0": "\\0", "\x1a": "\\Z"}


def sql_string(s: str) -> str:
    return "'" + "".join(_ESCAPES.get(c, c) for c in s) + "'"


def main(argv: list[str]) -> int:
    user_id = argv[1] if len(argv) > 1 else ""
    if not user_id.isdigit() or user_id == "0":
        print("usage: python3 components_sql.py <user_id>", file=sys.stderr)
        return 1
    print("-- ServiceNow code components from components/*.py. Run this yourself; it changes code only.")
    for file, name in COMPONENTS.items():
        code = (Path(__file__).resolve().parent / "components" / f"{file}.py").read_text(encoding="utf-8")
        print(f"UPDATE code_components SET code = {sql_string(code.rstrip())}, updated_at = CURRENT_TIMESTAMP"
              f" WHERE user_id = {user_id} AND name = {sql_string(name)};")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
