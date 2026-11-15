"""Crop/level controls and one cancellable rendering load at a time."""
import asyncio
import logging
import threading
from types import SimpleNamespace

import dask.array as da
import numpy as np
import vtk

from .volumes import VolumeSource, ImportCancelled
from .orientation import sample_rotation


def array_source(values, spacing, origin):
    """Give the synthetic specimen the same crop planner as file-backed volumes."""
    source=object.__new__(VolumeSource)
    source.path=None
    source.data=da.from_array(values,chunks=64)
    source.shape,source.dtype=source.data.shape,source.data.dtype
    source.spacing=np.broadcast_to(spacing,3).copy()
    source.origin=np.asarray(origin).copy()
    source.images=[SimpleNamespace(data=source.data,axes_units=dict.fromkeys('xyz','millimeter'),
        scale=dict(zip('xyz',source.spacing)),translation=dict(zip('xyz',source.origin)))]
    return source


def size_text(size):
    return f'{size/1024**3:.2f} GiB' if size>=1024**3 else f'{size/1024**2:.2f} MiB'


class VolumeViewing:
    def init_volume_viewing(self):
        self._synthetic_source=array_source(self.volume,self.spacing,self.origin)
        self._render_generation=0
        self._render_task=None
        self._render_pending=None
        self._render_cancel=None
        self._crop_widget_updating=False
        self._crop_dragging=False
        self.state.update(crop_revision=0,crop_bounds=[],render_options=[],render_level='auto',
            render_loaded='',render_target='',render_error='',render_loading=False,
            crop_handles=False,crop_notice='')
        self.state.client_only('crop_draft_x','crop_draft_y','crop_draft_z','crop_notice')
        self.sync_volume_controls()
        self.server.controller.trigger('nim_volume_view')(self.receive_volume_view)
        self.state.change('crop_handles')(self.toggle_crop_handles)

    def cancel_render_load(self):
        self._render_generation+=1
        if self._render_cancel:
            self._render_cancel.set()
        self._render_pending=None
        self.state.render_loading=False

    def cancel_volume_render(self):
        self.cancel_render_load()
        self.publish_crop(self._render_spec)
        self.state.render_level=str(self._render_spec['level'])
        self.state.render_error=''
        self.refresh_level_options(self._render_spec['crop'],self._render_spec['level'])
        self.set_crop_planes(self._render_spec['crop'])
        self.update_crop_widget()
        self.view.update()
        self.state.flush()

    def sync_volume_controls(self, volume=None):
        self.cancel_render_load()
        self.render_source=volume.source if volume is not None else self._synthetic_source
        self._render_spec=dict(crop=self.render_source.crop_bounds(volume.crop if volume else None),
                               level=volume.requested_level if volume else 'auto')
        self.publish_crop(self._render_spec)
        self.state.update(render_error='',render_level=str(self._render_spec['level']))
        self.refresh_level_options(self._render_spec['crop'])
        if volume is not None:
            self.update_render_summary(volume)
        else:
            self.update_render_summary(SimpleNamespace(values=self.volume,spacing=self._synthetic_source.spacing,level=0,stride=1))
        if hasattr(self,'crop_widget'):
            self.set_crop_planes(self._render_spec['crop'])
            self.update_crop_widget()

    def publish_crop(self, spec, drafts=True):
        self.state.crop_bounds=[list(pair) for pair in spec['crop']]
        for axis,pair,n in zip('xyz',spec['crop'],self.render_source.shape[::-1]):
            self.state[f'crop_max_{axis}']=int(n)
            if drafts:
                key=f'crop_draft_{axis}'
                self.server.clear_state_client_cache(key)
                self.state[key]=dict(min=pair[0],max=pair[1])
                self.state.dirty(key)
        if drafts:self.state.crop_revision+=1

    def refresh_level_options(self, crop, level=None):
        options=self.render_source.level_options(float(self.state.volume_preview_mib),crop)
        automatic=next((o['level'] for o in options if o['fits']),len(options)-1)
        items=[dict(value='auto',label=f'Auto · level {automatic}',disabled=False)]
        for item in options:
            dimensions=' × '.join(map(str,item['shape'][::-1]))
            spacing=' × '.join(f'{s*1000:g}' for s in item['spacing'])
            text=f"Level {item['level']} · {dimensions} · {size_text(item['bytes'])} · {spacing} µm"
            items.append(dict(value=str(item['level']),label=text+(' (too large)' if not item['fits'] else ''),disabled=not item['fits']))
        self.state.render_options=items
        chosen=automatic if level in (None,'auto') else level
        self.state.render_target=f"Crop: {' × '.join(str(b-a) for a,b in crop)} voxels at full resolution"
        return options,chosen

    def update_render_summary(self, volume):
        dimensions=' × '.join(map(str,volume.values.shape[::-1]))
        spacing=' × '.join(f'{s*1000:g}' for s in volume.spacing)
        extra=f' · subsampling ×{volume.stride}' if volume.stride>1 else ''
        self.state.render_loaded=f'Level {volume.level}{extra} · {dimensions} voxels · {size_text(volume.values.nbytes)} · XYZ {spacing} µm'
        name=self.render_source.path.name if self.render_source.path else 'Synthetic specimen'
        self.state.volume_summary=f'{name} · {self.state.render_loaded}'

    def volume_view_state(self):
        return dict(crop=[list(pair) for pair in self._render_spec['crop']],level=self._render_spec['level'])

    def receive_volume_view(self, spec, context=None):
        if context!=self.state.sample_context or self.state.volume_loading:
            return
        try:
            crop=self.render_source.crop_bounds(spec['crop'])
            level=spec.get('level','auto')
            level='auto' if level=='auto' else int(level)
            budget=float(spec['limit'])
            options=self.render_source.level_options(budget,crop)
            if level!='auto' and not 0<=level<len(options):
                raise ValueError('Choose an available resolution level.')
            notice=''
            if level!='auto' and not options[level]['fits']:
                notice=f'Level {level} exceeds the voxel array size limit for this crop. Switched to Auto.'
                level='auto'
            self.state.update(volume_preview_mib=budget,render_level=str(level),render_error=notice)
            self.publish_crop(dict(crop=crop,level=level),drafts=False)
            self.refresh_level_options(crop,level)
            self.set_crop_planes(crop)
            self.update_crop_widget(crop=crop)
            self.view.update()
            self._render_generation+=1
            if self._render_cancel:
                self._render_cancel.set()
            self._render_pending=(self._render_generation,context,self.render_source,crop,level,budget)
            self.state.render_loading=True
            if self._render_task is None or self._render_task.done():
                self._render_task=asyncio.get_running_loop().create_task(self.drain_render_loads())
        except (KeyError,TypeError,ValueError,RuntimeError) as error:
            self.state.render_error=str(error)
        self.state.flush()

    async def drain_render_loads(self):
        while self._render_pending is not None:
            # Let a burst of slider input settle before reading chunks.
            await asyncio.sleep(.15)
            if self._render_pending is None:
                break
            generation,context,source,crop,level,budget=self._render_pending
            self._render_pending=None
            cancel=threading.Event()
            self._render_cancel=cancel
            try:
                volume=await asyncio.to_thread(source.preview,budget,cancel,crop,level)
                if (cancel.is_set() or generation!=self._render_generation or context!=self.state.sample_context
                        or source is not self.render_source):
                    continue
                self.volume,self.spacing,self.origin=volume.values,volume.spacing,volume.origin
                self.loaded_volume=volume
                self._render_spec=dict(crop=crop,level=level)
                self.set_image_data()
                self.set_crop_planes(crop)
                self.update_render_summary(volume)
                self.update_scene()
                self.persist_active()
            except ImportCancelled:
                pass
            except Exception as error:
                if generation==self._render_generation and context==self.state.sample_context:
                    logging.getLogger(__name__).warning('Volume rendering load failed: %s',error)
                    self.state.render_error=str(error)
                    self.publish_crop(self._render_spec)
                    self.state.render_level=str(self._render_spec['level'])
                    self.refresh_level_options(self._render_spec['crop'],self._render_spec['level'])
                    self.set_crop_planes(self._render_spec['crop'])
                    self.update_crop_widget()
                    self.view.update()
            finally:
                if (generation==self._render_generation and context!=self.state.sample_context
                        and source is self.render_source):
                    # A pose recall can invalidate the context without changing
                    # the source. Restore controls/planes to the retained array.
                    self.cancel_volume_render()
                if self._render_pending is None:
                    self.state.render_loading=False
                self.state.flush()

    def toggle_crop_handles(self, **_):
        self.update_crop_widget()
        if hasattr(self,'view'):self.view.update()

    def crop_world_bounds(self, crop):
        # Cell edges, not voxel-centre positions, define the requested region.
        bounds=np.asarray(crop,dtype=float)
        return (self.render_source.origin[:,None]+(bounds-.5)*self.render_source.spacing[:,None]).ravel()

    def set_crop_planes(self, crop):
        self.mapper.SetCroppingRegionPlanes(*self.crop_world_bounds(crop))
        self.mapper.SetCroppingRegionFlagsToSubVolume()
        self.mapper.CroppingOn()

    def build_crop_widget(self):
        self.crop_rep=vtk.vtkBoxRepresentation()
        self.crop_rep.SetPlaceFactor(1)
        self.crop_widget=vtk.vtkBoxWidget2()
        self.crop_widget.SetInteractor(self.interactor)
        self.crop_widget.SetRepresentation(self.crop_rep)
        self.crop_widget.RotationEnabledOff()
        self.crop_widget.TranslationEnabledOff()
        self.crop_widget.AddObserver(vtk.vtkCommand.StartInteractionEvent,self.crop_widget_started)
        self.crop_widget.AddObserver(vtk.vtkCommand.InteractionEvent,self.crop_widget_changed)
        self.crop_widget.AddObserver(vtk.vtkCommand.EndInteractionEvent,self.crop_widget_finished)
        self.update_crop_widget()
        self.set_crop_planes(self._render_spec['crop'])

    def update_crop_widget(self, crop=None, **_):
        if not hasattr(self,'crop_widget') or self._crop_widget_updating or self._crop_dragging:
            return
        if crop is None and not self.state.crop_handles:
            self.crop_widget.SetEnabled(False)
            return
        self._crop_widget_updating=True
        try:
            self.crop_rep.PlaceWidget(self.crop_world_bounds(crop or self.state.crop_bounds))
            rotation=sample_rotation(self.state.rotation_axis,float(self.state.angle))
            matrix=vtk.vtkMatrix4x4()
            for row in range(3):
                for col in range(3):matrix.SetElement(row,col,float(rotation[row,col]))
            transform=vtk.vtkTransform();transform.SetMatrix(matrix)
            self.crop_rep.SetTransform(transform)
            self.crop_widget.SetEnabled(bool(self.state.crop_handles) and not self.state.volume_loading)
        finally:
            self._crop_widget_updating=False

    def widget_crop(self):
        poly=vtk.vtkPolyData();self.crop_rep.GetPolyData(poly)
        rotation=sample_rotation(self.state.rotation_axis,float(self.state.angle))
        points=np.asarray([poly.GetPoint(i) for i in range(poly.GetNumberOfPoints())]) @ rotation
        low=np.rint((points.min(axis=0)-self.render_source.origin)/self.render_source.spacing+.5).astype(int)
        high=np.rint((points.max(axis=0)-self.render_source.origin)/self.render_source.spacing+.5).astype(int)
        shape=np.asarray(self.render_source.shape[::-1])
        low=np.clip(low,0,shape-1);high=np.clip(high,low+1,shape)
        return tuple((int(a),int(b)) for a,b in zip(low,high))

    def crop_widget_started(self,*_):
        self._crop_dragging=True
        self.cancel_render_load()

    def crop_widget_changed(self,*_):
        if self._crop_widget_updating:return
        crop=self.widget_crop()
        self.publish_crop(dict(crop=crop))
        self.set_crop_planes(crop)
        self.view.update()

    def crop_widget_finished(self,*_):
        self._crop_dragging=False
        self.receive_volume_view(dict(crop=[list(p) for p in self.widget_crop()],
            level=self.state.render_level,limit=self.state.volume_preview_mib),self.state.sample_context)
