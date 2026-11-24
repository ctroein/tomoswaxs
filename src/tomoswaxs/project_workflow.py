"""Project lifecycle, sample switching and viewing-state persistence."""
import asyncio
import math
import logging
from pathlib import Path
import threading
import uuid
from copy import deepcopy

from trame.widgets import html, quasar

from .projects import Project, VIEW_FIELDS, legacy_axis, validate_view
from .sample_management import SampleManagement
from .volumes import VolumeSource, import_tiff, ImportCancelled, logical_path, import_hdf5


class ProjectWorkflow(SampleManagement):
    def project_dialog_visibility(self,visible):
        self.server.clear_state_client_cache('show_project')
        self.state.show_project=visible
        # This modal is client-only: its browser value may differ from Python's.
        self.state.dirty('show_project')

    def init_projects(self):
        self.project=None
        self.active_sample_id=None
        self._save_timer=None
        self._import_sample_id=uuid.uuid4().hex
        self.state.update(project_name='',sample_name='',has_sample=False,has_volume=False,sample_choices=[],sample_choice='',
                          project_error='',project_open_error='',show_project_open_error=False,
                          show_project=False,project_dialog_mode='new',project_menu_open=False,
                          project_new_directory='',
                          project_open_path='',project_name_draft='',sample_name_draft='',
                          project_include_current=True,project_for_tiff=False,picker_mode='volume',
                          project_relink_choice='',relink_sample_name='',relink_ct_path='',volume_import_mode='external',sample_context=uuid.uuid4().hex,
                          show_samples=False,project_samples=[],managed_sample_choice='',managed_sample_name='',sample_manager_error='')
        self.state.project_new_folder=''
        self._directory_snapshot=None
        self._new_project_choosing=False
        self._directory_for_import=False
        self.state.directory_picker_title='Select project directory'
        self.state.update(recent_projects=[],project_history_event={},project_history_notice='')
        self.state.client_only('recent_projects','project_history_notice')
        self.server.controller.trigger('nim_recent_project')(self.open_recent_project)

    def project_history(self,kind,path=None):
        self._restore_project_pending=False
        self.state.restore_project_allowed=False
        target=Path(path or self.project.path).expanduser().absolute() if kind=='opened' else None
        if target is not None and target.is_dir():
            target=target/'project.json'
        self.state.project_history_event=dict(id=uuid.uuid4().hex,kind=kind,
            path=str(target) if target is not None else '',
            name=self.project.document['name'] if kind=='opened' else '')

    def open_recent_project(self,path,restore=False):
        if self.state.volume_loading:
            return
        if restore:
            if not self._restore_project_pending:
                return
            self._restore_project_pending=False
            self.state.restore_project_allowed=False
            if self.project or self.state.has_sample or self.state.show_volume_picker or self.state.show_project:
                return
        self._volume_task=asyncio.create_task(self.open_project_path(path))

    def sync_project(self):
        project=self.project
        current=project.sample(self.active_sample_id) if project and self.active_sample_id else None
        name=(current['name'] if current else (self.volume_source.path.name if self.volume_source else 'Sample')) if self.state.has_sample else ''
        self.state.update(project_name=project.document['name'] if project else '',sample_name=name,
                          can_include_current=self.can_include_current(),
                          project_name_draft=project.document['name'] if project else '',sample_name_draft=name,
                          project_open_path=str(project.path) if project else '',
                          project_relink_choice=(project.document.get('active_sample_id') or next((s['id'] for s in project.document['samples']),'')) if project else '',
                          sample_choices=[dict(id=s['id'],name=s['name']) for s in project.document['samples']] if project else [],
                          sample_choice=self.active_sample_id or '')
        self.sync_saved_views()
        self.sync_sample_manager()
        self.sync_saxs_sample()

    def capture_view(self):
        if not self.state.has_sample:
            raise ValueError('Open a sample first.')
        if self.parameters() is None:
            raise ValueError('Finish editing the sample controls before saving or switching samples.')
        view={key:float(self.state[key]) for key in VIEW_FIELDS}
        if view['contrast_low']>=view['contrast_high']:
            raise ValueError('Contrast maximum must exceed minimum.')
        camera=self.renderer.GetActiveCamera()
        view['camera']=dict(position=list(camera.GetPosition()),focal_point=list(camera.GetFocalPoint()),
                            view_up=list(camera.GetViewUp()),view_angle=camera.GetViewAngle(),
                            parallel_scale=camera.GetParallelScale(),parallel_projection=bool(camera.GetParallelProjection()),
                            zoom_out_limit=self.zoom_out_limit)
        view['volume']=self.volume_view_state()
        validate_view(view)
        return view

    def restore_view(self,view):
        self.state.update(**{key:value for key,value in view.items() if key in VIEW_FIELDS})
        if 'volume' in view:
            self.restore_auto_detail(view['volume'].get('auto_detail',{}))
        camera=view.get('camera')
        if camera:
            cam=self.renderer.GetActiveCamera()
            cam.SetPosition(*camera['position']); cam.SetFocalPoint(*camera['focal_point'])
            cam.SetViewUp(*camera['view_up']); cam.SetViewAngle(camera['view_angle'])
            cam.SetParallelScale(camera['parallel_scale']); cam.SetParallelProjection(camera['parallel_projection'])
            self.zoom_out_limit=camera['zoom_out_limit']
            self._zoom_camera=(cam.GetViewAngle(),cam.GetDistance())
            self.sync_camera_angle()
            self._camera_crop_key=tuple(self.visible_crop_centre())

    def schedule_project_save(self,**_):
        if not self.project or not self.active_sample_id or self._applying_pose or self.state.volume_loading:
            return
        if self.dragging_beam or self.dragging_controls:
            return
        if self._save_timer:
            self._save_timer.cancel()
        try:
            loop=asyncio.get_running_loop()
        except RuntimeError:
            return
        context=self.state.sample_context
        def save():
            if context==self.state.sample_context:
                self.persist_active()
        self._save_timer=loop.call_later(.3,save)

    def persist_active(self,**_):
        if self._save_timer:
            self._save_timer.cancel(); self._save_timer=None
        if not self.project or not self.active_sample_id:
            return True
        try:
            sample=self.project.sample(self.active_sample_id)
            self.persist_saxs()
            self.project.update_sample(self.active_sample_id,view=self.capture_view(),
                                       settings={**sample.get('settings',{}),'rotation_axis':self.state.rotation_axis})
            self.state.project_error=''
            return True
        except (OSError,ValueError) as error:
            self.state.project_error=f'Could not save project: {error}'
            return False
        finally:
            self.state.flush()

    def show_new_project_for_tiff(self):
        self.state.update(project_dialog_mode='new',project_for_tiff=True,project_include_current=False)
        self._new_project_choosing=True
        self.browse_project_directory()

    def can_include_current(self):
        return self.project is None and self.volume_source is not None and bool(self.state.has_sample)

    def new_project_dialog(self):
        self.state.update(project_dialog_mode='new',project_for_tiff=False,project_include_current=self.can_include_current())
        self._new_project_choosing=True
        self.browse_project_directory()

    def open_project_dialog(self):
        self.state.project_for_tiff=False
        self.browse_project()

    def show_project_settings(self):
        if self.project:
            self.state.project_name_draft=self.project.document['name']
        self.state.project_dialog_mode='settings'
        self.project_dialog_visibility(True)

    def create_project(self):
        if self.state.volume_loading or not self.persist_active():
            return
        try:
            if not self.state.project_new_directory.strip():
                raise ValueError('Choose a project directory on the application host.')
            directory=Path(self.state.project_new_directory).expanduser().resolve()
            if not directory.name:
                raise ValueError('Choose a named project directory.')
            view=self.capture_view() if self.can_include_current() and self.state.project_include_current and not self.state.project_for_tiff else None
            project=Project.create(directory,directory.name)
            if view is not None:
                project.add_sample(self.volume_source.path if self.volume_source else None,self.state.sample_name,
                                   self.state.rotation_axis,view,saved_views=self.current_saved_views())
            if view is not None and self._saxs_config is not None:
                config=deepcopy(self._saxs_config)
                for spec in config['scans']:
                    for key in ('path','metadata'):spec[key]=project.reference(spec[key])
                sample=project.sample(project.document['active_sample_id'])
                project.update_sample(sample['id'],datasets={**sample['datasets'],'scattering':config})
            self.project=project
            self.active_sample_id=project.document['active_sample_id']
            self.state.sample_context=uuid.uuid4().hex
            self.state.project_error=''
            if self.active_sample_id is None:
                self.clear_sample()
            self.sync_project()
            self.project_history('opened',Path(self.state.project_new_directory)/'project.json')
            self.project_dialog_visibility(False)
            if self.state.project_for_tiff:
                self.state.volume_import_mode='project'
                self.set_import_destination()
            self.state.project_for_tiff=False
        except (OSError,ValueError) as error:
            self.state.project_error=str(error)

    def rename_project(self):
        if not self.project or self.state.volume_loading:
            return False
        try:
            name=self.state.project_name_draft.strip()
            self.project.change(name=name)
            self.state.update(project_name=name,project_name_draft=name,project_error='')
            return True
        except (OSError,ValueError) as error:
            self.state.project_error=str(error)
            return False

    def close_project_dialog(self,visible=False):
        if visible:
            return
        if self.state.project_dialog_mode=='settings' and self.project and not self.rename_project():
            self.project_dialog_visibility(True)
        else:
            self.project_dialog_visibility(False)
        self.state.flush()

    def rename_sample(self):
        if not self.project or not self.active_sample_id or self.state.volume_loading:
            return
        try:
            self.project.update_sample(self.active_sample_id,name=self.state.sample_name_draft.strip())
            self.state.project_error=''; self.sync_project()
        except (OSError,ValueError) as error:
            self.state.project_error=str(error)

    def close_project(self):
        if self.state.volume_loading or not self.persist_active():
            return
        if self.state.has_sample:
            self.cache_current_saved_views()
            if self._saxs_config:
                self._saxs_standalone[self.saxs_sample_key()]=deepcopy(self._saxs_config)
        self.state.show_samples=False
        self.project=None; self.active_sample_id=None
        self.state.project_error=''
        self.state.sample_context=uuid.uuid4().hex
        self.sync_project()
        self.project_history('closed')
        self.project_dialog_visibility(False)

    def clear_sample(self):
        self.cancel_render_load()
        self.active_sample_id=None
        self.volume_source=None
        self.state.update(has_sample=False,has_volume=False,sample_context=uuid.uuid4().hex,sample_choice='',
                          sample_name='',volume_summary='No sample open',data_notice='',status='Open a sample to begin.',
                          crop_handles=False)
        self.update_crop_widget()
        if hasattr(self,'sample'):
            self.sample.VisibilityOff();self.beam.VisibilityOff();self.view.update()

    def browse_project(self):
        if self.state.volume_loading:
            return
        self.state.update(picker_mode='project',show_volume_picker=True)
        self.configure_volume_filter()
        self.project_dialog_visibility(False)
        self.list_volume_directory()

    def browse_import_destination(self):
        self.browse_project_directory(import_destination=True)

    def browse_project_directory(self,import_destination=False):
        if self.state.volume_loading:
            return
        if self.state.picker_mode=='project_directory' and self._directory_snapshot is not None:
            return
        keys=('volume_directory','volume_selection','volume_entries','volume_destination','volume_prepared_path',
              'volume_voxel_x','volume_voxel_y','volume_voxel_z','volume_voxel_linked','volume_import_mode',
              'volume_error','picker_mode','show_volume_picker','volume_hdf5_datasets','volume_hdf5_dataset','volume_hdf5_axes')
        self._directory_snapshot={key:deepcopy(self.state[key]) for key in keys}
        self._directory_for_import=import_destination
        self.state.directory_picker_title='Select conversion directory' if import_destination else 'Select project directory'
        directory=(Path(self.state.volume_destination).expanduser().parent if import_destination and self.state.volume_destination
                   else Path(self.state.project_new_directory or self.state.volume_directory).expanduser())
        while not directory.is_dir() and directory!=directory.parent:
            directory=directory.parent
        self.state.update(picker_mode='project_directory',volume_directory=str(directory),
                          show_volume_picker=True,project_new_folder='')
        self.project_dialog_visibility(False)
        self.list_volume_directory()

    def create_project_folder(self):
        try:
            name=self.state.project_new_folder.strip()
            if not name or name in ('.','..') or Path(name).name!=name:
                raise ValueError('Enter a single folder name.')
            directory=Path(self.state.volume_directory).expanduser()/name
            directory.mkdir()
            self.state.update(volume_directory=str(directory),project_new_folder='')
            self.list_volume_directory()
        except (OSError,ValueError) as error:
            self.state.volume_error=str(error)

    def finish_project_directory(self,choose=True):
        snapshot=self._directory_snapshot
        if snapshot is None:
            return
        directory=logical_path(self.state.volume_directory)
        if choose and not directory.is_dir():
            self.state.volume_error='Choose an existing directory.'
            return
        # Restore the underlying TIFF form while its selection callback is paused.
        self.state.update(**{key:value for key,value in snapshot.items() if key not in ('picker_mode','show_volume_picker')})
        self.state.flush()
        self.state.update(picker_mode=snapshot['picker_mode'],show_volume_picker=snapshot['show_volume_picker'])
        if choose and self._directory_for_import:
            name=Path(snapshot['volume_destination']).name or Path(snapshot['volume_selection']).stem+'.ome.zarr'
            self.state.volume_destination=str(directory/name)
        elif choose:
            self.state.project_new_directory=str(directory)
        self._directory_snapshot=None
        if not self._directory_for_import:
            self.project_dialog_visibility(choose or not self._new_project_choosing)
        self._directory_for_import=False
        self._new_project_choosing=False

    def open_volume_picker(self):
        if self.state.volume_loading:
            return
        self.state.update(picker_mode='volume',show_volume_picker=True)
        self.configure_volume_filter()
        self.list_volume_directory()

    def reload_saved_project(self):
        if self.project and not self.state.volume_loading:
            self._volume_task=asyncio.create_task(self.open_project_path(self.project.path,discard=True))

    def report_project_open_error(self,path,error):
        message=f'Cannot open project "{path}": {error}'
        self.state.update(project_error=message,project_open_error=message,show_project_open_error=True)
        if self.state.picker_mode=='project':
            self.state.volume_error=message

    async def open_project_path(self,path,discard=False):
        if self.state.volume_loading:
            return
        self.state.update(project_open_error='',show_project_open_error=False)
        if not discard and not self.persist_active():
            self.report_project_open_error(path,self.state.project_error)
            self.state.flush()
            return
        try:
            if not str(path).strip():
                raise ValueError('Choose a project.json file or project directory.')
            project=Project.load(path)
            self.state.show_samples=False
            self.project=project
            self.clear_sample()
            self.state.sample_context=uuid.uuid4().hex
            self.state.project_error=''; self.sync_project()
            self.project_dialog_visibility(False)
            self.state.update(show_volume_picker=False,picker_mode='volume')
            identifier=project.document.get('active_sample_id')
            if identifier is None and project.document['samples']:
                identifier=project.document['samples'][0]['id']
            if identifier:
                await self.activate_sample(identifier)
                if self.state.project_error:
                    self.report_project_open_error(path,f'The project was read, but its sample could not be loaded. {self.state.project_error}')
            self.project_history('opened',Path(path).expanduser().absolute())
        except (OSError,ValueError) as error:
            self.report_project_open_error(path,str(error) or type(error).__name__)
        except Exception as error:
            logging.getLogger(__name__).exception('Could not open project %s',path)
            self.report_project_open_error(path,f'{type(error).__name__}: {error}')
        finally:
            self.state.flush()

    def select_project_sample(self,**_):
        identifier=self.state.sample_choice
        if self._applying_pose or self.state.volume_loading or not identifier or identifier==self.active_sample_id:
            return
        self._volume_task=asyncio.create_task(self.activate_sample(identifier))

    async def activate_sample(self,identifier):
        if not self.project or self.state.volume_loading:
            return
        if not self.persist_active():
            self.state.sample_choice=self.active_sample_id or ''
            self.state.flush()
            return
        try:
            sample=self.project.sample(identifier)
            await self.load_sample(self.project.dataset_path(sample),self.project,identifier,sample)
        except (OSError,ValueError,StopIteration) as error:
            self.state.project_error=str(error)

    def relink_sample(self):
        if not self.project or self.state.volume_loading or not self.state.project_relink_choice:
            return
        if not self.rename_project():
            return
        self._relink_id=self.state.project_relink_choice
        sample=self.project.sample(self._relink_id)
        self.state.update(picker_mode='relink',show_volume_picker=True,volume_error='',
                          relink_sample_name=sample['name'],relink_ct_path=sample['datasets']['ct'].get('path',''))
        self.configure_volume_filter()
        self.project_dialog_visibility(False)
        self.list_volume_directory()

    def set_import_destination(self,**_):
        if self.project and self.state.volume_import_mode=='project':
            self.state.volume_destination=str(self.project.output_directory('data',self._import_sample_id)/'ct.ome.zarr')
        elif self.state.volume_import_mode=='external' and Path(self.state.volume_selection).suffix.lower() in ('.tif','.tiff','.h5','.hdf5'):
            self.state.volume_destination=str(Path(self.state.volume_selection).with_suffix('.ome.zarr'))

    async def load_volume_selection(self, navigate=False):
        if self.state.volume_loading:
            return
        try:
            path=Path(self.state.volume_selection).expanduser()
            if not self.state.volume_selection:
                raise ValueError('Select sample data or a directory.')
            if self.state.picker_mode=='project_directory':
                if not path.is_dir():
                    raise ValueError('Select a directory.')
                self._list_volume_directory(path)
                return
            from .volumes import is_ome_zarr
            if self.state.picker_mode=='project':
                if path.is_dir() and (navigate or not (path/'project.json').is_file()):
                    self._list_volume_directory(path); return
                await self.open_project_path(path)
                return
            if self.state.picker_mode=='saxs':
                if path.is_dir():
                    self._list_volume_directory(path)
                else:
                    await self.attach_saxs_path(path)
                return
            if path.is_dir() and not is_ome_zarr(path):
                self._list_volume_directory(path); return
            if self.state.picker_mode=='relink' and not is_ome_zarr(path):
                raise ValueError('Select the existing OME-Zarr CT image folder. Relinking does not import TIFF or HDF5 files.')
            if not is_ome_zarr(path) and path.suffix.lower() not in ('.tif','.tiff','.h5','.hdf5'):
                raise ValueError('Supported CT inputs are TIFF, HDF5 and OME-Zarr images.')
            if path.suffix.lower() in ('.h5','.hdf5') and not self.state.volume_hdf5_dataset:
                raise ValueError('Select a numeric 3D dataset to import from the HDF5 file.')
            if not self.persist_active():
                self.state.volume_error=self.state.project_error
                return
            sample=None; identifier=None
            if self.state.picker_mode=='relink':
                identifier=self._relink_id
                sample=self.project.sample(identifier)
            needs_import=path.suffix.lower() in ('.tif','.tiff','.h5','.hdf5')
            if needs_import and not self.state.volume_destination.strip():
                raise ValueError('Choose an OME-Zarr conversion destination.')
            await self.load_sample(path,self.project,identifier,sample,needs_import=needs_import,
                                   destination=self.state.volume_destination,
                                   spacing=[self.state.volume_voxel_x,self.state.volume_voxel_y,self.state.volume_voxel_z],
                                   relink=self.state.picker_mode=='relink')
        except (OSError,ValueError) as error:
            self.state.volume_error=str(error)
        finally:
            self.state.flush()

    async def load_sample(self,path,project,identifier=None,record=None,needs_import=False,destination='',spacing=None,relink=False):
        try:
            budget=float(self.state.volume_preview_mib)
            if not math.isfinite(budget) or budget<1:
                raise ValueError('Voxel array size limit must be at least 1 MiB.')
            self.cancel_render_load()
            context=uuid.uuid4().hex
            self.state.sample_context=context
            self._volume_cancel=threading.Event()
            cancel=self._volume_cancel
            self.state.update(volume_loading=True,volume_error='',volume_progress='Opening sample…')
            self.state.flush()
            dataset=self.state.volume_hdf5_dataset
            axes=self.state.volume_hdf5_axes
            loop=asyncio.get_running_loop()
            def report(text):
                def update():
                    if self.state.sample_context==context:
                        self.state.volume_progress=text; self.state.flush()
                if not loop.is_closed():
                    loop.call_soon_threadsafe(update)
            def read():
                if needs_import and path.suffix.lower() in ('.h5','.hdf5'):
                    selected=import_hdf5(path,destination,dataset,spacing,cancel,report,axes)
                else:
                    selected=import_tiff(path,destination,spacing,cancel,report) if needs_import else path
                selection=record.get('view',{}).get('volume',{}) if record else {}
                if selected is None:return None
                source=VolumeSource(selected)
                level=selection.get('level','auto')
                options=source.level_options(budget,selection.get('crop'))
                if level!='auto' and (level>=len(options) or not options[level]['fits']):level='auto'
                return source.preview(budget,cancel=cancel,crop=selection.get('crop'),level=level,refine=level=='auto')
            volume=await asyncio.to_thread(read)
            if cancel.is_set():
                raise ImportCancelled('Load cancelled.')
            if project is not self.project or context!=self.state.sample_context:
                return
            axis=record.get('settings',{}).get('rotation_axis','y') if record else (legacy_axis(volume.path) if volume else 'y')
            if project:
                if record is None:
                    identifier=project.add_sample(volume.path if volume else None,
                        path.stem if path is not None else 'Sample',axis,identifier=self._import_sample_id,
                        saved_views=self.standalone_saved_views(volume.path if volume else None))
                    record=project.sample(identifier)
                elif relink:
                    datasets={**record['datasets'],'ct':{'format':'ome-zarr','path':project.reference(volume.path)}}
                    project.update_sample(identifier,datasets=datasets)
                project.change(active_sample_id=identifier)
            self._applying_pose=True
            try:
                if volume:
                    self.set_volume_data(volume,rotation_axis=axis)
                else:
                    # Legacy generated-sample entries are retained as samples
                    # without CT, so measured data can still be accessed.
                    self.volume=self._empty_source.data.compute()
                    self.spacing=self._empty_source.spacing;self.origin=self._empty_source.origin
                    self.volume_source=None
                    self.contrast=(0.,65535.)
                    self.sync_volume_controls()
                    self.state.update(sample_pixel_size_editable=False,
                                      volume_summary='No CT image',data_notice='No CT image')
                self.state.update(rotation_axis=axis,radius_x=60.,radius_y=40.,opacity=.55)
                self.set_image_data()
                # Establish bounds for the newly selected sample before fitting the camera.
                self.active_sample_id=identifier if project else None
                self.sample.SetUserMatrix(None)
                self.reset_camera()
                self.restore_view(record.get('view',{}) if record else {})
            finally:
                self._applying_pose=False
            self.dragging_beam=False; self.dragging_controls=False
            self.state.volume_loading=False
            self.state.update(has_sample=True,has_volume=volume is not None)
            self.sync_project()
            self.update_scene()
            self.state.update(show_volume_picker=False,project_error='',picker_mode='volume')
            self._import_sample_id=uuid.uuid4().hex
            self.list_volume_directory()
        except asyncio.CancelledError:
            cancel.set()
            raise
        except (OSError,ValueError,RuntimeError,MemoryError,ImportCancelled) as error:
            self.state.volume_error=str(error)
            self.state.project_error=str(error) if project else ''
            self.state.sample_choice=self.active_sample_id or ''
        except Exception as error:
            logging.getLogger(__name__).exception('Sample loading failed')
            self.state.volume_error=str(error) or type(error).__name__
            self.state.project_error=self.state.volume_error if project else ''
            self.state.sample_choice=self.active_sample_id or ''
        finally:
            self.state.volume_loading=False
            self.state.flush()
        if project is self.project and self.active_sample_id==identifier and not self.state.volume_error:
            self.persist_active()

    def project_menu(self):
        with html.Div(classes='project-menu-anchor'):
            html.Button('Project',id='open-project',classes='project-menu-trigger',
                        raw_attrs=['aria-label="Project"','aria-haspopup="menu"',':aria-expanded="project_menu_open"'])
            with quasar.QMenu(target='#open-project',v_model=('project_menu_open',),auto_close=True,
                              no_refocus=True,classes='project-menu'):
                html.Button('New project…',click=self.new_project_dialog,disabled=('volume_loading',),raw_attrs=['role="menuitem"'])
                html.Button('Open project…',click=self.open_project_dialog,disabled=('volume_loading',),raw_attrs=['role="menuitem"'])
                quasar.QSeparator(v_if=('recent_projects.length',))
                html.Span('Recent projects',v_if=('recent_projects.length',),classes='settings-help')
                html.Button('{{ item.name }}',v_for='item in recent_projects',key=('item.path',),
                            click=(self.open_recent_project,'[item.path]'),title=('item.path',),
                            disabled=('volume_loading',),raw_attrs=['role="menuitem"'])
                quasar.QSeparator(v_if=('recent_projects.length',))
                html.Button('Project settings…',click=self.show_project_settings,
                            disabled=('volume_loading || !project_name',),raw_attrs=['role="menuitem"'])
                html.Button('Reload saved project',click=self.reload_saved_project,
                            disabled=('volume_loading || !project_name',),raw_attrs=['role="menuitem"'],
                            title='Discard unsaved viewing changes and reopen the project from disk')
                html.Button('Close project',click=self.close_project,
                            disabled=('volume_loading || !project_name',),raw_attrs=['role="menuitem"'])

    def project_dialog(self):
        with quasar.QDialog(model_value=('show_project',),update_model_value=(self.close_project_dialog,'[$event]')):
            with quasar.QCard(classes='project-card',raw_attrs=['role="dialog"','aria-labelledby="project-title"']):
                with quasar.QCardSection():
                    html.H2('{{ project_dialog_mode === "new" ? "New project" : "Project settings" }}',id='project-title')
                    with html.Div(v_if=("project_dialog_mode === 'settings'",)):
                        html.Label('Name',raw_attrs=['for="project-name"'])
                        html.Input(id='project-name',v_model=('project_name_draft',),disabled=('volume_loading',))
                        html.P('Project file: {{ project_open_path }}',classes='settings-help')
                        html.Label('Sample whose CT image moved',raw_attrs=['for="relink-sample"'])
                        with html.Select(id='relink-sample',v_model=('project_relink_choice',),disabled=('volume_loading',)):
                            html.Option('{{ sample.name }}',v_for='sample in sample_choices',value=('sample.id',),key=('sample.id',))
                        html.Button('Locate CT image…',click=self.relink_sample,disabled=('volume_loading || !project_relink_choice',))
                    with html.Div(v_if=("project_dialog_mode === 'new'",)):
                        html.Label('Project directory',raw_attrs=['for="new-project-directory"'])
                        with html.Div(classes='path-field'):
                            html.Input(id='new-project-directory',type='text',v_model=('project_new_directory',),readonly=True,disabled=('volume_loading',))
                            self.path_browse_button('Choose project directory',self.browse_project_directory)
                        with html.Label(v_if=('can_include_current && !project_for_tiff',)):
                            html.Input(type='checkbox',v_model=('project_include_current',),disabled=('volume_loading || !has_sample',))
                            html.Span(' Include current sample')
                    html.P('{{ project_error }}',v_if=('project_error',),role='alert',classes='picker-error')
                with quasar.QCardActions(align='right'):
                    html.Button('Cancel',v_if=("project_dialog_mode !== 'settings'",),click='show_project = false')
                    html.Button('Close',v_if=("project_dialog_mode === 'settings'",),click=self.close_project_dialog)
                    html.Button('Create project',v_if=("project_dialog_mode === 'new'",),click=self.create_project,
                                disabled=('volume_loading || !project_new_directory',))
