"""Camera-only orbit controls, independent of measured sample coordinates."""
import math
import numpy as np
from .orientation import sample_rotation


class CameraControls:
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
            self.state.stereo_notice='Use a stereo strength between 0 and 5°.'
            return
        self.state.stereo_notice=''
        self.window.SetStereoTypeToAnaglyph()
        self.window.SetAnaglyphColorMask(3,4) if self.state.stereo_swap else self.window.SetAnaglyphColorMask(4,3)
        self.window.SetAnaglyphColorSaturation(0.)
        self.renderer.GetActiveCamera().SetEyeAngle(strength)
        self.window.SetStereoRender(bool(self.state.stereo_enabled and strength>0))
        if self.state.detail_enabled:
            self._detail_key=None
            self.detail_refresh(force=True)
        self.view.update()

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
        self.renderer.ResetCameraClippingRange(self.scene_bounds())
        self.sync_camera_angle()
        self.view.update()
        if finished:self.schedule_project_save()

    def camera_rendered(self,*_):
        self.sync_camera_angle()
        self.schedule_project_save()
