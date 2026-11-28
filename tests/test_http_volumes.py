"""Real HTTP reads, including the virtual Zarr v2 exposed by MAX IV's server."""
import asyncio
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import find_spec
import json
import re
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from urllib.request import Request, urlopen
import uuid

import h5py
import numpy as np
import tifffile
from trame.app import get_server

from tomoswaxs.app import Demo
from tomoswaxs.projects import Project, legacy_axis
from tomoswaxs.sources import http_url, source_location, source_name
from tomoswaxs.volumes import VolumeSource, import_tiff, import_pixel_size


@contextmanager
def http_directory(root,denied=()):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*_):pass
        def send_head(self):
            self._range_size=None
            if self.path in denied:
                self.send_error(403);return None
            requested=self.headers.get('Range')
            path=Path(self.translate_path(self.path))
            if not requested or not path.is_file():return super().send_head()
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',requested)
            size=path.stat().st_size
            if not match or not any(match.groups()):
                self.send_error(416);return None
            a,b=match.groups()
            start=int(a) if a else max(0,size-int(b))
            stop=min(size,int(b)+1) if a and b else size
            if not 0<=start<stop<=size:
                self.send_error(416);return None
            stream=path.open('rb');stream.seek(start);self._range_size=stop-start
            self.send_response(206);self.send_header('Content-Length',str(stop-start))
            self.send_header('Content-Range',f'bytes {start}-{stop-1}/{size}')
            self.send_header('Accept-Ranges','bytes');self.end_headers()
            return stream
        def copyfile(self,source,output):
            if self._range_size is None:return super().copyfile(source,output)
            remaining=self._range_size
            while remaining:
                block=source.read(min(remaining,65536))
                if not block:break
                output.write(block);remaining-=len(block)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(root)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}'
    finally:server.shutdown();server.server_close();thread.join()


@contextmanager
def virtual_hdf5_server():
    import uvicorn
    from hdf5_zarr_serve.server import create_app
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen()
    base=f'http://127.0.0.1:{sock.getsockname()[1]}'
    server=uvicorn.Server(uvicorn.Config(create_app(token='test-token'),log_level='error'))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    try:
        deadline=time.monotonic()+10
        while not server.started:
            if not thread.is_alive() or time.monotonic()>deadline:raise RuntimeError('Test data server did not start.')
            time.sleep(.01)
        yield base
    finally:server.should_exit=True;thread.join(timeout=10);sock.close()


