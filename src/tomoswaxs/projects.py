"""Versioned project records and atomic persistence, independent of the GUI."""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid


FORMAT = 'nim-ct-saxs-project'
VIEW_FIELDS = ('beam_x','beam_y','radius_x','radius_y','angle','opacity','contrast_low','contrast_high')


def legacy_axis(path):
    """Read old viewer settings once as defaults; never modify the dataset."""
    settings = Path(path)/'nim-view.json'
    if not settings.exists():
        return 'y'
    data = json.loads(settings.read_text())
    if not isinstance(data,dict) or data.get('rotation_axis','y') not in ('x','y','z'):
        raise ValueError('Invalid axis assignment in nim-view.json.')
    return data.get('rotation_axis','y')


def validate_view(view):
    if not isinstance(view,dict):
        raise ValueError('Invalid sample viewing state.')
    for key in VIEW_FIELDS:
        if key in view and (type(view[key]) not in (int,float) or not math.isfinite(view[key])):
            raise ValueError(f'Invalid saved {key}.')
    for key,low,high in [('radius_x',10,500),('radius_y',10,500),('angle',-180,180),('opacity',.05,1)]:
        if key in view and not low <= view[key] <= high:
            raise ValueError(f'Saved {key} is outside the supported range.')
    if 'contrast_low' in view and 'contrast_high' in view and view['contrast_low'] >= view['contrast_high']:
        raise ValueError('Invalid saved contrast range.')
    volume=view.get('volume')
    if volume is not None:
        if not isinstance(volume,dict) or set(volume)!={'crop','level'}:
            raise ValueError('Invalid saved volume selection.')
        crop=volume['crop'];level=volume['level']
        if (not isinstance(crop,list) or len(crop)!=3 or any(not isinstance(pair,list) or len(pair)!=2 or
                any(type(v) is not int for v in pair) or not 0<=pair[0]<pair[1] for pair in crop)):
            raise ValueError('Invalid saved volume crop.')
        if level!='auto' and (type(level) is not int or level<0):
            raise ValueError('Invalid saved volume level.')
    camera = view.get('camera')
    if camera is not None:
        if not isinstance(camera,dict):
            raise ValueError('Invalid saved camera.')
        for key in ('position','focal_point','view_up'):
            values=camera.get(key)
            if not isinstance(values,list) or len(values)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
                raise ValueError(f'Invalid camera {key}.')
        direction=[p-f for p,f in zip(camera['position'],camera['focal_point'])]
        up=camera['view_up']
        cross=[direction[1]*up[2]-direction[2]*up[1],direction[2]*up[0]-direction[0]*up[2],direction[0]*up[1]-direction[1]*up[0]]
        if not any(cross):
            raise ValueError('Invalid camera direction or view-up vector.')
        for key in ('view_angle','parallel_scale','zoom_out_limit'):
            if type(camera.get(key)) not in (int,float) or not math.isfinite(camera[key]) or camera[key]<=0:
                raise ValueError(f'Invalid camera {key}.')
        if camera['view_angle']>=180 or type(camera.get('parallel_projection')) is not bool:
            raise ValueError('Invalid camera projection.')


SAVED_VIEW_FIELDS = ('beam_x','beam_y','angle','camera')


def validate_saved_views(views):
    if not isinstance(views,list):
        raise ValueError('Invalid saved-view list.')
    ids,names=set(),set()
    for item in views:
        if not isinstance(item,dict):
            raise ValueError('Invalid saved view.')
        identifier=item.get('id')
        if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',identifier) or identifier in ids:
            raise ValueError('Invalid or duplicate saved-view ID.')
        ids.add(identifier)
        name=item.get('name')
        if not isinstance(name,str) or not name.strip():
            raise ValueError('Enter a name for the saved view.')
        key=name.strip().casefold()
        if key in names:
            raise ValueError('A saved view already has that name.')
        names.add(key)
        view=item.get('view')
        if not isinstance(view,dict) or set(view)!=set(SAVED_VIEW_FIELDS):
            raise ValueError('A saved view must contain X/Y position, angle and camera.')
        validate_view(view)


