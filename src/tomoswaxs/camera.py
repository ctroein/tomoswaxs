"""Camera-only orbit controls, independent of measured sample coordinates."""
import math
from itertools import product
import numpy as np
from .orientation import sample_rotation


class CameraControls:
    def update_clipping_for_render(self,*_):
        if self.state.beamline_visible:self.reset_clipping_range()

    def reset_clipping_range(self,*_):
        """Keep useful depth precision at station scale and protect nearby CT."""
        self.renderer.ResetCameraClippingRange(self.scene_bounds())
        if not self.state.beamline_visible:return
        camera=self.renderer.GetActiveCamera()
        near,far=camera.GetClippingRange()
        # A camera inside the station's enclosing box has no useful lower
        # depth bound. Do not spend precision on the first 0.5% of its orbit
        # distance; unlike a fixed world-space cutoff this follows dolly zoom.
        near=max(near,camera.GetDistance()*.005)
        if self.state.has_volume:
            points=self.camera_sample_points()
            depths=(points-np.asarray(camera.GetPosition())) @ np.asarray(camera.GetDirectionOfProjection())
            front=float(depths.min())
            if front>0:
                # Large equipment behind the camera must not push the near
                # plane through a micron-scale sample. Leave a generous guard.
                near=min(near,front*.5)
            else:
                # Inside the crop, retain the small distance-scaled cutoff.
                near=min(near,camera.GetDistance()*.005)
        near=max(1e-9,min(near,far*.5))
        camera.SetClippingRange(near,far)

    def init_camera_controls(self):
        self._camera_crop_key=None
        self.state.update(camera_angle=0.,draft_camera_angle=0.,stereo_enabled=False,stereo_strength=2.,stereo_swap=False,stereo_notice='')
        self.state.client_only('draft_camera_angle')
        self.server.controller.trigger('nim_camera_angle')(self.receive_camera_angle)
        self.server.controller.trigger('nim_beam_view')(self.receive_beam_view)

    def update_stereo(self, **_):
        try:strength=float(self.state.stereo_strength)
        except (TypeError,ValueError):strength=float('nan')
        if not math.isfinite(strength) or not 0<=strength<=5:
            self.state.stereo_notice='Use a stereo strength between 0 and 5.'
            return
        self.state.stereo_notice=''
        self.window.SetStereoTypeToAnaglyph()
        self.window.SetAnaglyphColorMask(3,4) if self.state.stereo_swap else self.window.SetAnaglyphColorMask(4,3)
        self.window.SetAnaglyphColorSaturation(0.)
        self.window.SetStereoRender(bool(self.state.stereo_enabled and strength>0))
        self.sync_stereo_camera()
        if self.state.detail_enabled:
            self._detail_key=None
            self.detail_refresh(force=True)
        self.view.update()

    def sync_stereo_camera(self, *_):
        camera=self.renderer.GetActiveCamera()
        try:strength=float(self.state.stereo_strength)
        except (TypeError,ValueError):return
        if not math.isfinite(strength) or not 0<=strength<=5:return
        angle=0.
        if self.window.GetStereoRender():
            distance=max(camera.GetDistance(),1e-12)
            # Wheel zoom changes the field of view; dolly changes distance.
            # Scale the baseline with the visible span for both zoom mechanisms.
            ratio=min(1.,self.camera_view_span()/(2*distance*math.tan(math.radians(15))))
            if self.state.has_volume:
                world=self.camera_sample_points()
                depths=(world-np.asarray(camera.GetPosition())) @ np.asarray(camera.GetDirectionOfProjection())
                # Reduce the baseline as the foreground approaches the camera,
                # bounding disparity instead of letting near-plane parallax diverge.
                ratio*=max(0.,min(1.,float(depths.min())/distance))
            angle=math.degrees(2*math.atan(math.tan(math.radians(strength/2))*ratio))
        if not math.isclose(camera.GetEyeAngle(),angle,rel_tol=1e-10,abs_tol=1e-12):
            camera.SetEyeAngle(angle)

    def receive_beam_view(self,context=None):
        if self.state.volume_loading or not self.state.has_volume or context!=self.state.sample_context:
            return
        self.reset_camera(True)

    def sync_camera_angle(self,*_):
        if not hasattr(self,'renderer'):
            return
        camera=self.renderer.GetActiveCamera()
        direction=np.asarray(camera.GetPosition())-camera.GetFocalPoint()
        if np.hypot(direction[0],direction[2])>1e-10:
            self.state.camera_angle=round(math.degrees(math.atan2(direction[0],direction[2])),3)

    def camera_sample_points(self):
        bounds=np.asarray(self.crop_world_bounds(self.state.crop_bounds)).reshape(3,2)
        key=(id(self.render_source),self.display_array_key()[2])
        if getattr(self,'_camera_data_key',None)==key:
            clipped=np.column_stack([np.maximum(bounds[:,0],self._camera_data_bounds[:,0]),
                                     np.minimum(bounds[:,1],self._camera_data_bounds[:,1])])
            if np.all(clipped[:,1]>clipped[:,0]):bounds=clipped
        corners=np.array([(*point,1.) for point in product(*bounds)])
        return (corners @ self.sample_pose_matrix().T)[:,:3]

    def visible_crop_centre(self,crop=None):
        bounds=np.asarray(self.crop_world_bounds(crop or self.state.crop_bounds)).reshape(3,2)
        centre=np.r_[bounds.mean(axis=1),1.]
        return (self.sample_pose_matrix() @ centre)[:3]

    def visible_crop_bounds(self):
        from itertools import product
        bounds=np.asarray(self.crop_world_bounds(self.state.crop_bounds)).reshape(3,2)
        points=np.array([(*point,1.) for point in product(*bounds)])
        world=(points @ self.sample_pose_matrix().T)[:,:3]
        return np.column_stack([world.min(axis=0),world.max(axis=0)]).ravel()

    def focus_visible_crop(self,crop=None,force=False):
        if not hasattr(self,'renderer') or not self.state.has_volume:
            return
        if self.state.beamline_visible and self._beamline_scope!='sample':return
        centre=self.visible_crop_centre(crop)
        key=tuple(centre)
        if not force and self._camera_crop_key is not None and np.allclose(
                self._camera_crop_key,key,rtol=1e-10,atol=1e-12):
            return
        self._camera_crop_key=key
        camera=self.renderer.GetActiveCamera()
        delta=centre-camera.GetFocalPoint()
        camera.SetPosition(*(np.asarray(camera.GetPosition())+delta))
        camera.SetFocalPoint(*centre)

    def receive_camera_angle(self,value,finished=True,context=None):
        if self.state.volume_loading or not self.state.has_volume or (context is not None and context!=self.state.sample_context):
            return
        try:angle=float(value)
        except (TypeError,ValueError):return
        if not math.isfinite(angle):return
        angle=self.wrap_angle(angle)
        if not self.state.detail_enabled:self.focus_visible_crop(force=True)
        self.sync_camera_angle()
        delta=self.wrap_angle(angle-float(self.state.camera_angle))
        rotation=sample_rotation('y',delta)
        camera=self.renderer.GetActiveCamera()
        centre=np.asarray(camera.GetFocalPoint())
        camera.SetPosition(*(centre+rotation @ (np.asarray(camera.GetPosition())-centre)))
        camera.SetViewUp(*(rotation @ np.asarray(camera.GetViewUp())))
        self.reset_clipping_range()
        self.sync_camera_angle()
        self.view.update()
        if finished:self.schedule_project_save()

    def camera_rendered(self,*_):
        self.sync_camera_angle()
        self.schedule_project_save()
