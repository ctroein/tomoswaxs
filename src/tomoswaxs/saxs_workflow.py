"""Measured-SAXS selection, bounded reads and provisional CT placement."""
import asyncio
from copy import deepcopy
import logging
import math
from pathlib import Path

import numpy as np

from .scattering_data import open_scans,scan_specs
from .registration import initial_placement,positions,angles,MOTORS,motor_rows,rotation_warning
from .orientation import sample_transform


class SaxsWorkflow:
    def init_saxs(self):
        self.saxs_scans=[]
        self._saxs_config=None
        self._saxs_scope=None
        self._saxs_standalone={}
        self._saxs_generation=0
        self._saxs_pending=None
        self._saxs_task=None
        self._saxs_attach_task=None
        self._saxs_restore=None
        self._saxs_setting_pose=False
        self._saxs_requested_selection=None
        self._saxs_requested_context=None
        self.signal_kind='none'
        self.signal=(np.empty(0),np.empty(0),np.empty((0,0)),np.empty(0))
        self.state.update(saxs_available=False,saxs_loading=False,saxs_error='',saxs_sources=[],saxs_axes=[],
            saxs_scan=0,saxs_row=0,saxs_column=0,saxs_revision=0,saxs_pose_revision=0,saxs_frame_info='',saxs_flag='',
            saxs_draft_scan=0,saxs_draft_row=0,saxs_draft_column=0,saxs_input_notice='',
            saxs_input_x='',saxs_input_angle='',
            saxs_link_ct=False,saxs_lock_x=False,saxs_map_x_origin=0.,saxs_map_y_origin=0.,
            saxs_map_x_offset=0.,saxs_map_y_offset=0.,saxs_map_x_sign=1,saxs_map_y_sign=1,
            saxs_map_angle_offset=0.,saxs_map_angle_sign=1.,saxs_y_marks=[],saxs_selection_label='',saxs_map_model='manual',saxs_map_camera_x=0.,saxs_map_camera_y=0.,saxs_map_motors=[],saxs_registration_source='',saxs_recorded={},saxs_frame='',saxs_y_source='')
        self.state.client_only('saxs_draft_scan','saxs_draft_row','saxs_draft_column','saxs_input_notice','saxs_input_x','saxs_input_angle','saxs_lock_x')
        self.state.update(saxs_map_pivot_x=0.,saxs_map_pivot_z=0.)
        self.server.controller.trigger('nim_saxs_selection')(self.receive_saxs_selection)

    def scattering_record(self):
        if self.project and self.active_sample_id:
            return self.project.sample(self.active_sample_id)['datasets'].get('scattering',{})
        return self._saxs_standalone.get(self.saxs_sample_key(),{})

    def saxs_sample_key(self):
        return str(self.volume_source.path) if self.volume_source else '<demo>'

    def persist_saxs(self):
        if self._saxs_config is None:
            return
        config=deepcopy(self._saxs_config)
        if self.project and self.active_sample_id:
            record=self.project.sample(self.active_sample_id)
            for spec in config['scans']:
                for key in ('path','metadata'):
                    spec[key]=self.project.reference(spec[key])
            self.project.update_sample(self.active_sample_id,datasets={**record['datasets'],'scattering':config})
        else:
            self._saxs_standalone[self.saxs_sample_key()]=config

    def sync_saxs_sample(self):
        scope=(str(self.project.path) if self.project else None,self.active_sample_id,self.saxs_sample_key(),bool(self.state.has_sample))
        if scope==self._saxs_scope:
            return
        self._saxs_scope=scope
        self._saxs_generation+=1
        self._saxs_pending=None
        self._saxs_requested_selection=None
        self.saxs_scans=[]
        self._saxs_config=None
        self.state.update(saxs_available=False,saxs_loading=False,saxs_sources=[],saxs_axes=[],saxs_error='',
                          saxs_frame_info='',saxs_selection_label='',saxs_flag='',saxs_recorded={},saxs_frame='',saxs_y_source='',saxs_link_ct=False,saxs_y_marks=[])
        self.state.saxs_revision+=1
        record=self.scattering_record() if self.state.has_sample else {}
        if record.get('kind')=='formax-integrated':
            config=deepcopy(record)
            if self.project:
                for spec in config['scans']:
                    for key in ('path','metadata'):
                        spec[key]=str((self.project.root/spec[key]).resolve())
            self._saxs_config=config
            self._saxs_restore=config
            self.signal_kind='measured'
            self.signal=(np.empty(0),np.empty(0),np.empty((0,0)),np.empty(0))
            if hasattr(self,'curve'):
                self.update_plots()
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return
            self.restore_saxs()
        else:
            self._saxs_restore=None
            self.signal_kind='none'
            self.signal=(np.empty(0),np.empty(0),np.empty((0,0)),np.empty(0))
            if hasattr(self,'curve'):self.update_plots()

    def restore_saxs(self,**_):
        # CLI project loading has a short-lived asyncio loop before server.start.
        # Restart a restore cancelled when that setup loop closed.
        if self._saxs_restore is None and self._saxs_config and not self.saxs_scans and (
                self._saxs_attach_task is None or self._saxs_attach_task.done()):
            self._saxs_restore=deepcopy(self._saxs_config)
        if self._saxs_restore is not None:
            config=self._saxs_restore;self._saxs_restore=None
            self._saxs_attach_task=asyncio.create_task(self.attach_saxs(config['scans'],config,expected_context=self.state.sample_context))
        elif self.saxs_scans and not self.state.saxs_frame_info and (self._saxs_task is None or self._saxs_task.done()):
            selected=self._saxs_config['selection']
            self.request_saxs_frame(selected['scan'],selected['row'],selected['column'])

    def open_saxs_picker(self):
        if not self.state.has_sample or self.state.volume_loading:
            return
        self.close_sample_settings()
        if self.state.show_sample_settings:
            return
        self.state.update(picker_mode='saxs',show_volume_picker=True)
        self.configure_volume_filter()
        self.list_volume_directory()

    def use_saxs_directory(self):
        self._saxs_attach_task=asyncio.create_task(self.attach_saxs_path(self.state.volume_directory))

    async def attach_saxs_path(self,path):
        try:
            specs=scan_specs(path)
        except (OSError,ValueError) as error:
            self.state.volume_error=str(error);self.state.flush();return
        await self.attach_saxs(specs,deepcopy(self._saxs_config))

    async def attach_saxs(self,specs,config=None,expected_context=None):
        if expected_context is not None and expected_context!=self.state.sample_context:
            return
        self._saxs_generation+=1
        generation=self._saxs_generation;context=self.state.sample_context
        self.state.update(saxs_loading=True,saxs_error='',volume_error='')
        self.state.flush()
        try:
            scans=await asyncio.to_thread(open_scans,specs)
            if context!=self.state.sample_context or generation!=self._saxs_generation:
                return
            mapping=config.get('placement',{}) if config else {}
            # Upgrade only the original untouched motor estimate. Preserve
            # custom factors, offsets and manual placements as saved.
            if mapping.get('model')=='motors':
                try:baseline=initial_placement(scans)
                except (OSError,KeyError,ValueError):baseline={}
                if (baseline.get('model')=='stack' and
                    mapping.get('motors')==motor_rows({r['name']:r['reference'] for r in baseline['motors']}) and
                    all(mapping.get(k)==baseline[k] for k in (
                        'x_offset','y_offset','camera_x','camera_y','angle_offset','angle_sign'))):
                    mapping={**mapping,'model':'stack','motors':baseline['motors']}
            defaults=initial_placement(scans,discover=not mapping.get('model'))
            # Old unlabelled defaults centred whichever scan was loaded first.
            legacy_default=(mapping and 'model' not in mapping and all(mapping.get(k)==defaults[k] for k in ('x_origin','y_origin','x_offset','y_offset','x_sign','y_sign','angle_offset')))
            if mapping and 'model' not in mapping and not legacy_default:
                defaults['model']='manual'
            placement=self.validate_saxs_placement({**defaults,**({} if legacy_default else mapping)})
            candidate=dict(kind='formax-integrated',scans=[dict(path=str(s.path),metadata=str(s.metadata)) for s in scans],
                           placement=placement,link_ct=True,
                           selection=(config or {}).get('selection',{}))
            selection=candidate['selection']
            scan=int(selection.get('scan',0));scan=scan if 0<=scan<len(scans) else 0
            index=scans[scan].index
            row=min(max(int(selection.get('row',index.shape[0]//2)),0),index.shape[0]-1)
            col=min(max(int(selection.get('column',index.shape[1]//2)),0),index.shape[1]-1)
            candidate['selection']=dict(scan=scan,row=row,column=col)
            previous=self._saxs_config
            self._saxs_config=candidate
            try:self.persist_saxs()
            except Exception:
                self._saxs_config=previous
                raise
            if defaults.get('axis_hint') and (not config or legacy_default):
                self._applying_pose=True
                try:
                    with self.state:self.state.rotation_axis=defaults['axis_hint']
                finally:self._applying_pose=False
            self.saxs_scans=scans
            self.signal_kind='measured'
            self.state.update(saxs_available=True,saxs_link_ct=True)
            self.publish_saxs_placement()
            self.sync_saxs_marks()
            self.state.update(saxs_scan=scan,saxs_row=row,saxs_column=col,show_volume_picker=False,picker_mode='volume')
            self.state.data_notice=('CT volume' if self.volume_source else 'No CT image')+' · measured SAXS'
            self.sync_sample_manager()
            self.state.saxs_revision+=1
            # Clear the previous source's plots while the first measured frame loads.
            self.signal=(scans[scan].q,scans[scan].phi,np.full((len(scans[scan].phi),len(scans[scan].q)),np.nan),np.full(len(scans[scan].q),np.nan))
            self.update_plots()
            self.request_saxs_frame(scan,row,col)
        except Exception as error:
            if context==self.state.sample_context and generation==self._saxs_generation:
                logging.getLogger(__name__).exception('Could not open SAXS scans')
                self.state.saxs_error=f'{type(error).__name__}: {error}'
                self.state.volume_error=self.state.saxs_error
        finally:
            if generation==self._saxs_generation and self._saxs_pending is None:
                self.state.saxs_loading=False
            self.state.flush()

    @staticmethod
    def validate_saxs_placement(values):
        result=dict(model=values.get('model','manual'),motors=deepcopy(values.get('motors',[])),reference_source=values.get('reference_source','Manual reference'))
        if result['model'] not in ('manual','motors','stack'):raise ValueError('Unknown registration model.')
        for key in ('x_origin','y_origin','x_offset','y_offset','x_sign','y_sign','angle_offset','angle_sign','camera_x','camera_y','pivot_x','pivot_z'):
            value=float(values.get(key,1. if key.endswith('_sign') else 0.))
            if not math.isfinite(value) or (key.endswith('_sign') and value not in (-1,1)):
                raise ValueError('Enter finite CT placement values and valid axis directions.')
            result[key]=value
        if result['model'] in ('motors','stack'):
            if [row.get('name') for row in result['motors']]!=list(MOTORS):raise ValueError('Incomplete motor registration.')
            for row in result['motors']:
                for key in ('reference','x','y'):
                    row[key]=float(row[key])
                    if not math.isfinite(row[key]):raise ValueError('Motor registration values must be finite.')
                if result['model']=='stack' and row['name'] in ('tomo_xf','tomo_zf'):
                    row['y']=0.
        return result

    def publish_saxs_placement(self):
        m=self._saxs_config['placement']
        self.state.update(**{'saxs_map_'+key:value for key,value in m.items() if key!='reference_source'})
        self.state.saxs_registration_source=m['reference_source']

    def sync_saxs_marks(self):
        if not self._saxs_config:
            return
        m=self._saxs_config['placement']
        grids=[positions(scan,m) for scan in self.saxs_scans]
        self._saxs_positions=grids
        self.state.saxs_axes=[dict(x=x[:scan.index.shape[1]].tolist(),
            x_by_angle=x.reshape(scan.index.shape).tolist(),angle=angles(scan,m).tolist())
            for scan,(x,y) in zip(self.saxs_scans,grids)]
        ys=np.unique(np.concatenate([y for x,y in grids]))
        self.state.saxs_y_marks=[dict(raw=float(y),value=float(y)) for y in ys]
        self.state.saxs_sources=[dict(value=i,label=f'{scan.name} (Y {y[0]:.2f} µm)'+('…' if np.ptp(y)>0 else '')) for i,(scan,(x,y)) in enumerate(zip(self.saxs_scans,grids))]
        maximum=max(float(np.max(np.abs(a))) for grid in grids for a in grid)
        if maximum>self.beam_limit_um:
            self.beam_limit_um=math.ceil(maximum/100)*100
            self.state.beam_limit_um=self.beam_limit_um

    def receive_saxs_selection(self,spec,context=None):
        if context!=self.state.sample_context or not self.saxs_scans or self.state.volume_loading:
            return
        try:
            scan,row,col=(spec[key] for key in ('scan','row','column'))
            if type(scan) is not int or not 0<=scan<len(self.saxs_scans):
                raise ValueError('Select an available SAXS scan.')
            self.saxs_scans[scan].index.frame(row,col)
            placement=self.validate_saxs_placement({**self._saxs_config['placement'],**spec.get('placement',{})})
            changed=placement!=self._saxs_config['placement']
            config={**self._saxs_config,'placement':placement,'link_ct':True}
            self._saxs_config=config
            self.state.update(saxs_link_ct=config['link_ct'])
            if changed:
                self.state.update(saxs_scan=scan,saxs_row=row,saxs_column=col)
                self.publish_saxs_placement()
                self.sync_saxs_marks()
                self._saxs_setting_pose=True
                try:self.update_scene()
                finally:self._saxs_setting_pose=False
            self.request_saxs_frame(scan,row,col)
        except (KeyError,TypeError,ValueError) as error:
            self.state.saxs_error=str(error);self.state.flush()

    def request_saxs_frame(self,scan,row,column,drive_pose=True):
        self._saxs_generation+=1
        self._saxs_requested_selection=(scan,row,column)
        self._saxs_requested_context=self.state.sample_context
        pose=tuple(self.state[key] for key in ('beam_x','beam_y','angle'))
        self._saxs_pending=(self._saxs_generation,self.state.sample_context,scan,row,column,drive_pose,pose)
        self.state.update(saxs_loading=True,saxs_error='')
        if self._saxs_task is None or self._saxs_task.done():
            self._saxs_task=asyncio.create_task(self._read_saxs_frames())

    async def _read_saxs_frames(self):
        while self._saxs_pending:
            generation,context,scan_index,row,column,drive_pose,requested_pose=self._saxs_pending
            self._saxs_pending=None
            scan=self.saxs_scans[scan_index]
            try:
                for other in self.saxs_scans:
                    if other is not scan:
                        other.clear_cache()
                signal=await asyncio.to_thread(scan.read,row,column)
                if generation!=self._saxs_generation or context!=self.state.sample_context:
                    continue
                self.signal=signal;self.signal_kind='measured'
                self.state.update(saxs_scan=scan_index,saxs_row=row,saxs_column=column)
                details=scan.index.details(row,column)
                self._saxs_config['selection']=dict(scan=scan_index,row=row,column=column)
                self.state.update(saxs_frame=details['frame'],saxs_recorded={k:round(details[k],4) for k in ('x_um','y_um','angle')},saxs_y_source=('Y recorded at scan start' if scan.y_origin=='start-position snapshot' else 'Y recorded for each measurement'))
                self.state.saxs_selection_label=f'{scan.name}, frame {details["frame"]}'
                self.state.saxs_frame_info=(f'Frame {details["frame"]} · recorded X {details["x_um"]:.3f} µm · '
                    f'Y {details["y_um"]:.3f} µm ({scan.y_origin}) · rotation {details["angle"]:.4f}°')
                self.state.saxs_flag=' '.join(filter(None,[
                    f'Angle readback differs from the nominal {details["nominal_angle"]:g}° row.' if details['angle_flag'] else '',
                    rotation_warning(scan)]))
                self.update_plots()
                self.state.saxs_revision+=1
                # A newer continuous pose takes precedence even when its nearest
                # measurement is unchanged and therefore needed no second read.
                if drive_pose and requested_pose==tuple(self.state[key] for key in ('beam_x','beam_y','angle')):
                    self.apply_saxs_pose(scan,row,column)
                self.persist_saxs()
            except Exception as error:
                logging.getLogger(__name__).exception('Could not read SAXS measurement')
                if generation==self._saxs_generation and context==self.state.sample_context:
                    self.state.saxs_error=f'{type(error).__name__}: {error}'
                    self._saxs_requested_selection=None
            finally:
                if generation==self._saxs_generation:
                    self.state.saxs_loading=False
                self.state.flush()

    def apply_saxs_pose(self,scan,row,column):
        if not self._saxs_config['link_ct']:
            return
        m=self._saxs_config['placement'];index=scan.index;n=index.frame(row,column)
        x,y=positions(scan,m);x=float(x[n]);y=float(y[n])
        self._saxs_setting_pose=True
        try:
            self.receive_pose(dict(beam_x=float(x),beam_y=float(y),angle=float(angles(scan,m)[row])),True,self.state.sample_context)
            self.state.saxs_pose_revision+=1
        finally:self._saxs_setting_pose=False

    def saxs_from_pose(self):
        if self._saxs_setting_pose or not self.saxs_scans or not self.state.saxs_link_ct:
            return
        m=self._saxs_config['placement']
        choices=[]
        for i,scan in enumerate(self.saxs_scans):
            angle_distance=np.abs((angles(scan,m)-float(self.state.angle)+180)%360-180)
            row=int(np.argmin(angle_distance))
            x,y=self._saxs_positions[i]
            start=row*scan.index.shape[1];stop=start+scan.index.shape[1]
            distance=(x[start:stop]-float(self.state.beam_x))**2+(y[start:stop]-float(self.state.beam_y))**2
            col=int(np.argmin(distance))
            choices.append((float(distance[col]),float(angle_distance[row]),i,row,col))
        _,_,i,row,col=min(choices)
        current=self._saxs_requested_selection
        if (i,row,col)!=current or self._saxs_requested_context!=self.state.sample_context:
            self.request_saxs_frame(i,row,col,drive_pose=False)

    def sample_pose_matrix(self,angle=None):
        return sample_transform(self.state.rotation_axis,
            float(self.state.angle) if angle is None else angle)
