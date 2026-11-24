"""View-dependent volume selection; manual crop and camera remain authoritative."""
import asyncio
from itertools import combinations, product
import math
import time

import numpy as np
import vtk

from .volume_cache import DecodedChunkCache


def box_planes(bounds):
    """Half spaces n.x + d >= 0, with inward normals."""
    rows=[]
    for i,(lo,hi) in enumerate(np.asarray(bounds).reshape(3,2)):
        normal=np.eye(3)[i]
        rows.extend([np.r_[normal,-lo],np.r_[-normal,hi]])
    return np.asarray(rows)


def region_vertices(planes,bounds):
    """Vertices of the convex intersection of a viewing region and image crop."""
    constraints=np.vstack([planes,box_planes(bounds)])
    triples=constraints[np.array(list(combinations(range(len(constraints)),3)))]
    nonsingular=np.abs(np.linalg.det(triples[:,:,:3]))>1e-10
    triples=triples[nonsingular]
    if not len(triples):return np.empty((0,3))
    points=np.linalg.solve(triples[:,:,:3],-triples[:,:,3,None])[:,:,0]
    tolerance=1e-8*max(1.,np.max(np.abs(bounds)))
    return points[np.all(points @ constraints[:,:3].T+constraints[:,3]>=-tolerance,axis=1)]


def enclosing_crop(points,source,manual):
    if not len(points):return None
    # Include boundary cells and an interpolation margin.
    low=np.floor((points.min(axis=0)-source.origin)/source.spacing+.5).astype(int)-1
    high=np.ceil((points.max(axis=0)-source.origin)/source.spacing+.5).astype(int)+1
    limits=np.asarray(manual)
    low=np.maximum(low,limits[:,0]);high=np.minimum(high,limits[:,1])
    if np.any(low>=high):return None
    return tuple((int(a),int(b)) for a,b in zip(low,high))


def contains(outer,inner):
    return all(a<=c and b>=d for (a,b),(c,d) in zip(outer,inner))