class HttpVolumeChecks(unittest.TestCase):
    def test_http_permission_errors_are_not_missing_chunks(self):
        from tomoswaxs.http_sources import HttpV2Store
        with tempfile.TemporaryDirectory() as root,http_directory(root,denied=('/0/0.0.0',)) as base:
            store=HttpV2Store(base)
            with self.assertRaises(KeyError):store['missing']
            with self.assertRaises(Exception) as error:store['0/0.0.0']
            self.assertNotIsInstance(error.exception,KeyError)
            self.assertIn('403',str(error.exception))

    def test_url_identity_and_project_references_survive_relocation(self):
        url='https://example.org/access-token/a%20b.ome.zarr/?key=abc%2Fdef'
        self.assertEqual(source_location(url),url)
        self.assertEqual(source_name(url),'a b.ome.zarr')
        self.assertEqual(legacy_axis(url),'y')
        self.assertIsNone(import_pixel_size(url))
        for invalid in ('ftp://example.org/a','https://','http:/missing-host','https://[broken',''):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):http_url(invalid)
        with tempfile.TemporaryDirectory() as root:
            project=Project.create(root,'Remote')
            identifier=project.add_sample(url,'Remote sample')
            loaded=Project.load(project.path)
            self.assertEqual(loaded.dataset_path(loaded.sample(identifier)),url)
            self.assertEqual(loaded.sample(identifier)['datasets']['ct'],{'format':'ome-zarr','url':url})

    def fixture(self,folder):
        values=np.arange(24*30*36,dtype=np.uint16).reshape(24,30,36)
        tiff=Path(folder)/'input.tiff';tifffile.imwrite(tiff,values,photometric='minisblack',metadata={'axes':'ZYX'})
        store=import_tiff(tiff,Path(folder)/'test image.ome.zarr',[2,3,4])
        return values,store

    def test_ngff_http_reads_crops_and_spacing_match_local(self):
        with tempfile.TemporaryDirectory() as root:
            values,path=self.fixture(root)
            with http_directory(root) as base:
                url=base+'/test%20image.ome.zarr/'
                remote=VolumeSource(url);local=VolumeSource(path)
                self.assertEqual(remote.path,url)
                np.testing.assert_equal(remote.read_region((slice(2,9),slice(5,11),slice(3,15))),values[2:9,5:11,3:15])
                np.testing.assert_allclose(remote.spacing,local.spacing)
                np.testing.assert_allclose(remote.origin,local.origin)
                crop=[[3,20],[4,21],[2,18]]
                a=remote.preview(1,crop=crop);b=local.preview(1,crop=crop)
                np.testing.assert_equal(a.values,b.values);np.testing.assert_allclose(a.origin,b.origin)

    def test_open_url_in_project_reopen_and_failure_preserves_sample(self):
        with tempfile.TemporaryDirectory() as root:
            values,path=self.fixture(root)
            with http_directory(root) as base:
                url=base+'/test%20image.ome.zarr'
                app=Demo(get_server('http-'+uuid.uuid4().hex,client_type='vue3'),render_device='system',restore_project=False)
                self.addCleanup(app.window.Finalize)
                project=Project.create(Path(root)/'project','Remote CT');app.project=project
                app.state.update(picker_mode='volume',volume_url_mode=True,volume_url=url)
                asyncio.run(app.load_volume_selection())
                self.assertEqual(app.state.volume_error,'')
                self.assertTrue(app.state.has_volume)
                identifier=app.active_sample_id
                self.assertEqual(app.project.sample(identifier)['datasets']['ct']['url'],url)
                self.assertFalse(app.state.sample_pixel_size_editable)
                app.state.contrast_high=20000;app.persist_active()
                asyncio.run(app.open_project_path(project.path,discard=True))
                self.assertEqual(app.state.project_error,'')
                self.assertEqual(app.state.contrast_high,20000)
                original=app.volume_source
                app.state.update(picker_mode='volume',volume_url_mode=True,volume_url=base+'/missing.zarr')
                asyncio.run(app.load_volume_selection())
                self.assertTrue(app.state.volume_error)
                self.assertIs(app.volume_source,original)
                # Relinking may move between a hosted image and a local copy.
                app._relink_id=identifier
                app.state.update(picker_mode='relink',volume_url_mode=False,volume_selection=str(path))
                asyncio.run(app.load_volume_selection())
                self.assertEqual(app.state.volume_error,'')
                self.assertEqual(app.project.dataset_path(app.project.sample(identifier)),path.resolve())
                app.state.update(picker_mode='relink',volume_url_mode=True,volume_url=url)
                asyncio.run(app.load_volume_selection())
                self.assertEqual(app.state.volume_error,'')
                self.assertEqual(app.project.dataset_path(app.project.sample(identifier)),url)

    @unittest.skipUnless(find_spec('hdf5_zarr_serve'),'Optional hdf5-zarr-serve integration fixture is not installed.')
    def test_virtual_hdf5_multiscale_data_and_gzip(self):
        with tempfile.TemporaryDirectory() as root,virtual_hdf5_server() as base:
            values=np.arange(32*40*48,dtype=np.uint16).reshape(32,40,48)
            for compression in (None,'gzip'):
                path=Path(root)/f'input-{compression}.h5'
                with h5py.File(path,'w') as f:
                    ds=f.create_dataset('exchange/data',data=values,chunks=(8,8,8),compression=compression)
                    ds.attrs['pixel_size']=2.5
                    f.create_dataset('exchange/data_02',data=values[::2,::2,::2],chunks=(8,8,8),compression=compression)
                request=Request(base+'/open',data=json.dumps({'path':str(path)}).encode(),headers={'Content-Type':'application/json'})
                with urlopen(request) as response:result=json.load(response)
                url=base+result['scan_url']
                source=VolumeSource(url)
                self.assertEqual(len(source.images),2)
                np.testing.assert_allclose(source.spacing,[.0025]*3)
                np.testing.assert_equal(source.read_region((slice(1,8),slice(4,12),slice(5,15))),values[1:8,4:12,5:15])
                level=source.preview(1,level=1)
                np.testing.assert_equal(level.values,values[::2,::2,::2])
                np.testing.assert_allclose(level.spacing,[.005]*3)
