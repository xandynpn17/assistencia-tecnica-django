from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    script = project_root / 'run_local.ps1'
    if not script.exists():
        print(f'run_local.ps1 nao encontrado em {script}', file=sys.stderr)
        return 1

    cmd = [
        'powershell.exe',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        str(script),
    ]
    return subprocess.call(cmd, cwd=str(project_root))


if __name__ == '__main__':
    raise SystemExit(main())
