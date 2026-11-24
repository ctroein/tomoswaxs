"""Named per-sample position and camera bookmarks."""
from copy import deepcopy
from pathlib import Path
import uuid

from .projects import SAVED_VIEW_FIELDS, validate_saved_views


class SavedViews:
    def init_saved_views(self):
        self._standalone_views={}
        self._saved_view_draft=None
        self._saved_view_context=None
        self.state.update(saved_view_items=[],saved_view_error='',show_saved_view_dialog=False,
                          saved_view_mode='manage',saved_view_name='',saved_view_edit_id='')
        self.state.client_only('show_saved_view_dialog')

    def standalone_saved_views(self,path):
        key=str(Path(path).resolve()) if path is not None else '<synthetic>'
        return deepcopy(self._standalone_views.get(key,[]))

    def current_saved_views(self):
        if not self.state.has_sample:
            return []
        if self.project and self.active_sample_id:
            return self.project.sample(self.active_sample_id).get('saved_views',[])
        return self.standalone_saved_views(self.volume_source.path if self.volume_source else None)

    def cache_current_saved_views(self):
        key=str(self.volume_source.path) if self.volume_source else '<synthetic>'
        self._standalone_views[key]=self.current_saved_views()

    def sync_saved_views(self):
        scope=(str(self.project.path),self.active_sample_id) if self.project and self.active_sample_id else (None,str(self.volume_source.path) if self.volume_source else '<synthetic>')
        if getattr(self,'_saved_view_scope',None)!=scope:
            self._saved_view_scope=scope
            self._saved_view_draft=None
            self._saved_view_context=None
            self.state.saved_view_error=''
            self.saved_view_dialog_visibility(False)
        self.state.saved_view_items=[dict(id=item['id'],name=item['name']) for item in self.current_saved_views()]

    def write_saved_views(self,views):
        validate_saved_views(views)
        if self.project and self.active_sample_id:
            self.project.update_sample(self.active_sample_id,saved_views=views)
        else:
            key=str(self.volume_source.path) if self.volume_source else '<synthetic>'
            self._standalone_views[key]=deepcopy(views)
        self.state.saved_view_error=''
        self.sync_saved_views()

    def saved_view_dialog_visibility(self,visible):
        self.server.clear_state_client_cache('show_saved_view_dialog')
        self.state.show_saved_view_dialog=visible
        self.state.dirty('show_saved_view_dialog')

    def check_saved_view_context(self,context):
        if self.state.volume_loading:
            raise ValueError('Wait for the sample to finish loading.')
        if context is not None and context!=self.state.sample_context:
            raise ValueError('The active sample changed; choose the view again.')

    def begin_save_view(self,pose=None,context=None):
        try:
            self.check_saved_view_context(context)
            captured=self.capture_view()
            view={key:deepcopy(captured[key]) for key in SAVED_VIEW_FIELDS}
            if pose is not None:
                for field in ('beam_x','beam_y','angle'):
                    if pose[field] in ('',None):
                        raise ValueError('Finish editing position and angle before saving a view.')
                    view[field]=float(pose[field])
                view['angle']=self.wrap_angle(view['angle'])
            validate_saved_views([dict(id='draft',name='draft',view=view)])
            if any(abs(view[field])>self.beam_limit_um for field in ('beam_x','beam_y')):
                raise ValueError('Position is outside this sample’s current limits.')
            self._saved_view_draft=view
            self._saved_view_context=self.state.sample_context
            self.state.update(saved_view_mode='save',saved_view_name='',saved_view_edit_id='',saved_view_error='')
            self.saved_view_dialog_visibility(True)
        except (OSError,ValueError,KeyError,TypeError) as error:
            self.state.saved_view_error=str(error)
        finally:
            self.state.flush()

    def manage_saved_views(self):
        self._saved_view_draft=None
        self._saved_view_context=self.state.sample_context
        self.state.update(saved_view_mode='manage',saved_view_error='')
        self.sync_saved_views()
        self.saved_view_dialog_visibility(True)
        self.state.flush()

    def begin_rename_saved_view(self,identifier,context=None):
        try:
            self.check_saved_view_context(context)
            item=next(item for item in self.current_saved_views() if item['id']==identifier)
            self._saved_view_context=self.state.sample_context
            self.state.update(saved_view_mode='rename',saved_view_name=item['name'],saved_view_edit_id=identifier,saved_view_error='')
            self.saved_view_dialog_visibility(True)
        except (ValueError,StopIteration) as error:
            self.state.saved_view_error=str(error) or 'This saved view is no longer available.'
        finally:
            self.state.flush()

    def commit_saved_view(self):
        try:
            self.check_saved_view_context(self._saved_view_context)
            views=self.current_saved_views()
            if self.state.saved_view_mode=='save' and self._saved_view_draft is not None:
                views.append(dict(id=uuid.uuid4().hex,name=self.state.saved_view_name.strip(),view=deepcopy(self._saved_view_draft)))
            elif self.state.saved_view_mode=='rename':
                item=next(item for item in views if item['id']==self.state.saved_view_edit_id)
                item['name']=self.state.saved_view_name.strip()
            else:
                return
            self.write_saved_views(views)
            if self.state.saved_view_mode=='rename':
                self.state.saved_view_mode='manage'
            else:
                self.cancel_saved_view_dialog()
        except (OSError,ValueError,StopIteration) as error:
            self.state.saved_view_error=str(error) or 'This saved view is no longer available.'
        finally:
            self.state.flush()

    def cancel_saved_view_dialog(self):
        self._saved_view_draft=None
        self.state.saved_view_error=''
        self.saved_view_dialog_visibility(False)
        self.state.flush()

    def delete_saved_view(self,identifier,context=None):
        try:
            self.check_saved_view_context(context)
            self.write_saved_views([item for item in self.current_saved_views() if item['id']!=identifier])
        except (OSError,ValueError) as error:
            self.state.saved_view_error=str(error)
        finally:
            self.state.flush()

    def recall_saved_view(self,identifier,context=None):
        try:
            self.check_saved_view_context(context)
            item=next(item for item in self.current_saved_views() if item['id']==identifier)
            validate_saved_views([item])
            view=item['view']
            if any(abs(view[field])>self.beam_limit_um for field in ('beam_x','beam_y')):
                raise ValueError('Saved position is outside this sample’s current limits.')
            self._applying_pose=True
            try:
                # Cancel queued input from the old pose before publishing the new one.
                self.state.sample_context=uuid.uuid4().hex
                self.dragging_beam=self.dragging_controls=False
                self.restore_view(view)
            finally:
                self._applying_pose=False
            self.state.saved_view_error=''
            self.update_scene()
            self.persist_active()
        except (OSError,ValueError,StopIteration) as error:
            self.state.saved_view_error=str(error) or 'This saved view is no longer available.'
        finally:
            self.state.flush()
