"""Versioned, verified optional beamline assets on the application host."""
from dataclasses import dataclass
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import tempfile
from time import monotonic
import urllib.error
import urllib.parse
import urllib.request
import zipfile


class ModelDownloadError(OSError):
    """A model acquisition failure suitable for display to the user."""


def _filename(name):
    if not isinstance(name,str) or name in ('','.','..') or '/' in name or '\\' in name or '\0' in name:
        raise ValueError('Model bundle files must have simple filenames.')
    return name


def _digest(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):
        raise ValueError('Invalid model SHA-256 checksum.')
    return value


@dataclass(frozen=True)
class ModelRelease:
    version: str
    url: str
    size: int
    sha256: str
    files: dict

    @classmethod
    def from_dict(cls,raw):
        version=raw['version'];url=raw['url'];size=raw['size']
        if not isinstance(version,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]*',version):
            raise ValueError('Invalid model version.')
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme not in ('https','http') or not parsed.hostname:
            raise ValueError('Invalid model download URL.')
        if type(size) is not int or size<=0:raise ValueError('Invalid model download size.')
        files=raw['files']
        if not isinstance(files,dict) or 'model.json' not in files:raise ValueError('Model bundle must include model.json.')
        for name,info in files.items():
            _filename(name);_digest(info['sha256'])
            if type(info['size']) is not int or info['size']<0:raise ValueError('Invalid model file size.')
        return cls(version,url,size,_digest(raw['sha256']),files)


def configured_release():
    """The catalogue stays empty until a model release is published."""
    raw=json.loads(Path(__file__).with_name('beamline_release.json').read_text())
    return ModelRelease.from_dict(raw['formax']) if raw.get('formax') else None


def model_directory():
    root=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share')).expanduser()
    return root/'tomoswaxs'/'beamline-models'/'formax'


def ensure_model(release,directory=None,*,progress=lambda phase,percent:None,cancelled=lambda:False):
    """Reuse verified files or fetch/extract a trusted ZIP without exposing partial files.

    The catalogue pins both the archive and each installed file. Concurrent
    installers may write only the same verified content, using atomic file moves;
    the manifest is installed last. Each future use verifies the complete bundle.
    """
    destination=Path(directory if directory is not None else model_directory())/release.version
    last=0.
    def check():
        if cancelled():raise InterruptedError('Model download cancelled.')
    def notify(phase,percent):
        nonlocal last
        check();now=monotonic()
        if now-last>=.25 or percent in (0,95,100):
            progress(phase,int(percent));last=now
    try:
        total=sum(info['size'] for info in release.files.values())
        notify('Checking installed model',0)
        done=0;valid=True
        for name,info in release.files.items():
            file=destination/name
            if not file.is_file() or file.stat().st_size!=info['size']:
                valid=False;break
            digest=hashlib.sha256()
            with file.open('rb') as stream:
                while chunk:=stream.read(256*1024):
                    check();digest.update(chunk);done+=len(chunk)
                    notify('Checking installed model',90*done/max(1,total))
            if digest.hexdigest()!=info['sha256']:valid=False;break
        if valid:
            _validate_manifest(destination,release)
            notify('Model ready',100);return destination/'model.json'
        destination.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.formax-',dir=destination.parent) as temporary:
            staging=Path(temporary);archive=staging/'download.zip';digest=hashlib.sha256();done=0
            notify('Downloading ForMAX model',0)
            request=urllib.request.Request(release.url,headers={'Accept-Encoding':'identity'})
            with urllib.request.urlopen(request,timeout=10) as response,archive.open('wb') as stream:
                length=response.headers.get('Content-Length')
                if length is not None and int(length)!=release.size:
                    raise ModelDownloadError('The model download has an unexpected size.')
                read=getattr(response,'read1',response.read)
                while chunk:=read(256*1024):
                    check();done+=len(chunk)
                    if done>release.size:raise ModelDownloadError('The model download is larger than expected.')
                    stream.write(chunk);digest.update(chunk)
                    notify('Downloading ForMAX model',80*done/release.size)
            check()
            if done!=release.size:raise ModelDownloadError('The model download ended before the whole file arrived.')
            if digest.hexdigest()!=release.sha256:raise ModelDownloadError('The model download failed checksum verification.')
            extracted=staging/'files';extracted.mkdir();done=0
            with zipfile.ZipFile(archive) as bundle:
                names=bundle.namelist()
                if len(names)!=len(set(names)) or set(names)!=set(release.files):
                    raise ModelDownloadError('The model bundle contains unexpected or missing files.')
                for name,info in release.files.items():
                    if bundle.getinfo(name).file_size!=info['size']:
                        raise ModelDownloadError(f'Unexpected size for model file {name}.')
                    digest=hashlib.sha256()
                    with bundle.open(name) as source,(extracted/name).open('wb') as target:
                        while chunk:=source.read(256*1024):
                            check();target.write(chunk);digest.update(chunk);done+=len(chunk)
                            notify('Unpacking ForMAX model',80+15*done/max(1,total))
                    if digest.hexdigest()!=info['sha256']:
                        raise ModelDownloadError(f'Model file {name} failed checksum verification.')
            _validate_manifest(extracted,release);notify('Installing ForMAX model',95)
            # From here, finish the short install even if cancellation arrives.
            # Every replacement has the exact content pinned by this release.
            destination.mkdir(exist_ok=True)
            for name in sorted(release.files,key=lambda name:name=='model.json'):
                os.replace(extracted/name,destination/name)
        notify('Model ready',100)
        return destination/'model.json'
    except (InterruptedError,ModelDownloadError):raise
    except (OSError,ValueError,KeyError,zipfile.BadZipFile,RuntimeError,http.client.HTTPException) as error:
        raise ModelDownloadError(f'Could not obtain the ForMAX model: {error}') from error


def _validate_manifest(directory,release):
    model=json.loads((directory/'model.json').read_text())
    if model.get('version')!=1 or model.get('units')!='millimeter':
        raise ModelDownloadError('Unsupported beamline model manifest.')
    for field in ('geometry','sample_area_geometry'):
        name=_filename(model[field])
        if name not in release.files or not name.endswith('.vtp'):
            raise ModelDownloadError(f'The model bundle is missing its {field} mesh.')
