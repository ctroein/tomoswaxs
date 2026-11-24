"""Project identity shared by the application and its About dialog."""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import subprocess


def build_version():
    root=Path(__file__).resolve().parents[2]
    if (root/'.git').exists():
        try:
            return subprocess.run(['git','-c',f'safe.directory={root}','describe','--always','--tags','--dirty'],
                                  cwd=root,capture_output=True,text=True,check=True,timeout=2).stdout.strip()
        except (OSError,subprocess.SubprocessError):
            pass
    try:
        return version('tomoswaxs')
    except PackageNotFoundError:
        return 'unknown'


NAME = 'TomoSWAXS'
DESCRIPTION = 'µCT and SAXS visualization for beamline workflows'
BUILD = build_version()
LICENSE_NAME = 'MIT License'
CONTRIBUTORS = ('Carl Troein', 'Emanuel Larsson', 'Mira Viljanen', 'Daniel White', 'Stuart Ansell')
COPYRIGHT = 'Copyright (c) 2026 ' + ', '.join(CONTRIBUTORS)
DISPLAY_COPYRIGHT = 'Copyright (c) 2026 ' + ', '.join(name.replace(' ', '\u00a0') for name in CONTRIBUTORS)
COLLABORATION = 'NIM is a collaboration between InfraVis, MAX IV and NAISS.'
