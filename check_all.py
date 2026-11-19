"""Run the full regression and both public demos from the repository root.

The entry keeps the original V1 coverage (check_project.py plus line.workday)
and adds the anonymous-window sample replay. Any failing business assertion
propagates as a nonzero exit status.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

COMMANDS = (
    ('unittest', [sys.executable, '-B', 'check_project.py']),
    ('anonymous replay', [sys.executable, '-B', 'check_anonymous.py', 'replay']),
    ('workday demo', [sys.executable, '-B', '-m', 'line.workday']),
)


def main():
    for label, command in COMMANDS:
        print(f'--- {label}', flush=True)
        completed = subprocess.run(command, cwd=ROOT)
        if completed.returncode != 0:
            print(f'{label} failed with exit {completed.returncode}', file=sys.stderr)
            return completed.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
