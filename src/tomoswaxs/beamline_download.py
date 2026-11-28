"""Acquire optional equipment assets without blocking the Trame event loop."""
import asyncio
import logging
import threading

import vtk

from .beamline_mesh import CadBeamlineModel
from .model_store import configured_release,ensure_model


class BeamlineDownloads:
    def init_beamline_download(self):
        self._beamline_release=configured_release()
        self._beamline_download_task=None;self._beamline_download_cancel=threading.Event()
        self._beamline_download_ready=False
        self.state.update(beamline_model_loading=False,show_beamline_download=False,
                          beamline_download_message='',beamline_download_percent=0,beamline_download_error='')
        self.server.controller.on_server_ready.add(self.beamline_download_ready)
        self.server.controller.on_server_exited.add(self.cancel_beamline_download)

    def beamline_download_ready(self,**_):
        self._beamline_download_ready=True
        self.request_beamline_model(self.state.beamline_level)

    def request_beamline_model(self,level,fit_camera=False):
        if level=='sample':
            self.cancel_beamline_download();return False
        if self._beamline_release is None or isinstance(self.beamline,CadBeamlineModel):return False
        self._beamline_download_level=level;self._beamline_download_fit=fit_camera
        if self._beamline_download_task and not self._beamline_download_task.done():return True
        try:loop=asyncio.get_running_loop()
        except RuntimeError:return False
        self._beamline_download_cancel=threading.Event()
        self.server.clear_state_client_cache('show_beamline_download')
        self.state.update(beamline_model_loading=True,show_beamline_download=True,
                          beamline_download_message='Checking installed model',beamline_download_percent=0,beamline_download_error='')
        self._beamline_download_task=loop.create_task(self.download_beamline_model())
        return True

    def cancel_beamline_download(self,**_):
        self._beamline_download_cancel.set()
        self.state.show_beamline_download=False

    def retry_beamline_download(self):
        self.request_beamline_model(self._beamline_download_level,self._beamline_download_fit)

    async def download_beamline_model(self):
        loop=asyncio.get_running_loop();cancel=self._beamline_download_cancel
        def progress(phase,percent):
            def update():
                if cancel.is_set():return
                self.state.update(beamline_download_message=phase,beamline_download_percent=percent)
                self.state.flush()
            loop.call_soon_threadsafe(update)
        try:
            path=await asyncio.to_thread(ensure_model,self._beamline_release,
                                        progress=progress,cancelled=cancel.is_set)
            if cancel.is_set():return
            self.state.update(beamline_download_message='Loading ForMAX model',beamline_download_percent=100)
            self.state.flush();await asyncio.sleep(0)
            if cancel.is_set():return
            # Build all CAD props on the render thread, isolated from the live
            # renderer until the complete model has loaded successfully.
            temporary=vtk.vtkRenderer();model=CadBeamlineModel(temporary,path)
            previous=self.beamline
            for actor in previous.parts.values():self.renderer.RemoveActor(actor)
            for actor,_ in previous.labels:self.renderer.RemoveViewProp(actor)
            for actor in model.parts.values():
                temporary.RemoveActor(actor);self.renderer.AddActor(actor)
            for actor,_ in model.labels:
                temporary.RemoveViewProp(actor);self.renderer.AddViewProp(actor)
            model.renderer=self.renderer;self.beamline=model;self._beamline_model_path=path
            self.state.show_beamline_download=False
            if self._beamline_download_fit:self.select_beamline_level(self._beamline_download_level)
            else:
                self.update_beamline();self.reset_clipping_range();self.view.update()
        except InterruptedError:pass
        except asyncio.CancelledError:
            cancel.set();raise
        except Exception as error:
            if cancel.is_set():return
            logging.getLogger(__name__).exception('Could not load the ForMAX model')
            self.server.clear_state_client_cache('show_beamline_download')
            self.state.update(beamline_download_error=str(error),show_beamline_download=True)
        finally:
            self.state.beamline_model_loading=False
            self.state.flush()
