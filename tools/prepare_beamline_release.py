"""Build a versioned beamline download bundle and its checksum catalogue; upload separately."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import quote
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from tomoswaxs.model_store import ModelRelease,_filename,_validate_manifest


def prepare(manifest,destination,version,tag,extras=()):
    document=json.loads(manifest.read_text())
    paths=list(dict.fromkeys([manifest]+[manifest.parent/_filename(document[key]) for key in ('geometry','sample_area_geometry')]+list(extras)))
    if len({path.name for path in paths})!=len(paths):raise ValueError('Bundle filenames must be unique.')
    files={_filename(path.name):dict(size=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths}
    filename=f'formax-{version}.zip'
    url=f'https://github.com/ctroein/tomoswaxs/releases/download/{quote(tag,safe="")}/{filename}'
    # Validate identifiers before constructing the output path.
    validated=ModelRelease.from_dict(dict(version=version,url=url,size=1,sha256='0'*64,files=files))
    _validate_manifest(manifest.parent,validated)
    destination.mkdir(parents=True,exist_ok=True);archive=destination/filename
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_STORED) as bundle:
        for path in sorted(paths):
            entry=zipfile.ZipInfo(path.name,date_time=(1980,1,1,0,0,0));entry.external_attr=0o100644<<16
            bundle.writestr(entry,path.read_bytes())
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    release=ModelRelease(version,url,archive.stat().st_size,digest,files)
    (destination/(filename+'.sha256')).write_text(f'{digest}  {filename}\n')
    catalogue=destination/'beamline_release.json'
    catalogue.write_text(json.dumps({'formax':asdict(release)},indent=2)+'\n')
    return archive,catalogue


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path);parser.add_argument('destination',type=Path)
    parser.add_argument('--version',required=True);parser.add_argument('--tag',required=True)
    parser.add_argument('--include',type=Path,action='append',default=[],help='Additional provenance/credits/licence file to include')
    args=parser.parse_args()
    for path in prepare(args.manifest,args.destination,args.version,args.tag,args.include):print(path)