class Project:
    def __init__(self, path, document, fingerprint=None):
        self.path=Path(path).expanduser().resolve()
        self.document=deepcopy(document)
        self._fingerprint=fingerprint
        self.validate(self.document)

    @property
    def root(self):
        return self.path.parent

    @staticmethod
    def validate(document):
        if not isinstance(document,dict) or document.get('format')!=FORMAT or document.get('version')!=1:
            raise ValueError('Unsupported NIM project format or version.')
        if not isinstance(document.get('name'),str) or not document['name'].strip():
            raise ValueError('Enter a project name.')
        if not isinstance(document.get('samples'),list):
            raise ValueError('Invalid project sample list.')
        ids=set()
        for sample in document['samples']:
            if not isinstance(sample,dict):
                raise ValueError('Invalid sample record.')
            identifier=sample.get('id')
            if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',identifier) or identifier in ids:
                raise ValueError('Invalid or duplicate sample ID.')
            ids.add(identifier)
            if not isinstance(sample.get('name'),str) or not sample['name'].strip():
                raise ValueError('Enter a sample name.')
            if not isinstance(sample.get('datasets'),dict) or not isinstance(sample.get('settings',{}),dict):
                raise ValueError('Invalid sample datasets or settings.')
            ct=sample['datasets'].get('ct',{})
            if not isinstance(ct,dict):
                raise ValueError('Invalid sample CT dataset reference.')
            if ct.get('kind')!='synthetic' and (ct.get('format')!='ome-zarr' or not isinstance(ct.get('path'),str) or not ct['path']):
                raise ValueError('Invalid sample CT dataset reference.')
            if sample.get('settings',{}).get('rotation_axis','y') not in ('x','y','z'):
                raise ValueError('Invalid sample axis assignment.')
            validate_view(sample.get('view',{}))
            validate_saved_views(sample.get('saved_views',[]))
        if document.get('active_sample_id') is not None and document['active_sample_id'] not in ids:
            raise ValueError('Active sample is missing from the project.')

    @classmethod
    def create(cls,directory,name):
        directory=Path(directory).expanduser().resolve()
        project=cls(directory/'project.json',dict(format=FORMAT,version=1,name=name.strip(),samples=[],active_sample_id=None))
        directory.mkdir(parents=True,exist_ok=True)
        project._write(project.document,create=True)
        return project

    @classmethod
    def load(cls,path):
        path=Path(path).expanduser().resolve()
        if path.is_dir():
            path=path/'project.json'
        raw=path.read_bytes()
        return cls(path,json.loads(raw),hashlib.sha256(raw).digest())

    def _write(self,document,create=False):
        self.validate(document)
        raw=(json.dumps(document,indent=2,allow_nan=False)+'\n').encode()
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root,prefix='.project-',delete=False) as stream:
                temporary=Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if create:
                os.link(temporary,self.path)  # Exclusive creation, including existing manifests.
            else:
                if hashlib.sha256(self.path.read_bytes()).digest()!=self._fingerprint:
                    raise OSError('Project changed on disk; reopen it before saving further changes.')
                os.replace(temporary,self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.document=deepcopy(document)
        self._fingerprint=hashlib.sha256(raw).digest()

    def change(self,**fields):
        document={**deepcopy(self.document),**fields}
        if document!=self.document:
            self._write(document)

    def sample(self,identifier):
        return deepcopy(next(s for s in self.document['samples'] if s['id']==identifier))

    def update_sample(self,identifier,**fields):
        samples=deepcopy(self.document['samples'])
        record=next(s for s in samples if s['id']==identifier)
        record.update(fields)
        self.change(samples=samples)

    def reference(self,path):
        path=Path(path).expanduser().resolve()
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    def dataset_path(self,sample):
        ct=sample['datasets']['ct']
        if ct.get('kind')=='synthetic':
            return None
        return (self.root/ct['path']).resolve()

    def output_directory(self,kind,identifier,create=False):
        if kind not in ('data','results','figures') or not re.fullmatch(r'[A-Za-z0-9_-]+',identifier):
            raise ValueError('Invalid sample output location.')
        directory=self.root/kind/identifier
        if create:
            directory.mkdir(parents=True,exist_ok=True)
        return directory

    def add_sample(self,path,name,axis='y',view=None,identifier=None,saved_views=None):
        identifier=identifier or uuid.uuid4().hex
        ct={'kind':'synthetic'} if path is None else {'format':'ome-zarr','path':self.reference(path)}
        sample=dict(id=identifier,name=name.strip(),datasets=dict(ct=ct,scattering={'kind':'synthetic'}),
                    settings={'rotation_axis':axis},view=view or {})
        if saved_views:
            sample['saved_views']=deepcopy(saved_views)
        self.change(samples=[*self.document['samples'],sample],active_sample_id=identifier)
        return identifier
