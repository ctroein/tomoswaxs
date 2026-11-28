"""Project sample membership and the Samples dialog."""
import asyncio
import logging

from trame.widgets import html, quasar


class SampleManagement:
    def sync_sample_manager(self):
        rows=[]
        for sample in self.project.document['samples'] if self.project else []:
            datasets=sample['datasets']
            ct=datasets.get('ct',{})
            scattering=datasets.get('scattering',{})
            rows.append(dict(id=sample['id'],name=sample['name'],
                             ct='No CT image' if ct.get('kind') in ('synthetic','none') else ct.get('url',ct.get('path','')),
                             scattering=('Not loaded' if scattering.get('kind') in ('synthetic','none') else
                                         f"{len(scattering.get('scans',[]))} integrated SAXS scans" if scattering.get('kind')=='formax-integrated' else
                                         scattering.get('path','Not specified')),
                             active=sample['id']==self.active_sample_id))
        sources=[]
        if self.volume_source is not None:
            sources.append(dict(label='CT',path=str(self.volume_source.path)))
        for scan in getattr(self,'saxs_scans',[]):
            sources.append(dict(label=scan.name,path=str(scan.path)))
            sources.append(dict(label=f'{scan.name} motor metadata',path=str(scan.metadata)))
        self.state.sample_sources=sources
        self.state.project_samples=rows
        selected=next((row for row in rows if row['id']==self.state.managed_sample_choice),None)
        if selected is None:
            selected=next((row for row in rows if row['active']),rows[0] if rows else None)
        self.state.update(managed_sample_choice=selected['id'] if selected else '',
                          managed_sample_name=selected['name'] if selected else '')

    def show_samples(self):
        if not self.project or self.state.volume_loading:
            return
        self.state.sample_manager_error=''
        self.state.managed_sample_choice=self.active_sample_id or ''
        self.sync_sample_manager()
        self.server.clear_state_client_cache('show_samples')
        self.state.show_samples=True
        self.state.dirty('show_samples')

    def select_managed_sample(self,identifier):
        if not self.project or self.state.volume_loading:
            return
        sample=self.project.sample(identifier)
        self.state.update(managed_sample_choice=identifier,managed_sample_name=sample['name'],sample_manager_error='')

    def open_managed_sample(self,identifier=None):
        if self.project and not self.state.volume_loading and self.state.managed_sample_choice:
            self._volume_task=asyncio.create_task(self._open_managed_sample(identifier or self.state.managed_sample_choice))

    async def _open_managed_sample(self,identifier):
        try:
            if identifier!=self.active_sample_id:
                await self.activate_sample(identifier)
                self.state.sample_manager_error=self.state.project_error or self.state.volume_error
            else:
                self.state.sample_manager_error=''
            if self.active_sample_id==identifier and not self.state.sample_manager_error:
                self.state.show_samples=False
        except Exception as error:
            logging.getLogger(__name__).exception('Could not open project sample %s',identifier)
            self.state.sample_manager_error=str(error) or type(error).__name__
        finally:
            self.state.flush()

    def rename_managed_sample(self):
        if not self.project or self.state.volume_loading or not self.state.managed_sample_choice:
            return
        try:
            self.project.update_sample(self.state.managed_sample_choice,name=self.state.managed_sample_name.strip())
            self.sync_project()
            self.state.sample_manager_error=''
        except (OSError,ValueError,StopIteration) as error:
            self.state.sample_manager_error=str(error)

    def remove_managed_sample(self,identifier=None):
        if self.project and not self.state.volume_loading and self.state.managed_sample_choice:
            self._volume_task=asyncio.create_task(self._remove_managed_sample(identifier or self.state.managed_sample_choice))

    async def _remove_managed_sample(self,identifier=None):
        project=self.project
        identifier=identifier or self.state.managed_sample_choice
        try:
            if not project or not self.persist_active():
                self.state.sample_manager_error=self.state.project_error
                return
            project.sample(identifier)
            if identifier==self.active_sample_id:
                replacement=next((sample['id'] for sample in project.document['samples'] if sample['id']!=identifier),None)
                if replacement:
                    await self.activate_sample(replacement)
                    if self.project is not project or self.active_sample_id!=replacement or self.state.project_error:
                        self.state.sample_manager_error=self.state.project_error or 'Could not open the replacement sample.'
                        return
            project.remove_sample(identifier)
            if not project.document['samples']:
                self.clear_sample()
            self.sync_project()
            self.state.sample_manager_error=''
        except Exception as error:
            logging.getLogger(__name__).exception('Could not remove project sample %s',identifier)
            self.state.sample_manager_error=str(error) or type(error).__name__
            self.sync_project()
        finally:
            self.state.flush()

    def samples_dialog(self):
        with quasar.QDialog(v_model=('show_samples',)):
            with quasar.QCard(classes='samples-card',raw_attrs=['role="dialog"','aria-labelledby="samples-title"']):
                with quasar.QCardSection():
                    html.H2('Samples',id='samples-title')
                    html.P('No samples in this project.',v_if=('!project_samples.length',))
                    with html.Div(classes='samples-table-scroll'):
                        with html.Table(id='project-samples'):
                            with html.Thead():
                                with html.Tr():
                                    for label in ('Name','CT data','Scattering data','Active'):
                                        html.Th(label,scope='col')
                            with html.Tbody():
                                with html.Tr(v_for='item in project_samples',key=('item.id',),
                                             click="!volume_loading && (managed_sample_choice = item.id, managed_sample_name = item.name, sample_manager_error = '')",
                                             keydown_enter="!volume_loading && (managed_sample_choice = item.id, managed_sample_name = item.name, sample_manager_error = '')",
                                             __events=[('keydown_enter','keydown.enter.prevent')],
                                             raw_attrs=['tabindex="0"',':aria-selected="managed_sample_choice === item.id"',':data-sample-id="item.id"'],
                                             classes=("{'file-selected': managed_sample_choice === item.id}",)):
                                    html.Td('{{ item.name }}')
                                    html.Td('{{ item.ct }}',classes='sample-source')
                                    html.Td('{{ item.scattering }}',classes='sample-source')
                                    html.Td('{{ item.active ? "✓" : "" }}')
                    html.Label('Sample name',raw_attrs=['for="managed-sample-name"'])
                    html.Input(id='managed-sample-name',v_model=('managed_sample_name',),disabled=('volume_loading || !managed_sample_choice',))
                    with html.Div(classes='sample-management-actions'):
                        html.Button('Show sample',click=(self.open_managed_sample,'[managed_sample_choice]'),disabled=('volume_loading || !managed_sample_choice',))
                        html.Button('Rename',click=self.rename_managed_sample,disabled=('volume_loading || !managed_sample_choice',))
                        html.Button('Remove from project',click=(self.remove_managed_sample,'[managed_sample_choice]'),disabled=('volume_loading || !managed_sample_choice',),
                                    title='Remove this sample’s project entry and saved settings; keep its data files.')
                    html.P('{{ volume_progress }}',v_if=('volume_loading',),raw_attrs=['role="status"'])
                    html.Button('Cancel loading',v_if=('volume_loading',),click=self.cancel_volume_load)
                    html.P('{{ sample_manager_error }}',v_if=('sample_manager_error',),classes='picker-error',raw_attrs=['role="alert"'])
                with quasar.QCardActions(align='right'):
                    html.Button('Close',click='show_samples = false')
