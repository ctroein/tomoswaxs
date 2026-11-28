"""Application controls and dialogs; scientific state and rendering live in app.py."""
from pathlib import Path
import re
import platform
from importlib.metadata import version, PackageNotFoundError
from trame.ui.html import DivLayout
from trame_client.widgets.core import Template
from trame.widgets import html, quasar

from .project_info import NAME, DESCRIPTION, BUILD, LICENSE_NAME, COPYRIGHT, DISPLAY_COPYRIGHT, COLLABORATION
from .workspace import DockWorkspace


class ApplicationUI:
    def sample_menu(self):
        html.Button('Sample',id='sample-menu',classes='project-menu-trigger',
                    raw_attrs=['aria-label="Sample"','aria-haspopup="menu"'])
        with quasar.QMenu(target='#sample-menu',auto_close=True,classes='project-menu'):
            html.Button('Open sample…',id='open-volume',click=self.open_volume_picker,
                        disabled=('volume_loading',),raw_attrs=['role="menuitem"'])
            html.Button('Load SAXS scans…',click=self.open_saxs_picker,
                        disabled=('!has_sample || volume_loading',),raw_attrs=['role="menuitem"'])
            html.Button('Sample settings',click='window.nimCoordinates.pause(); show_sample_settings = true',
                        disabled=('!has_sample || volume_loading',),raw_attrs=['role="menuitem"'])
            html.Button('Manage samples…',click=self.show_samples,
                        disabled=('volume_loading || !project_name',),raw_attrs=['role="menuitem"'])
            quasar.QSeparator(v_if=('sample_choices.length',))
            html.Span('Samples',v_if=('sample_choices.length',),classes='settings-help')
            with html.Button(v_for='item in sample_choices',key=('item.id',),
                             click='sample_choice = item.id',disabled=('volume_loading',),
                             raw_attrs=['role="menuitemradio"',':aria-checked="sample_choice === item.id"',':data-sample-id="item.id"']):
                html.Span('✓',classes='tab-menu-check',raw_attrs=[':style="{visibility: sample_choice === item.id ? \'visible\' : \'hidden\'}"','aria-hidden="true"'])
                html.Span('{{ item.name }}')

    def beamline_menu(self):
        html.Button('Beamline',id='beamline-menu',classes='project-menu-trigger',disabled=('volume_loading',),raw_attrs=['aria-label="Beamline"','aria-haspopup="menu"'])
        ensure_volume="workspace_tabs.includes('volume') || window.nimWorkspace.open('volume');"
        with quasar.QMenu(target='#beamline-menu',classes='project-menu',auto_close=True):
            for level,label in [('sample','Sample'),('area','Sample area'),('station','Whole beamline')]:
                with html.Button(click=ensure_volume+f"window.nimCoordinates.pause(); window.trame.trigger('nim_beamline_level',['{level}'])",
                                 disabled=("volume_loading || (beamline_model_loading && '"+level+"' !== 'sample')",),raw_attrs=['role="menuitemradio"',f':aria-checked="beamline_level === \'{level}\'"']):
                    html.Span('✓',classes='tab-menu-check',raw_attrs=[f':style="{{visibility: beamline_level === \'{level}\' ? \'visible\' : \'hidden\'}}"','aria-hidden="true"'])
                    html.Span(label)
            quasar.QSeparator()
            with html.Button(click='beamline_labels = !beamline_labels',disabled=('!beamline_visible',),
                             raw_attrs=['role="menuitemcheckbox"',':aria-checked="beamline_labels"']):
                html.Span('✓',classes='tab-menu-check',raw_attrs=[':style="{visibility: beamline_labels ? \'visible\' : \'hidden\'}"','aria-hidden="true"'])
                html.Span('Component labels')

    def path_browse_button(self,label,callback):
        with html.Button(classes='path-browse',click=callback,title=label,
                         disabled=('volume_loading',),raw_attrs=[f'aria-label="{label}"']):
            quasar.QIcon(name='folder_open',size='1.4rem',classes='app-icon',raw_attrs=['aria-hidden="true"'])

    def stereo_menu(self):
        html.Button('3D glasses',id='stereo-menu',disabled=('volume_loading || !has_volume',),
                    raw_attrs=['aria-label="3D glasses"','aria-haspopup="dialog"'])
        with quasar.QMenu(target='#stereo-menu',no_refocus=True,classes='stereo-menu'):
            with html.Div(raw_attrs=['role="dialog"','aria-label="3D glasses"']):
                with html.Div(classes='stereo-controls'):
                    with html.Label(classes='stereo-toggle'):
                        html.Input(type='checkbox',v_model=('stereo_enabled',),raw_attrs=['aria-label="Red–cyan 3D glasses"'])
                        html.Span('Red–cyan 3D glasses')
                    with html.Div(classes='stereo-strength'):
                        html.Span('Strength')
                        html.Input(type='range',v_model=('stereo_strength',),min=0,max=5,step=.1,
                                   disabled=('!stereo_enabled',),raw_attrs=['aria-label="Stereo strength slider"'])
                        html.Input(type='number',v_model=('stereo_strength',),min=0,max=5,step=.1,
                                   disabled=('!stereo_enabled',),raw_attrs=['aria-label="Stereo strength"'])
                    with html.Label(classes='stereo-toggle'):
                        html.Input(type='checkbox',v_model=('stereo_swap',),disabled=('!stereo_enabled',),raw_attrs=['aria-label="Swap stereo eyes"'])
                        html.Span('Swap eyes')
                    html.P('Red over the left eye, cyan over the right. Colours are modified in stereo.',classes='settings-help')
                    html.P('{{ stereo_notice }}',v_if=('stereo_notice',),role='alert',classes='picker-error')

    def build_ui(self):
        self.workspace = DockWorkspace(self)
        self.workspace.build_panels()
        with DivLayout(self.server) as layout:
            with html.Div(classes='app-shell'):
                with html.Div(classes='app-header'):
                    html.Strong(NAME,classes='app-name')
                    with html.Div(classes='header-actions'):
                        html.Span('{{ project_name || \"Standalone inspection\" }}',classes='project-name')
                        self.project_menu()
                        self.sample_menu()
                        html.Span('{{ sample_name }}',v_if=('has_sample',),classes='sample-name')
                        with html.Div(classes='header-secondary'):
                            html.Button('View',id='view-menu',classes='project-menu-trigger',raw_attrs=['aria-haspopup="menu"','aria-label="View"'])
                            with quasar.QMenu(target='#view-menu',auto_close=True,classes='project-menu'):
                                html.Span('Tabs',classes='settings-help')
                                for panel,label in [('volume','µCT volume'),('iq','SAXS 1D'),('cake','SAXS cake'),('crop','Crop and resolution'),('saxs','SAXS measurements')]:
                                    with html.Button(click=f"window.nimWorkspace.toggle('{panel}')",raw_attrs=['role="menuitemcheckbox"',f':aria-checked="workspace_tabs.includes(\'{panel}\')"']):
                                        html.Span('✓',classes='tab-menu-check',raw_attrs=[f':style="{{visibility: workspace_tabs.includes(\'{panel}\') ? \'visible\' : \'hidden\'}}"','aria-hidden="true"'])
                                        html.Span(label)
                                quasar.QSeparator()
                                html.Button('Restore default layout',click='window.nimWorkspace.reset()',raw_attrs=['role="menuitem"'])
                                html.Button('Reinitialise rendering',click=self.reinitialise_rendering,
                                            disabled=('volume_loading || render_reinitialising',),raw_attrs=['role="menuitem"'])
                        self.beamline_menu()
                        html.Button('About', click='show_about = true')
                        with html.Button(id='open-settings',classes='settings-icon-button',title='Settings',raw_attrs=['aria-label="Settings"']):
                            quasar.QIcon(name='settings',size='1.25rem')
                with html.Fieldset(classes='controls',disabled=('!has_sample',)):
                    with html.Div():
                        html.Button('Saved views',id='saved-views',classes='project-menu-trigger',disabled=('volume_loading',),raw_attrs=['aria-label="Saved views"','aria-haspopup="menu"'])
                        with quasar.QMenu(target='#saved-views',auto_close=True,classes='project-menu saved-views-menu'):
                            html.Button('{{ item.name }}',v_for='item in saved_view_items',key=('item.id',),
                                        click=(self.recall_saved_view,'[item.id,sample_context]'),raw_attrs=['role="menuitem"'])
                            quasar.QSeparator(v_if=('saved_view_items.length',))
                            html.Button('Save current view…',click=(self.begin_save_view,'[{beam_x:draft_x,beam_y:draft_y,angle:draft_angle},sample_context]'),raw_attrs=['role="menuitem"'])
                            html.Button('Manage saved views…',click=self.manage_saved_views,disabled=('!saved_view_items.length',),raw_attrs=['role="menuitem"'])
                            quasar.QSeparator()
                            html.Button('Default camera',click=self.reset_camera,raw_attrs=['role="menuitem"'])
                    html.Button('Beam view',click='window.nimCoordinates.beamView()',disabled=('volume_loading || !has_volume',))
                    self.stereo_menu()
                    html.Span(classes='toolbar-spacer',raw_attrs=['aria-hidden="true"'])
                    with html.Label(classes='opacity-control'):
                        html.Span('Opacity ')
                        html.Input(type='range',v_model=('opacity',),min=0,max=1,step=.001,raw_attrs=['aria-label="Volume opacity"'],disabled=('volume_loading',))
                    with html.Div(classes='colour-mapping',role='group',aria_label='Colour mapping'):
                        html.Label('Colour mapping',title='Raw intensities mapped to the low and high ends of the colour and opacity range.')
                        html.Input(type='number',v_model=('contrast_low',),step=('contrast_step',),raw_attrs=['aria-label="Colour mapping minimum"'],disabled=('volume_loading || !has_volume',))
                        html.Span('to')
                        html.Input(type='number',v_model=('contrast_high',),step=('contrast_step',),raw_attrs=['aria-label="Colour mapping maximum"'],disabled=('volume_loading || !has_volume',))
                        html.Button('Reset',click=self.reset_contrast,title='Restore the initial colour mapping',aria_label='Reset colour mapping',disabled=('volume_loading || !has_volume',))
                    html.Span(classes='toolbar-spacer',raw_attrs=['aria-hidden="true"'])
                    with html.Div(classes='camera-controls'):
                        html.Label('Camera angle',raw_attrs=['for="camera-angle-number"'])
                        with html.Span(classes='coordinate-number axis-number'):
                            html.Input(type='number',v_model=('draft_camera_angle',),id='camera-angle-number',step='any',
                                disabled=('volume_loading || !has_volume',),raw_attrs=['aria-label="Camera angle (°)"'])
                            html.Span('°',classes='coordinate-unit',raw_attrs=['aria-hidden="true"'])
                        html.Input(type='range',v_model=('draft_camera_angle',),id='camera-angle-range',min=-180,max=180,step=.1,
                            disabled=('volume_loading || !has_volume',),raw_attrs=['aria-label="Camera angle slider"'])
                        with html.Button(id='rotation-toggle',classes='rotation-button',
                                disabled=('volume_loading || !has_volume',),
                                title=("rotation_playing ? 'Pause camera rotation' : 'Play camera rotation'",),
                                raw_attrs=[':aria-label="rotation_playing ? \'Pause\' : \'Play\'"']):
                            quasar.QIcon(name=("rotation_playing ? 'pause' : 'play_arrow'",),raw_attrs=['aria-hidden="true"'])
                        with html.Div(classes='rotation-settings-anchor'):
                            with html.Button(id='rotation-settings',classes='rotation-button',title='Camera rotation settings',disabled=('volume_loading || !has_volume',),raw_attrs=['aria-label="Camera rotation settings"','aria-haspopup="dialog"']):
                                quasar.QIcon(name='tune',size='1.15rem',classes='app-icon',raw_attrs=['aria-hidden="true"'])
                            with quasar.QMenu(v_model=('rotation_settings_open',),target='#rotation-settings',no_refocus=True,classes='rotation-settings'):
                                with html.Div(role='dialog',raw_attrs=['aria-label="Camera rotation settings"']):
                                    html.Strong('Camera rotation')
                                    for field,label,minimum,maximum,step in [('rotation_fps','Updates per second',1,60,1),('rotation_step','Step (°)',.1,180,.1)]:
                                        html.Label(label,raw_attrs=[f'for="{field}"'])
                                        html.Input(type='number',id=field,v_model=(field,),min=minimum,max=maximum,step=step)
                                    html.P("360°: {{ Number(rotation_fps) >= 1 && Number(rotation_fps) <= 60 && Number(rotation_step) >= 0.1 && Number(rotation_step) <= 180 ? (360 / (Number(rotation_fps) * Number(rotation_step))).toFixed(2) + ' s' : '—' }}",classes='settings-help')
                                    html.P('Use 1–60 updates/s and 0.1–180° per update.',v_if=("!(Number(rotation_fps) >= 1 && Number(rotation_fps) <= 60 && Number(rotation_step) >= 0.1 && Number(rotation_step) <= 180)",),role='alert',classes='picker-error')
                                    html.Button('Done',click='rotation_settings_open = false')
                self.workspace.build()
                with html.Div(v_if=('!has_sample && !beamline_visible',),classes='empty-workspace'):
                    html.P("{{ volume_loading ? (project_name ? 'Loading project…' : 'Loading sample…') : 'No sample open. Choose Open sample… to begin.' }}",role='status')
                with html.Div(classes='app-footer'):
                    html.Span('{{ project_error }}',v_if=('project_error',),role='alert',classes='picker-error')
                    html.Span('{{ project_history_notice }}',v_if=('project_history_notice',),role='alert',classes='picker-error')
                    html.Span('{{ saved_view_error }}',v_if=('saved_view_error',),role='alert',classes='picker-error')
                    html.Span('{{ saxs_error }}',v_if=('saxs_error',),raw_attrs=['role="alert"'],classes='picker-error')
                    html.Span('{{ workspace_error }}',v_if=('workspace_error',),role='alert',classes='picker-error')
                    html.Span('{{ render_reinitialise_error }}',v_if=('render_reinitialise_error',),role='alert',classes='picker-error')
                    html.Span('Reinitialising rendering…',v_if=('render_reinitialising',),role='status')
                    html.Span('{{ status }}')
                with quasar.QDialog(v_model=('show_beamline_download',),persistent=True):
                    with quasar.QCard(classes='project-card',raw_attrs=['role="dialog"','aria-labelledby="beamline-download-title"']):
                        with quasar.QCardSection():
                            html.H2('ForMAX model',id='beamline-download-title')
                            html.P('{{ beamline_download_message }}',v_if=('beamline_model_loading',),role='status')
                            html.Progress(value=('beamline_download_percent',),max=100,v_if=('beamline_model_loading',),
                                          style='width:100%',aria_label='ForMAX model progress')
                            html.Span('{{ beamline_download_percent }}%',v_if=('beamline_model_loading',))
                            html.P('{{ beamline_download_error }}',v_if=('beamline_download_error',),role='alert',classes='picker-error')
                        with quasar.QCardActions(align='right'):
                            html.Button('Cancel',v_if=('beamline_model_loading',),click=self.cancel_beamline_download)
                            html.Button('Close',v_else=True,click='show_beamline_download = false')
                            html.Button('Retry',v_if=('!beamline_model_loading && beamline_download_error',),click=self.retry_beamline_download)
                with quasar.QDialog(v_model=('show_project_open_error',)):
                    with quasar.QCard(classes='project-card',raw_attrs=['role="alertdialog"','aria-labelledby="project-open-error-title"','aria-describedby="project-open-error-message"']):
                        with quasar.QCardSection():
                            html.H2('Project opening failed',id='project-open-error-title')
                            html.P('{{ project_open_error }}',id='project-open-error-message')
                        with quasar.QCardActions(align='right'):
                            html.Button('Close',click='show_project_open_error = false')
                with quasar.QDialog(v_model=('show_saved_view_dialog',)):
                    with quasar.QCard(classes='saved-view-card',raw_attrs=['role="dialog"','aria-labelledby="saved-view-title"']):
                        with quasar.QCardSection():
                            html.H2("{{ saved_view_mode === 'save' ? 'Save current view' : saved_view_mode === 'rename' ? 'Rename saved view' : 'Saved views' }}",id='saved-view-title')
                            with html.Div(v_if=("saved_view_mode !== 'manage'",)):
                                html.Label('Name',raw_attrs=['for="saved-view-name"'])
                                html.Input(id='saved-view-name',type='text',v_model=('saved_view_name',),
                                           keydown_enter=self.commit_saved_view,__events=[('keydown_enter','keydown.enter.prevent')])
                            with html.Div(v_else=True):
                                with html.Div(v_for='item in saved_view_items',key=('item.id',),classes='saved-view-row'):
                                    html.Span('{{ item.name }}')
                                    html.Button('Rename',click=(self.begin_rename_saved_view,'[item.id,sample_context]'),raw_attrs=[':aria-label="\'Rename \' + item.name"'])
                                    html.Button('Delete',click=(self.delete_saved_view,'[item.id,sample_context]'),raw_attrs=[':aria-label="\'Delete \' + item.name"'])
                            html.P('{{ saved_view_error }}',v_if=('saved_view_error',),role='alert',classes='picker-error')
                        with quasar.QCardActions(align='right'):
                            html.Button("{{ saved_view_mode === 'manage' ? 'Close' : 'Cancel' }}",click=self.cancel_saved_view_dialog)
                            html.Button('Save',v_if=("saved_view_mode !== 'manage'",),click=self.commit_saved_view,disabled=('volume_loading',))
                self.project_dialog()
                self.samples_dialog()
                with quasar.QDialog(model_value=('show_sample_settings',),update_model_value=(self.close_sample_settings,'[$event]')):
                    with quasar.QCard(classes='sample-settings-card',raw_attrs=['role="dialog"','aria-labelledby="sample-settings-title"']):
                        with quasar.QCardSection():
                            html.H2('Sample settings',id='sample-settings-title')
                            html.P('{{ data_notice }}',classes='settings-help')
                            html.P('{{ volume_summary }}',classes='settings-help')
                            with html.Details(v_if=('sample_sources.length',)):
                                html.Summary('Data sources')
                                with html.Div(v_for='source in sample_sources',key=('source.path',),classes='sample-data-source'):
                                    html.Strong('{{ source.label }}')
                                    html.Div('{{ source.path }}')
                            with html.Div(v_if=('sample_choice',)):
                                html.Label('Sample name',raw_attrs=['for=\"sample-name\"'])
                                html.Input(id='sample-name',v_model=('sample_name_draft',),disabled=('volume_loading',))
                                html.Button('Rename sample',click=self.rename_sample,disabled=('volume_loading',))
                            with html.Div(v_if=('sample_pixel_size_editable',)):
                                html.H3('Pixel size (µm)')
                                html.P('User-supplied pixel size from import. Changes are saved to OME-Zarr when this dialog closes.',classes='settings-help')
                                with html.Label(classes='sample-spacing-link'):
                                    html.Input(type='checkbox',v_model=('sample_voxel_linked',),change="window.nimPixelSizes.begin('sample')")
                                    html.Span('Preserve XYZ ratio')
                                with html.Div(classes='sample-spacing-fields'):
                                    for axis in 'xyz':
                                        with html.Span(classes='axis-number'):
                                            html.Span(axis.upper(),classes='axis-prefix',raw_attrs=['aria-hidden="true"'])
                                            html.Input(type='number',v_model=(f'sample_voxel_{axis}',),step=1,min=0,
                                                       raw_attrs=[f'aria-label="Sample pixel size {axis.upper()} (µm)"'],
                                                       focus="window.nimPixelSizes.begin('sample')",
                                                       input=f"window.nimPixelSizes.change('sample','{axis}',$event.target.value)",
                                                       disabled=('volume_loading',))
                            html.H3('Axis assignment')
                            with html.Label():
                                html.Span('File direction for sample Y ')
                                with html.Select(v_model=('rotation_axis',),aria_label='File direction for sample Y',disabled=('volume_loading',)):
                                    for axis,direction in [('x','columns'),('y','rows'),('z','stack')]:
                                        html.Option(f'{axis.upper()} (TIFF {direction})',value=axis)
                            html.P('Choose the file direction that represents sample Y.',classes='settings-help')
                            html.P('{{ sample_settings_notice }}',v_if=('sample_settings_notice',),role='status',classes='picker-error')
                        with quasar.QCardActions(align='right'):
                            html.Button('Close',click=self.close_sample_settings)
                with quasar.QDialog(v_model=('show_about',)):
                    with quasar.QCard(dark=True, classes='about-card', raw_attrs=['role="dialog"', 'aria-modal="true"', 'aria-labelledby="about-title"']):
                        with quasar.QCardSection():
                            html.H2(NAME, id='about-title')
                            html.P(DESCRIPTION)
                            with html.P(classes='about-muted'):
                                html.A(f'Version {BUILD}',href='https://github.com/ctroein/tomoswaxs',target='_blank',rel='noopener noreferrer')
                            html.P(COLLABORATION)
                            with html.Div(classes='infrastructure-links'):
                                for label,url,image in [('InfraVis','https://infravis.se/','infravis.svg'),
                                                        ('MAX IV','https://www.maxiv.lu.se/','maxiv.png'),
                                                        ('NAISS','https://www.naiss.se/','naiss.png')]:
                                    with html.A(href=url, target='_blank', rel='noopener noreferrer', title=label,aria_label=label,
                                                classes='maxiv-logo-link' if label == 'MAX IV' else ''):
                                        if label == 'MAX IV':
                                            html.Span('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 314" overflow="hidden"><image href="/nim-assets/logos/maxiv.png" width="1024" height="421"/></svg>',classes='infrastructure-logo',raw_attrs=['aria-hidden="true"'])
                                        elif image.endswith('.svg'):
                                            logo = (Path(__file__).parent/'assets/logos'/image).read_text()
                                            logo = re.sub(r'<style>.*?</style>', '', logo[logo.index('<svg'):], flags=re.S)
                                            logo = logo.replace('class="cls-2"', 'fill="currentColor"').replace('class="cls-1"', 'fill="url(#gradient-rainbow_2_copy)"')
                                            html.Span(logo,classes='infrastructure-logo',raw_attrs=['aria-hidden="true"'])
                                        else:
                                            html.Span(classes='infrastructure-logo monochrome-logo',style=f'mask-image:url(/nim-assets/logos/{image});-webkit-mask-image:url(/nim-assets/logos/{image})',raw_attrs=['aria-hidden="true"'])
                            if COPYRIGHT:
                                html.P(DISPLAY_COPYRIGHT, classes='about-muted')
                            licence_file = Path(__file__).with_name('LICENSE')
                            if not licence_file.exists():
                                licence_file = Path(__file__).parents[2] / 'LICENSE'
                            if licence_file.exists():
                                with html.Details():
                                    html.Summary(LICENSE_NAME)
                                    html.Pre(licence_file.read_text(), classes='licence-text')
                            html.H3('Built with')
                            with html.Div(classes='dependency-versions'):
                                for label,package,url in [
                                        ('Python',None,'https://www.python.org/'),
                                        ('Dask','dask','https://www.dask.org/'),
                                        ('zarrista','zarrista','https://pypi.org/project/zarrista/'),
                                        ('obstore','obstore','https://pypi.org/project/obstore/'),
                                        ('trame-client','trame-client','https://github.com/Kitware/trame-client'),
                                        ('trame-server','trame-server','https://github.com/Kitware/trame-server'),
                                        ('Trame','trame','https://kitware.github.io/trame/'),
                                        ('VTK','vtk','https://vtk.org/'),
                                        ('trame-vtk','trame-vtk','https://github.com/Kitware/trame-vtk'),
                                        ('trame-quasar','trame-quasar','https://github.com/Kitware/trame-quasar'),
                                        ('trame-dockview','trame-dockview','https://github.com/Kitware/trame-dockview'),
                                        ('Plotly','plotly','https://plotly.com/python/'),
                                        ('trame-plotly','trame-plotly','https://github.com/Kitware/trame-plotly'),
                                        ('NumPy','numpy','https://numpy.org/'),
                                        ('h5py','h5py','https://www.h5py.org/'),
                                        ('tifffile','tifffile','https://github.com/cgohlke/tifffile'),
                                        ('ngff-zarr','ngff-zarr','https://ngff-zarr.readthedocs.io/')]:
                                    try:
                                        installed = version(package) if package else platform.python_version()
                                    except PackageNotFoundError:
                                        installed = 'unknown'
                                    with html.Div(classes='dependency-item'):
                                        html.A(label, href=url, target='_blank', rel='noopener noreferrer')
                                        html.Span(installed)
                            html.P('Dependencies retain their own licences.', classes='about-muted')
                        with quasar.QCardActions(align='right'):
                            html.Button('Close', click='show_about = false')
                with quasar.QDialog(v_model=('show_volume_picker',), persistent=('volume_loading',), no_backdrop_dismiss=True,
                                    escape_key=self.cancel_volume_load,position='top'):
                    with quasar.QCard(classes=("{'volume-picker': true, 'url-picker': volume_url_mode && (picker_mode === 'volume' || picker_mode === 'relink')}",), raw_attrs=['role="dialog"', 'aria-labelledby="volume-picker-title"']):
                        with quasar.QCardSection(classes='picker-body'):
                            html.H2('{{ picker_mode === \"project_directory\" ? directory_picker_title : picker_mode === \"project\" ? \"Open project\" : picker_mode === \"saxs\" ? \"Load SAXS scans\" : picker_mode === \"relink\" ? \"Locate CT image\" : \"Open sample\" }}', id='volume-picker-title')
                            with html.Div(v_if=("picker_mode === 'relink'",),classes='settings-help'):
                                html.P('Sample: {{ relink_sample_name }}')
                                html.P('Stored CT image: {{ relink_ct_path }}')
                            with html.Div(v_if=("picker_mode === 'volume' || picker_mode === 'relink'",),classes='picker-source-kind',role='group',aria_label='Sample source'):
                                html.Span('Source')
                                for label,value in [('Files','false'),('URL','true')]:
                                    with html.Label():
                                        html.Input(type='radio',name='sample-source-kind',checked=(('volume_url_mode' if value=='true' else '!volume_url_mode'),),
                                                   change=f"volume_url_mode = {value}; volume_error = ''",disabled=('volume_loading',),raw_attrs=[f'aria-label="{label}"'])
                                        html.Span(label)
                            with html.Div(v_if=("volume_url_mode && (picker_mode === 'volume' || picker_mode === 'relink')",),classes='picker-url-field'):
                                html.Label('OME-Zarr URL',raw_attrs=['for="volume-url"'])
                                html.Input(id='volume-url',type='url',v_model=('volume_url',),disabled=('volume_loading',),
                                           keydown_enter=self.open_selected_volume,__events=[('keydown_enter','keydown.enter.prevent')])
                            with html.Div(v_show=("!(volume_url_mode && (picker_mode === 'volume' || picker_mode === 'relink'))",),classes='picker-local-fields'):
                                with html.Div(classes='picker-navigation'):
                                    html.Label('Folder',raw_attrs=['for="volume-directory"'])
                                    html.Input(id='volume-directory',type='text',v_model=('volume_directory',),disabled=('volume_loading',),
                                        keydown_enter=self.list_volume_directory,__events=[('keydown_enter','keydown.enter.prevent')])
                                    with html.Button(click=self.parent_volume_directory,title='Parent directory',disabled=('volume_loading',),raw_attrs=['aria-label="Parent directory"']):
                                        quasar.QIcon(name='arrow_upward',size='1.1rem')
                                    with html.Button(click=self.list_volume_directory,title='Refresh',disabled=('volume_loading',),raw_attrs=['aria-label="Refresh"']):
                                        quasar.QIcon(name='refresh',size='1.1rem')
                                with quasar.QTable(id='volume-files',classes='file-table',
                                                   no_data_label=("picker_mode === 'project_directory' ? 'No subdirectories' : 'No files match the selected filters'",),
                                                   rows=('volume_entries',),row_key='path',
                                                   columns=('file_columns', [dict(name='name',label='Name',field='name',align='left',sortable=True),
                                                            dict(name='size',label='Size',field='size',align='right',sortable=True),
                                                            dict(name='modified',label='Modified',field='modified',align='left',sortable=True)]),
                                                   pagination=("{rowsPerPage:0,sortBy:'name',descending:false}",),
                                                   hide_bottom=True,dense=True,flat=True,
                                                   raw_attrs=['aria-label="Files and directories"']):
                                    with Template(raw_attrs=['#body="props"']):
                                        with html.Tr(click='!volume_loading && (volume_selection = props.row.path)',
                                                        dblclick=(self.open_selected_volume, "[props.row.path, true]"),
                                                        keydown_space='!volume_loading && (volume_selection = props.row.path)',
                                                        keydown_enter=(self.open_selected_volume, "[props.row.path, true]"),
                                                        __events=[('keydown_space','keydown.space.prevent'),('keydown_enter','keydown.enter.prevent')],
                                                        raw_attrs=['tabindex="0"', ':data-path="props.row.path"',
                                                                   ':aria-selected="volume_selection === props.row.path"'],
                                                        classes=("{ 'file-selected': volume_selection === props.row.path }",)):
                                            with html.Td():
                                                html.Span('{{ props.row.name }}',title=('props.row.name',))
                                            html.Td('{{ props.row.size_display }}',classes='text-right')
                                            html.Td('{{ props.row.modified_display }}')
                                with html.Div(classes='file-details',id='volume-file-details',
                                              v_for='entry in volume_entries.filter(entry => entry.path === volume_selection)',key=('entry.path',)):
                                    html.Strong('{{ entry.name }}',title=('entry.path',))
                                    html.Span('{{ entry.kind }}{{ entry.size_detail ? " · " + entry.size_detail : "" }}')
                                with html.Div(classes='picker-filter',v_if=("picker_mode !== 'project_directory'",)):
                                    html.Label('Filter',raw_attrs=['for="volume-filter"'])
                                    with html.Select(id='volume-filter',value=('volume_filter_choice',),change=(self.choose_volume_filter,'[$event.target.value]'),disabled=('volume_loading',)):
                                        html.Option('{{ item.label }}',v_for='item in volume_filter_options',value=('item.value',),key=('item.value',))
                                    html.Input(id='volume-name-filter',type='text',v_model=('volume_name_filter',),v_if=("volume_filter_choice === 'custom'",),
                                        title='Filename pattern; separate multiple patterns with semicolons.',raw_attrs=['aria-label="Custom filename pattern"'],disabled=('volume_loading',))
                                with html.Div(classes='picker-import-options',v_if=("picker_mode === 'volume' && /\\.(?:tiff?|h5|hdf5)$/i.test(volume_selection) && volume_prepared_path === volume_selection",)):
                                    with html.Div(v_if=('project_name',),classes='import-row'):
                                        html.Label('Destination',raw_attrs=['for="import-destination-mode"'])
                                        with html.Select(id='import-destination-mode',v_model=('volume_import_mode',),disabled=('volume_loading',)):
                                            html.Option('In project',value='project')
                                            html.Option('External destination',value='external')
                                    html.Button('Create new project',v_if=('!project_name',),click=self.show_new_project_for_tiff,disabled=('volume_loading',),classes='import-project-action')
                                    with html.Div(v_if=("/\\.(h5|hdf5)$/i.test(volume_selection)",),classes='import-hdf-fields'):
                                        html.Label('Dataset',raw_attrs=['for="hdf5-dataset"'])
                                        with html.Select(id='hdf5-dataset',v_model=('volume_hdf5_dataset',),disabled=('volume_loading',)):
                                            html.Option('{{ item.label }}',v_for='item in volume_hdf5_datasets',value=('item.value',),key=('item.value',))
                                        html.Label('Dimension order',raw_attrs=['for="hdf5-axes"'])
                                        with html.Select(id='hdf5-axes',v_model=('volume_hdf5_axes',),disabled=('volume_loading',)):
                                            for axes in ('zyx','zxy','yxz','yzx','xyz','xzy'):
                                                html.Option(axes.upper(),value=axes)
                                    html.Label('OME-Zarr output',raw_attrs=['for="volume-destination"'])
                                    with html.Div(classes='path-field'):
                                        html.Input(id='volume-destination',type='text',v_model=('volume_destination',),disabled=("volume_loading || volume_import_mode === 'project'",))
                                        with html.Span(v_if=("volume_import_mode !== 'project'",)):
                                            self.path_browse_button('Choose conversion directory',self.browse_import_destination)
                                    html.Span('Pixel size (µm)',classes='import-pixel-label')
                                    with html.Div(classes='import-pixel-controls'):
                                        with html.Div(classes='sample-spacing-fields'):
                                            for axis in 'xyz':
                                                with html.Span(classes='axis-number'):
                                                    html.Span(axis.upper(),classes='axis-prefix',raw_attrs=['aria-hidden="true"'])
                                                    html.Input(type='number',v_model=(f'volume_voxel_{axis}',),step=1,min=0,
                                                               focus="window.nimPixelSizes.begin('volume')",
                                                               input=f"window.nimPixelSizes.change('volume','{axis}',$event.target.value)",
                                                               raw_attrs=[f'aria-label="Pixel size {axis.upper()} (µm)"'],disabled=('volume_loading',))
                                        with html.Label(classes='import-ratio'):
                                            html.Input(type='checkbox',v_model=('volume_voxel_linked',),change="window.nimPixelSizes.begin('volume')",disabled=('volume_loading',))
                                            html.Span('Preserve XYZ ratio')
                                with html.Div(classes='picker-new-folder',v_if=("picker_mode === 'project_directory'",)):
                                    html.Label('New folder name',raw_attrs=['for="project-new-folder"'])
                                    html.Input(id='project-new-folder',type='text',v_model=('project_new_folder',))
                                    html.Button('Create folder',click=self.create_project_folder)
                            with html.Label(v_if=("picker_mode === 'volume' || picker_mode === 'relink'",)):
                                html.Span('Voxel array size limit (MiB) ',title='Maximum size of the voxel array loaded into RAM for volume rendering.')
                                html.Input(type='number',v_model=('volume_preview_mib',),min=1,step=16,disabled=('volume_loading',))
                            html.P('{{ volume_error }}',v_if=('volume_error',),classes='picker-error',raw_attrs=['role="alert"'])
                            html.P('{{ volume_progress }}',v_if=('volume_loading',),role='status')
                        with quasar.QCardActions(align='right'):
                            html.Button('Cancel',click=self.cancel_volume_load)
                            html.Button('Load scans in this directory',v_if=("picker_mode === 'saxs'",),click=self.use_saxs_directory,disabled=('saxs_loading',))
                            html.Button('Use this directory',v_if=("picker_mode === 'project_directory'",),click=self.finish_project_directory)
                            html.Button('{{ picker_mode === \"project_directory\" ? \"Open folder\" : picker_mode === \"relink\" ? \"Use this CT image\" : \"Open\" }}',click=self.open_selected_volume,disabled=("volume_loading || (picker_mode === 'project_directory' && !volume_selection) || (picker_mode === 'volume' && !volume_url_mode && /\\.(?:tiff?|h5|hdf5)$/i.test(volume_selection) && volume_prepared_path !== volume_selection)",))
        self.layout = layout