class AutoDetail:
    def init_auto_detail(self):
        self._detail_timer=None
        self._detail_overview=None
        self._detail_planes=None
        self._detail_frozen=None
        self._detail_key=None
        self._detail_plan=None
        self._detail_failure=None
        self._detail_changed_at=0.
        self._detail_cache=DecodedChunkCache()
        self._detail_busy=False
        self._detail_rendering=False
        self.state.update(detail_enabled=False,detail_depth=100.,detail_frozen=False,detail_level=0,
                          detail_depth_um='',detail_notice='')
        self.server.controller.trigger('nim_auto_detail')(self.receive_auto_detail)

    def reset_auto_detail(self):
        self._detail_cache.clear()
        if self._detail_timer:self._detail_timer.cancel()
        self._detail_timer=None
        self._detail_overview=None
        self._detail_planes=self._detail_frozen=self._detail_key=self._detail_plan=None
        self._detail_failure=None
        self._detail_busy=False
        self.state.update(detail_enabled=False,detail_depth=100.,detail_frozen=False,
                          detail_depth_um='',detail_notice='')
        if hasattr(self,'mapper'):self.mapper.RemoveAllClippingPlanes()

    def auto_detail_state(self):
        return dict(enabled=bool(self.state.detail_enabled),depth=float(self.state.detail_depth),
                    frozen_planes=self._detail_frozen.tolist() if self._detail_frozen is not None else None)

    def restore_auto_detail(self,spec):
        self._detail_frozen=np.asarray(spec['frozen_planes'],dtype=float) if spec.get('frozen_planes') is not None else None
        self._detail_key=None
        self.state.update(detail_enabled=spec.get('enabled',False),detail_depth=spec.get('depth',100.),
                          detail_frozen=self._detail_frozen is not None)

    def receive_auto_detail(self,spec,context):
        if context!=self.state.sample_context or not self.state.has_volume or self.state.volume_loading:return
        try:
            depth=float(spec['depth'])
            if not math.isfinite(depth) or not 0<=depth<=100:raise ValueError('Depth must be between 0 and 100.')
            enabled=bool(spec['enabled'])
            self.state.update(detail_enabled=enabled,detail_depth=depth,render_error='')
            if not enabled:
                self.reset_auto_detail()
                self.state.detail_depth=depth
                self.receive_volume_view(dict(crop=self.state.crop_bounds,level=self.state.render_level,
                    limit=self.state.volume_preview_mib),context)
            else:
                self.cancel_render_load()
                self.state.render_level='auto'
                self._render_spec=dict(crop=tuple(map(tuple,self.state.crop_bounds)),level='auto')
                if 'freeze' in spec:
                    self._detail_frozen=None
                    if spec['freeze']:
                        planes=self.detail_view_planes()
                        self._detail_frozen=planes.copy()
                    self.state.detail_frozen=self._detail_frozen is not None
                self._detail_key=None;self._detail_failure=None
                self.detail_refresh()
                self.view.update()
            self.schedule_project_save()
        except (KeyError,TypeError,ValueError) as error:
            self.state.render_error=str(error)
        self.state.flush()

    def detail_view_planes(self):
        camera=self.renderer.GetActiveCamera()
        copy=vtk.vtkCamera();copy.DeepCopy(camera)
        coefficients=[0.]*24
        copy.GetFrustumPlanes(self.renderer.GetTiledAspectRatio(),coefficients)
        sides=np.asarray(coefficients).reshape(6,4)[:4]
        focal=np.asarray(camera.GetFocalPoint())
        direction=np.asarray(camera.GetDirectionOfProjection())
        bounds=np.asarray(self.crop_world_bounds(self.state.crop_bounds)).reshape(3,2)
        corners=np.array([(*p,1.) for p in product(*bounds)]) @ self.sample_pose_matrix().T
        depths=(corners[:,:3]-focal) @ direction
        value=float(self.state.detail_depth)
        thickness=2*max(abs(depths.min()),abs(depths.max())) if value>=100 else self.camera_view_span()*(2**(-3+6*value/100))
        thickness=max(float(np.min(self.render_source.spacing)),thickness)
        self.state.detail_depth_um=f'{thickness*1000:.5g} µm'
        front=max(-thickness/2,-camera.GetDistance()+max(camera.GetClippingRange()[0],1e-6))
        world=np.vstack([sides,np.r_[direction,-direction @ focal-front],np.r_[-direction,direction @ focal+thickness/2]])
        local=world @ self.sample_pose_matrix()
        return local/np.linalg.norm(local[:,:3],axis=1)[:,None]

    def detail_clip(self):
        self.mapper.RemoveAllClippingPlanes()
        if self._detail_planes is None:return
        world=self._detail_planes @ np.linalg.inv(self.sample_pose_matrix())
        for coefficients in world:
            normal=coefficients[:3]
            plane=vtk.vtkPlane();plane.SetNormal(*normal)
            plane.SetOrigin(*(-coefficients[3]*normal/(normal @ normal)))
            self.mapper.AddClippingPlane(plane)

    def detail_camera_key(self):
        camera=self.renderer.GetActiveCamera()
        return (tuple(np.round((*camera.GetPosition(),*camera.GetFocalPoint(),*camera.GetViewUp(),
                    camera.GetViewAngle(),camera.GetParallelScale(),float(camera.GetParallelProjection()),
                    self.renderer.GetTiledAspectRatio()),9)),
                tuple(self.sample_pose_matrix().ravel()),tuple(map(tuple,self.state.crop_bounds)),
                float(self.state.detail_depth),float(self.state.volume_preview_mib),bool(self.state.detail_frozen))

    def detail_render_start(self,*_):
        if self._detail_rendering or not self.state.detail_enabled:return
        if self.state.volume_loading or not self.state.has_volume:return
        self._detail_rendering=True
        try:self.detail_refresh()
        except Exception as error:
            self.state.render_error=f'Auto detail: {error}'
        finally:self._detail_rendering=False

    def detail_refresh(self,force=False):
        if not self.state.detail_enabled or not self.state.has_volume or self.state.volume_loading:return
        key=self.detail_camera_key()
        changed=key!=self._detail_key
        if not force and not changed:return
        if changed:self._detail_changed_at=time.monotonic()
        self._detail_key=key
        planes=self._detail_frozen if self._detail_frozen is not None else self.detail_view_planes()
        if self._detail_frozen is not None:
            thickness=max(0.,planes[-2,3]+planes[-1,3])
            self.state.detail_depth_um=f'{thickness*1000:.5g} µm'
        self._detail_planes=planes
        self.detail_clip()
        manual=tuple(map(tuple,self.state.crop_bounds))
        points=region_vertices(planes,self.crop_world_bounds(manual))
        required=enclosing_crop(points,self.render_source,manual)
        if required is None:
            self._detail_plan=None
            self.state.detail_notice='No sample in view'
            if self._detail_timer:self._detail_timer.cancel()
            self._detail_timer=None
            self.cancel_render_load()
            return
        self.state.detail_notice=''
        total=float(self.state.volume_preview_mib)
        overview_budget=max(1.,min(8.,total/8))
        budget=max(1.,total-overview_budget)
        self._detail_cache.resize(min(256.,max(8.,2*total))*1024**2)
        # Fetch extra coverage, but test reuse against the actual visible region.
        # Padding all image axes protects oblique rotations as well as pans.
        crop=tuple((max(a,c-int(math.ceil((d-c)*.12))),
                    min(b,d+int(math.ceil((d-c)*.12))))
                   for (c,d),(a,b) in zip(required,manual))
        options=self.render_source.level_options(budget,crop)
        pixel=self.camera_view_span()/max(1,self.renderer.GetSize()[1])
        fitting=[o for o in options if o['fits']]
        chosen=fitting[0] if fitting else options[-1]
        useful=[o for o in fitting if max(o['spacing'])<=pixel*1.5]
        if useful:chosen=useful[-1]
        old=self._detail_plan
        if old and old['level']<len(options):
            previous=options[old['level']]
            if previous['fits'] and pixel*.65<=max(previous['spacing'])<=pixel*1.8:chosen=previous
        stride=1
        while np.prod([(n+stride-1)//stride for n in chosen['shape']])*self.render_source.images[chosen['level']].data.dtype.itemsize>budget*1024**2:
            stride*=2
        self._detail_plan=dict(crop=crop,required=required,level=chosen['level'],budget=budget,
                              spacing=np.asarray(chosen['spacing'])*stride,
                              request_level=chosen['level'] if chosen['fits'] else 'auto')
        self.state.detail_level=chosen['level']
        overview_key=(id(self.render_source),manual,overview_budget)
        if self._detail_overview and self._detail_overview[0]!=overview_key:self._detail_overview=None
        loaded=getattr(self,'loaded_volume',None)
        if loaded is not None and loaded.source is self.render_source:
            if loaded.values.nbytes<=overview_budget*1024**2 and self._detail_overview is None:
                self._detail_overview=(overview_key,loaded)
            if self.detail_sufficient(loaded,self._detail_plan):
                if self._detail_timer:self._detail_timer.cancel()
                self._detail_timer=None
                return
        # Never replace useful detail merely because its padded box is too small.
        # Only use a retained coarse array when it restores otherwise absent coverage.
        if (self._detail_overview and loaded is not self._detail_overview[1]
                and not self.detail_overlap(loaded,required)
                and contains(self._detail_overview[1].crop,required)):
            self.install_detail_volume(self._detail_overview[1],render=False)
        self.schedule_detail()

    @staticmethod
    def detail_overlap(volume,crop):
        if volume is None or volume.crop is None:return 0.
        intersection=np.prod([max(0,min(b,d)-max(a,c)) for (a,b),(c,d) in zip(volume.crop,crop)])
        return float(intersection/np.prod([b-a for a,b in crop]))

    def detail_sufficient(self,volume,plan):
        return (volume is not None and volume.source is self.render_source and volume.crop is not None
                and contains(volume.crop,plan['required'])
                and (volume.display_threshold is None or volume.display_threshold==self.display_array_key()[2])
                and (volume.refinement_crop is None or contains(volume.refinement_crop,plan['required'])
                     or np.all(np.asarray(plan['spacing'])>=np.asarray(volume.refinement_spacing)*(1-1e-8)))
                and np.all(np.asarray(volume.spacing)<=plan['spacing']*1.01)
                and volume.values.nbytes<=plan['budget']*1024**2)

    def schedule_detail(self):
        if self._detail_busy or self._detail_timer is not None:return
        try:loop=asyncio.get_running_loop()
        except RuntimeError:return
        # One settling policy, shared by initial and subsequent refinement stages.
        # Once stable, continue through the remaining stages without another delay.
        delay=max(0.,.10-(time.monotonic()-self._detail_changed_at))
        self._detail_timer=loop.call_later(delay,self.detail_request)

    def detail_request(self):
        self._detail_timer=None
        if not self.state.detail_enabled or self._detail_plan is None or self.state.volume_loading:return
        if self._detail_busy:return
        plan=self._detail_plan
        loaded=getattr(self,'loaded_volume',None)
        if self.detail_sufficient(loaded,plan):return
        target=plan['level']
        candidates=[]
        # Two intermediate scales at most; coarse data covers the new view,
        # rather than repeatedly displaying a tiny full-sample overview.
        for level in range(min(len(self.render_source.images)-1,target+2),target,-1):
            spacing=self.render_source.geometry(self.render_source.images[level])[0]
            candidates.append((level,plan['budget'],spacing))
        if plan['request_level']=='auto':
            # Single-scale and unusually large coarsest levels refine by stride.
            coarse_budget=max(1.,plan['budget']/8)
            candidates.append(('auto',coarse_budget,plan['spacing']*2))
        candidates.append((plan['request_level'],plan['budget'],plan['spacing']))
        useful=self.detail_overlap(loaded,plan['required'])>=.6
        for level,budget,spacing in candidates:
            if (loaded is not None and loaded.source is self.render_source
                    and (loaded.display_threshold is None or loaded.display_threshold==self.display_array_key()[2])
                    and np.all(np.asarray(loaded.spacing)<=np.asarray(spacing)*1.01)
                    and (contains(loaded.crop,plan['required']) or useful)
                    and loaded.values.nbytes<=plan['budget']*1024**2):
                continue
            failure=(plan['crop'],level,budget)
            if failure==self._detail_failure:return
            self._detail_busy=True
            self.queue_render_load(plan['crop'],level,budget,('detail',))
            return
        # Partial overlap can skip coarser stages, but the final region must cover
        # the whole view even when its spacing equals the currently loaded array.
        failure=(plan['crop'],plan['request_level'],plan['budget'])
        if failure==self._detail_failure:return
        self._detail_busy=True
        self.queue_render_load(*failure,kind=('detail',))

    def install_detail_volume(self,volume,render=True):
        self.volume,self.spacing,self.origin=volume.values,volume.spacing,volume.origin
        self.loaded_volume=volume
        self.set_image_data()
        self.set_crop_planes(self.state.crop_bounds)
        self.detail_clip()
        self.update_render_summary(volume)
        self.renderer.ResetCameraClippingRange(self.scene_bounds())
        if render:self.view.update()

    def detail_loaded(self,volume,kind):
        if not self.state.detail_enabled or self._detail_plan is None:return
        plan=self._detail_plan
        # A moved camera can still use a completed intermediate, but not replace
        # a sharper full-coverage array with a late, coarser result.
        loaded=getattr(self,'loaded_volume',None)
        sharper=(loaded is not None and loaded.source is self.render_source
                 and (loaded.display_threshold is None or loaded.display_threshold==self.display_array_key()[2])
                 and self.detail_overlap(loaded,plan['required'])>=.6
                 and np.all(np.asarray(loaded.spacing)<=np.asarray(volume.spacing)*1.01))
        if (contains(volume.crop,plan['required']) and volume.values.nbytes<=plan['budget']*1024**2
                and not self.detail_sufficient(loaded,plan)
                and not (sharper and np.any(np.asarray(volume.spacing)>np.asarray(loaded.spacing)*1.01))):
            total=float(self.state.volume_preview_mib)
            overview_budget=max(1.,min(8.,total/8))
            if volume.values.nbytes<=overview_budget*1024**2:
                self._detail_overview=((id(self.render_source),tuple(map(tuple,self.state.crop_bounds)),overview_budget),volume)
            self.install_detail_volume(volume)

    def detail_load_finished(self):
        self._detail_busy=False
        if self.state.detail_enabled:
            self.detail_refresh(force=True)
