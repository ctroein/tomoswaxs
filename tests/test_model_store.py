"""Optional model downloads: real HTTP transfer, cache integrity and cancellation."""
from dataclasses import asdict
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import zipfile

from tomoswaxs.model_store import ModelRelease,ModelDownloadError,ensure_model


def bundle(files=None,extra=None):
    files=files or {'model.json':json.dumps(dict(version=1,units='millimeter',geometry='station.vtp',sample_area_geometry='sample-area.vtp')).encode(),
                    'station.vtp':b'station mesh'*1000,'sample-area.vtp':b'area mesh'*1000}
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as archive:
        for name,value in {**files,**(extra or {})}.items():archive.writestr(name,value)
    return buffer.getvalue(),{name:dict(size=len(value),sha256=hashlib.sha256(value).hexdigest()) for name,value in files.items()}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests+=1
        if self.server.fail:
            self.send_error(503,'Test service unavailable');return
        self.send_response(200);self.send_header('Content-Length',str(len(self.server.payload)));self.end_headers()
        try:self.wfile.write(self.server.payload)
        except (BrokenPipeError,ConnectionResetError):pass
    def log_message(self,*_):pass


class ModelStoreChecks(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.root=Path(self.folder.name)
        payload,files=bundle();self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.payload=payload;self.server.requests=0;self.server.fail=False
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start()
        self.addCleanup(self.stop,thread)
        self.release=ModelRelease.from_dict(dict(version='v1',url=f'http://127.0.0.1:{self.server.server_port}/formax-v1.zip',
                           size=len(payload),sha256=hashlib.sha256(payload).hexdigest(),files=files))

    def stop(self,thread):
        self.server.shutdown();self.server.server_close();thread.join()

    def test_download_verified_cache_reuse_offline_and_repair(self):
        progress=[]
        path=ensure_model(self.release,self.root,progress=lambda *event:progress.append(event))
        self.assertEqual(path,self.root/'v1/model.json');self.assertEqual(self.server.requests,1)
        self.assertEqual(progress[-1][1],100)
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()),sorted(self.release.files))
        self.server.fail=True
        self.assertEqual(ensure_model(self.release,self.root),path)
        self.assertEqual(self.server.requests,1,'An intact installed model needs no network request')
        mesh=path.with_name('station.vtp');original=mesh.read_bytes();mesh.write_bytes(b'x'*len(original))
        with self.assertRaises(ModelDownloadError):ensure_model(self.release,self.root)
        self.assertEqual(mesh.read_bytes(),b'x'*len(original),'A failed transfer must not replace existing files')
        self.server.fail=False;ensure_model(self.release,self.root)
        self.assertEqual(mesh.read_bytes(),original)
        self.assertFalse(list(self.root.glob('.formax-*')))

    def test_checksum_failure_and_cancellation_leave_no_install(self):
        bad=ModelRelease.from_dict({**asdict(self.release),'sha256':'0'*64})
        with self.assertRaisesRegex(ModelDownloadError,'checksum'):ensure_model(bad,self.root)
        self.assertFalse((self.root/'v1').exists());self.assertEqual(list(self.root.iterdir()),[])
        cancel=threading.Event()
        def progress(phase,percent):
            if phase.startswith('Downloading'):cancel.set()
        with self.assertRaises(InterruptedError):ensure_model(self.release,self.root,progress=progress,cancelled=cancel.is_set)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_unexpected_archive_member_and_bad_manifest_are_rejected(self):
        for extra,bad_manifest in [({'../escape':b'bad'},False),(None,True)]:
            payload,files=bundle(extra=extra)
            if bad_manifest:
                values={'model.json':json.dumps(dict(version=1,units='millimeter',geometry='../station.vtp',sample_area_geometry='sample-area.vtp')).encode(),
                        'station.vtp':b'station','sample-area.vtp':b'area'}
                payload,files=bundle(values)
            self.server.payload=payload
            release=ModelRelease.from_dict({**asdict(self.release),'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),'files':files})
            with self.assertRaises(ModelDownloadError):ensure_model(release,self.root)
            self.assertFalse((self.root/'v1').exists())
            self.assertEqual(list(self.root.iterdir()),[])

    def test_release_identifiers_and_checksums_are_validated(self):
        for field,value in [('version','../escape'),('sha256','invalid'),('url','file:///tmp/model.zip'),('size',0)]:
            with self.subTest(field=field):
                with self.assertRaises(ValueError):ModelRelease.from_dict({**asdict(self.release),field:value})

    def test_release_builder_is_reproducible_and_downloadable(self):
        from tools.prepare_beamline_release import prepare
        source=self.root/'source';source.mkdir()
        payload,files=bundle()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for name in files:(source/name).write_bytes(archive.read(name))
        credits=source/'credits.txt';credits.write_text('Fixture model credits')
        archive,catalogue=prepare(source/'model.json',self.root/'first','prepared-v1','models-v1',[credits])
        other,_=prepare(source/'model.json',self.root/'second','prepared-v1','models-v1',[credits])
        self.assertEqual(archive.read_bytes(),other.read_bytes())
        raw=json.loads(catalogue.read_text())['formax'];self.server.payload=archive.read_bytes()
        raw['url']=self.release.url
        installed=ensure_model(ModelRelease.from_dict(raw),self.root/'installed')
        self.assertEqual(installed.with_name('credits.txt').read_text(),'Fixture model credits')
        self.assertEqual(installed.with_name('station.vtp').read_bytes(),(source/'station.vtp').read_bytes())
