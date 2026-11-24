#!/usr/bin/env python3
"""Test current stable dependencies and automatically accept successful updates."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version
import tomlkit

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'.git', '.venv', '.dependency-trials', '__pycache__', 'dist', '.pytest_cache'}


def trial_requirements(dependencies, keep):
    """Retain minimums, exclusions, markers, extras and documented exceptions."""
    keep = {canonicalize_name(name): reason for name, reason in keep.items()}
    if any(not reason.strip() for reason in keep.values()):
        raise ValueError('Each retained dependency needs a reason in tool.dependency-trial.keep')
    result = []
    for text in dependencies:
        requirement = Requirement(text)
        if canonicalize_name(requirement.name) not in keep and not requirement.url:
            if any(s.operator in ('~=', '===', '==') for s in requirement.specifier):
                raise ValueError(f'{requirement.name}: use explicit bounds or document a keep exception')
            requirement.specifier = type(requirement.specifier)(','.join(
                str(s) for s in requirement.specifier if s.operator not in ('<', '<=')))
        result.append(str(requirement))
    return result


def accepted_requirements(dependencies, installed, keep):
    result = []
    keep = {canonicalize_name(name) for name in keep}
    for text in dependencies:
        requirement = Requirement(text)
        if requirement.marker and not requirement.marker.evaluate():
            result.append(text)
            continue
        name = canonicalize_name(requirement.name)
        version = Version(installed[name])
        if version.is_prerelease or version.is_devrelease:
            raise ValueError(f'{name}: refusing pre-release {version}')
        if requirement.url or name in keep or requirement.specifier.contains(version):
            result.append(text)
            continue
        lower = [str(s) for s in requirement.specifier if s.operator not in ('<', '<=')]
        major, minor = (version.release + (0, 0))[:2]
        epoch = f'{version.epoch}!' if version.epoch else ''
        requirement.specifier = type(requirement.specifier)(','.join(lower + [f'<{epoch}{major}.{minor+1}']))
        if not requirement.specifier.contains(version):
            raise ValueError(f'{name}: {version} conflicts with retained requirements')
        result.append(str(requirement))
    return result


def fingerprint(root):
    digest = hashlib.sha256()
    for directory, names, files in os.walk(root):
        names[:] = sorted(name for name in names if name not in IGNORED)
        for name in sorted(files):
            path = Path(directory)/name
            if path.is_symlink():
                continue
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def promote(root, candidate, expected):
    """Guard against concurrent edits and roll both files back on write failure."""
    if fingerprint(root) != expected:
        raise RuntimeError('Source changed during the trial; rerun before accepting updates')
    names = ('pyproject.toml', 'uv.lock')
    originals = {name: (root/name).read_bytes() if (root/name).exists() else None for name in names}
    try:
        for name in names:
            temporary = root/(name + '.trial-tmp')
            temporary.write_bytes((candidate/name).read_bytes())
            os.replace(temporary, root/name)
    except BaseException:
        for name, contents in originals.items():
            if contents is None:
                (root/name).unlink(missing_ok=True)
            else:
                (root/name).write_bytes(contents)
        raise
    finally:
        for name in names:
            (root/(name + '.trial-tmp')).unlink(missing_ok=True)


def run(command, cwd, log, env=None, timeout=600):
    print('+ ' + ' '.join(map(str, command)), flush=True)
    with log.open('a') as output:
        output.write('\n+ ' + ' '.join(map(str, command)) + '\n')
        output.flush()
        subprocess.run(list(map(str, command)), cwd=cwd, env=env, stdout=output,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def check_environment(python, source, artifacts, port):
    artifacts.mkdir(parents=True)
    log = artifacts/'checks.log'
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env.pop('VIRTUAL_ENV', None)
    run([python, '-m', 'unittest', 'discover', '-s', source/'tests'], artifacts, log, env)
    # Playwright supplies a Node executable even when no system Node is installed.
    import playwright
    node = shutil.which('node') or str(Path(playwright.__file__).parent/'driver'/'node')
    for test in sorted((source/'tests').glob('*.cjs')):
        run([node, test], artifacts, log, env)
    run(['uv', 'pip', 'check', '--python', python], artifacts, log, env)
    # Fail before launching if the test port is already occupied.
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', port))
    url = f'http://127.0.0.1:{port}'
    # Browser checks exercise a loaded sample; production startup is empty.
    fixture=artifacts/'browser-fixture.ome.zarr'
    run([str(python),'-c',
         'from pathlib import Path; import numpy as np,tifffile; '
         'from tomoswaxs.volumes import import_tiff; '
         'p=Path("browser-fixture.tiff"); z,y,x=np.indices((40,40,40)); '
         'tifffile.imwrite(p,np.uint16(((x-20)**2+(y-20)**2+(z-20)**2<225)*50000),photometric="minisblack"); '
         'import_tiff(p,Path("browser-fixture.ome.zarr"),[20,20,20])'],
        artifacts,log,env)
    with (artifacts/'server.log').open('w') as output:
        server = subprocess.Popen([str(python), '-m', 'tomoswaxs', '--server', '--port', str(port),
                                   '--timeout', '0','--volume',str(fixture)], cwd=artifacts, env=env,
                                  stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 60
            while True:
                if server.poll() is not None:
                    raise RuntimeError('Trial server exited; inspect server.log')
                try:
                    with urlopen(url, timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError('Trial server did not start within 60 seconds')
                time.sleep(.2)
            run([sys.executable, source/'tools/browser_check.py', '--url', url,
                 '--artifacts', artifacts], artifacts, log, env, timeout=300)
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true', help='test and prepare updates without accepting them')
    parser.add_argument('--port', type=int, default=8081)
    args = parser.parse_args()
    if args.port == 8080:
        parser.error('Port 8080 is reserved for the user-facing demo')
    if not sys.platform.startswith('linux'):
        parser.error('Dependency trials currently target Linux')
    if not shutil.which('uv'):
        parser.error('uv must be available on PATH')
    trial = ROOT/'.dependency-trials'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    trial.mkdir(parents=True)
    log = trial/'setup.log'
    expected = fingerprint(ROOT)
    try:
        source = trial/'source'
        shutil.copytree(ROOT, source, symlinks=True,
                        ignore=lambda directory, names: [name for name in names if name in IGNORED])
        original = tomlkit.parse((source/'pyproject.toml').read_text())
        config = tomlkit.parse((source/'pyproject.toml').read_text())
        keep = config['tool']['dependency-trial']['keep']
        config['project']['dependencies'] = trial_requirements(config['project']['dependencies'], keep)
        (source/'pyproject.toml').write_text(tomlkit.dumps(config))
        run(['uv', 'build', '--wheel', '--out-dir', trial/'unbounded-wheel', source], ROOT, log)
        wheel = next((trial/'unbounded-wheel').glob('*.whl'))
        run(['uv', 'venv', '--python', sys.executable, trial/'environment'], ROOT, log)
        python = trial/'environment/bin/python'
        run(['uv', 'pip', 'install', '--python', python, '--upgrade', '--prerelease', 'disallow',
             wheel, *original['dependency-groups']['dev']], ROOT, log)
        versions = json.loads(subprocess.check_output(
            ['uv', 'pip', 'list', '--python', str(python), '--format', 'json'], text=True))
        (trial/'installed.json').write_text(json.dumps(versions, indent=2)+'\n')
        installed = {canonicalize_name(item['name']): item['version'] for item in versions}
        check_environment(python, source, trial/'latest-checks', args.port)
        # Resolve and test the actual bounded package/environment that users receive.
        original['project']['dependencies'] = accepted_requirements(original['project']['dependencies'], installed, keep)
        (source/'pyproject.toml').write_text(tomlkit.dumps(original))
        run(['uv', 'lock', '--upgrade', '--project', source], ROOT, log)
        run(['uv', 'sync', '--locked', '--no-editable', '--project', source], ROOT, log)
        check_environment(source/'.venv/bin/python', source, trial/'locked-checks', args.port)
        run(['uv', 'build', '--out-dir', trial/'dist', source], ROOT, log)
        if not args.check_only:
            promote(ROOT, source, expected)
        (trial/'result.json').write_text(json.dumps({'passed': True, 'accepted': not args.check_only}, indent=2)+'\n')
        print(f'Trial passed. {"Candidate retained" if args.check_only else "Bounds and lockfile updated"}: {trial}')
        return 0
    except Exception as error:
        (trial/'result.json').write_text(json.dumps({'passed': False, 'accepted': False, 'error': str(error)}, indent=2)+'\n')
        print(f'Trial failed: {error}\nConfiguration unchanged. Inspect {trial}\n'
              'See docs/development.md for dependency-trial diagnostics.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
