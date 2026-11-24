"""Crop/level controls and one cancellable rendering load at a time."""
import asyncio
import logging
import threading
from types import SimpleNamespace

import dask.array as da
import numpy as np
import vtk

from .volumes import VolumeSource, ImportCancelled
from .auto_detail import AutoDetail


def array_source(values, spacing, origin):
    """Wrap an in-memory array for crop planning (including the empty renderer buffer)."""
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


class VolumeViewing(AutoDetail):
    def init_volume_viewing(self):
        self._empty_source=array_source(self.volume,self.spacing,self.origin)
        self._render_generation=0
        self._render_task=None
        self._render_pending=None
        self._render_cancel=None
        self._crop_widget_updating=False
        self._crop_dragging=False
        self.init_auto_detail()
        self.state.update(crop_revision=0,crop_bounds=[],render_options=[],render_level='auto',
            render_loaded='',render_target='',render_error='',render_loading=False,
            crop_handles=False,crop_notice='',crop_units='voxel',crop_origin_um=[0.,0.,0.],crop_spacing_um=[1.,1.,1.])
        self.state.client_only('crop_draft_x','crop_draft_y','crop_draft_z','crop_notice','crop_units')
        self.sync_volume_controls()
        self.server.controller.trigger('nim_volume_view')(self.receive_volume_view)
        self.state.change('crop_handles')(self.toggle_crop_handles)

    def cancel_render_load(self):
        self._detail_busy=False
        self._render_generation+=1
        if self._render_cancel:
            self._render_cancel.set()
        self._render_pending=None
        self.state.render_loading=False

    def cancel_volume_render(self):
        self.cancel_render_load()
        if self.state.detail_enabled:
            self.reset_auto_detail()
            self.receive_volume_view(dict(crop=self.state.crop_bounds,level=self.state.render_level,
                limit=self.state.volume_preview_mib),self.state.sample_context)
            return
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
        self.reset_auto_detail()
        self.render_source=volume.source if volume is not None else self._empty_source
        self._render_spec=dict(crop=self.render_source.crop_bounds(volume.crop if volume else None),
                               level=volume.requested_level if volume else 'auto')
        self.publish_crop(self._render_spec)
        self.state.update(render_error='',render_level=str(self._render_spec['level']))
        self.refresh_level_options(self._render_spec['crop'])
        if volume is not None:
            self.update_render_summary(volume)
        else:
            self.update_render_summary(SimpleNamespace(values=self.volume,spacing=self._empty_source.spacing,level=0,stride=1))
            if not self.state.has_volume:
                self.state.volume_summary='No CT image' if self.state.has_sample else 'No sample open'
        if hasattr(self,'crop_widget'):
            self.set_crop_planes(self._render_spec['crop'])
            self.update_crop_widget()

    def publish_crop(self, spec, drafts=True):
        self.state.update(crop_origin_um=((self.render_source.origin-self.render_source.spacing/2)*1000).tolist(),
                          crop_spacing_um=(self.render_source.spacing*1000).tolist())
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
        items=[dict(value='auto',label=f'Auto (L{automatic})',disabled=False)]
        for item in options:
            dimensions='×'.join(map(str,item['shape'][::-1]))
            spacing=' × '.join(f'{s*1000:g}' for s in item['spacing'])
            text=f"L{item['level']}: {dimensions} voxels, {size_text(item['bytes'])}"
            items.append(dict(value=str(item['level']),label=text,disabled=not item['fits']))
        self.state.render_options=items
        chosen=automatic if level in (None,'auto') else level
        self.state.render_target=f"{'×'.join(str(b-a) for a,b in crop)} voxels"
        return options,chosen

    def update_render_summary(self, volume):
        dimensions='×'.join(map(str,volume.values.shape[::-1]))
        spacing=' × '.join(f'{s*1000:g}' for s in volume.spacing)
        extra=f' (subsampling ×{volume.stride})' if volume.stride>1 else ''
        self.state.render_loaded=f'level {volume.level}{extra}\n{dimensions} voxels\n{size_text(volume.values.nbytes)}'
        name=self.render_source.path.name if self.render_source.path else 'Sample'
        self.state.volume_summary=f'{name}: {dimensions} voxels, {size_text(volume.values.nbytes)}'

    def volume_view_state(self):
        result=dict(crop=[list(pair) for pair in self._render_spec['crop']],level=self._render_spec['level'])
        if self.state.detail_enabled:result['auto_detail']=self.auto_detail_state()
        return result

    def receive_volume_view(self, spec, context=None):
        if not self.state.has_sample:
            return False
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
            if self.state.detail_enabled:self.focus_visible_crop(crop)
            self.update_crop_widget(crop=crop)
            if self.state.detail_enabled:
                self.cancel_render_load()
                self._render_spec=dict(crop=crop,level=level)
                self._detail_failure=None
                self._detail_key=None
                self.detail_refresh()
                self.view.update()
                self.schedule_project_save()
                return
            self.view.update()
            self.queue_render_load(crop,level,budget)
        except (KeyError,TypeError,ValueError,RuntimeError) as error:
            self.state.render_error=str(error)
        self.state.flush()

    def queue_render_load(self,crop,level,budget,kind=None):
        self._render_generation+=1
        if self._render_cancel:self._render_cancel.set()
        self._render_pending=(self._render_generation,self.state.sample_context,self.render_source,crop,level,budget,kind)
        self.state.render_loading=True
        if self._render_task is None or self._render_task.done():
            self._render_task=asyncio.get_running_loop().create_task(self.drain_render_loads())

    async def drain_render_loads(self):
        while self._render_pending is not None:
            # Let a burst of slider input settle before reading chunks.
            if self._render_pending[-1] is None:
                await asyncio.sleep(.15)
            if self._render_pending is None:
                break
            generation,context,source,crop,level,budget,kind=self._render_pending
            self._render_pending=None
            cancel=threading.Event()
            self._render_cancel=cancel
            try:
                if kind:
                    volume=await asyncio.to_thread(source.preview,budget,cancel,crop,level,
                        cache=self._detail_cache,contrast=self.contrast)
                else:
                    volume=await asyncio.to_thread(source.preview,budget,cancel,crop,level)
                if (cancel.is_set() or generation!=self._render_generation or context!=self.state.sample_context
                        or source is not self.render_source):
                    continue
                if kind:
                    self.detail_loaded(volume,kind)
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
                    if kind:
                        self._detail_failure=(crop,level,budget)
                        continue
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
                    if not kind:self.cancel_volume_render()
                if self._render_pending is None:
                    self.state.render_loading=False
                if kind and generation==self._render_generation:
                    self.detail_load_finished()
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
        if not self.state.detail_enabled:self.focus_visible_crop(crop)

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
            pose=self.sample_pose_matrix()
            matrix=vtk.vtkMatrix4x4()
            for row in range(4):
                for col in range(4):matrix.SetElement(row,col,float(pose[row,col]))
            transform=vtk.vtkTransform();transform.SetMatrix(matrix)
            self.crop_rep.SetTransform(transform)
            self.crop_widget.SetEnabled(bool(self.state.crop_handles) and not self.state.volume_loading)
        finally:
            self._crop_widget_updating=False

    def widget_crop(self):
        poly=vtk.vtkPolyData();self.crop_rep.GetPolyData(poly)
        pose=self.sample_pose_matrix()
        points=(np.asarray([poly.GetPoint(i) for i in range(poly.GetNumberOfPoints())])-pose[:3,3]) @ pose[:3,:3]
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
