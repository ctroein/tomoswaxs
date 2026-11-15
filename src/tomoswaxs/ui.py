"""Application controls and dialogs; scientific state and rendering live in app.py."""
from pathlib import Path
import re
from importlib.metadata import version, PackageNotFoundError
from trame.ui.html import DivLayout
from trame_client.widgets.core import Template
from trame.widgets import html, quasar

from .project_info import NAME, DESCRIPTION, BUILD, LICENSE_NAME, COPYRIGHT, COLLABORATION
from .workspace import DockWorkspace


class ApplicationUI:
    def path_browse_button(self,label,callback):
        with html.Button(classes='path-browse',click=callback,title=label,
                         disabled=('volume_loading',),raw_attrs=[f'aria-label="{label}"']):
            self.svg_icon('folder-open.svg')

    def svg_icon(self,name):
        return html.Span((Path(__file__).parent/'assets/icons'/name).read_text(),
                         classes='app-icon',raw_attrs=['aria-hidden="true"'])

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
                        with html.Div():
                            html.Button('Tabs',id='view-menu',classes='project-menu-trigger',raw_attrs=['aria-haspopup="menu"','aria-label="Tabs"'])
                            with quasar.QMenu(target='#view-menu',auto_close=True,classes='project-menu'):
                                for panel,label in [('volume','µCT volume'),('iq','SAXS 1D'),('cake','SAXS cake'),('crop','Crop'),('resolution','Resolution')]:
                                    with html.Button(click=f"window.nimWorkspace.toggle('{panel}')",raw_attrs=['role="menuitemcheckbox"',f':aria-checked="workspace_tabs.includes(\'{panel}\')"']):
                                        html.Span('✓',classes='tab-menu-check',raw_attrs=[f':style="{{visibility: workspace_tabs.includes(\'{panel}\') ? \'visible\' : \'hidden\'}}"','aria-hidden="true"'])
                                        html.Span(label)
                                html.Button('Restore default layout',click='window.nimWorkspace.reset()',raw_attrs=['role="menuitem"'])
                        html.Button('{{ project_name ? \"Add sample\" : \"Open volume\" }}', id='open-volume', click=self.open_volume_picker,disabled=('volume_loading',))
                        with html.Select(v_model=('sample_choice',),raw_attrs=['aria-label="Active sample"'],v_if=('sample_choices.length',),disabled=('volume_loading',)):
                            html.Option('Select sample',value='',disabled=True)
                            html.Option('{{ sample.name }}',v_for='sample in sample_choices',value=('sample.id',),key=('sample.id',))
                        html.Span('{{ sample_name }}',v_if=('!sample_choice',),classes='active-sample-name')
                        html.Button('Add to project',click=self.add_current_sample,v_if=('!sample_choice',),disabled=('volume_loading',))
                        html.Button('Sample settings',click='window.nimCoordinates.pause(); show_sample_settings = true')
                        html.Button('Settings',id='open-settings')
                        html.Button('About', click='show_about = true')
                with html.Div(classes='controls'):
                    with html.Div(classes='coordinate-controls'):
                        for field,draft,label,step in [('x','draft_x','Beam position X (µm)',50),
                                                       ('y','draft_y','Beam position Y (µm)',50),
                                                       ('angle','draft_angle','Sample angle (°)','any')]:
                            with html.Div(classes='coordinate-control'):
                                with html.Label(classes='coordinate-label'):
                                    if field == 'x':
                                        html.Span('Beam position')
                                    elif field == 'angle':
                                        html.Span('Sample angle')
                                    bounds = {} if field == 'angle' else dict(min=('-beam_limit_um',),max=('beam_limit_um',))
                                    with html.Span(classes='coordinate-number axis-number'):
                                        if field in ('x','y'):
                                            html.Span(field.upper(),classes='axis-prefix',raw_attrs=['aria-hidden="true"'])
                                        html.Input(type='number',v_model=(draft,),id=f'coord-{field}-number',
                                                   step=step,raw_attrs=[f'aria-label="{label}"'],disabled=('volume_loading',),**bounds)
                                        html.Span('°' if field == 'angle' else 'µm',classes='coordinate-unit',raw_attrs=['aria-hidden="true"'])
                                with html.Div(classes='coordinate-slider'):
                                    html.Input(type='range',v_model=(draft,),id=f'coord-{field}-range',
                                               min=-180 if field == 'angle' else ('-beam_limit_um',),
                                               max=180 if field == 'angle' else ('beam_limit_um',),step=.1,
                                               title=f'{label} slider',aria_label=f'{label} slider',disabled=('volume_loading',))
                                    if field == 'angle':
                                        with html.Button(id='rotation-toggle',classes='rotation-button',
                                                title=("rotation_playing ? 'Pause rotation' : 'Play rotation'",),
                                                raw_attrs=[':aria-label="rotation_playing ? \'Pause\' : \'Play\'"']):
                                            quasar.QIcon(name=("rotation_playing ? 'pause' : 'play_arrow'",),raw_attrs=['aria-hidden="true"'])
                                        with html.Div(classes='rotation-settings-anchor'):
                                            with html.Button(id='rotation-settings',classes='rotation-button',title='Rotation settings',raw_attrs=['aria-label="Rotation settings"','aria-haspopup="dialog"']):
                                                self.svg_icon('adjustments.svg')
                                            with quasar.QMenu(v_model=('rotation_settings_open',),target='#rotation-settings',no_refocus=True,classes='rotation-settings'):
                                                with html.Div(role='dialog',raw_attrs=['aria-label="Rotation settings"']):
                                                    html.Strong('Rotation')
                                                    for field,label,minimum,maximum,step in [('rotation_fps','Updates per second',1,60,1),('rotation_step','Step (°)',.1,180,.1)]:
                                                        html.Label(label,raw_attrs=[f'for="{field}"'])
                                                        html.Input(type='number',id=field,v_model=(field,),min=minimum,max=maximum,step=step)
                                                    html.P("360°: {{ Number(rotation_fps) >= 1 && Number(rotation_fps) <= 60 && Number(rotation_step) >= 0.1 && Number(rotation_step) <= 180 ? (360 / (Number(rotation_fps) * Number(rotation_step))).toFixed(2) + ' s' : '—' }}",classes='settings-help')
                                                    html.P('Use 1–60 updates/s and 0.1–180° per update.',v_if=("!(Number(rotation_fps) >= 1 && Number(rotation_fps) <= 60 && Number(rotation_step) >= 0.1 && Number(rotation_step) <= 180)",),role='alert',classes='picker-error')
                                                    html.Button('Done',click='rotation_settings_open = false')
                    with html.Details(classes='beam-size'):
                        html.Summary('Beam size')
                        with html.Div(classes='beam-radius-controls',role='group',aria_label='Radius (µm)'):
                            html.Span('Radius (µm)',classes='radius-label')
                            for axis in 'xy':
                                quasar.QInput(type='number',v_model=(f'radius_{axis}',),prefix=axis.upper(),
                                              outlined=True,dense=True,hide_bottom_space=True,
                                              dark=("ui_theme === 'dark'",),classes='beam-radius',disable=('volume_loading',),
                                              raw_attrs=[f'aria-label="{axis.upper()} radius (µm)"',
                                                         'step="10"','min="10"','max="500"'])
                    with html.Label():
                        html.Span('Opacity ')
                        html.Input(type='range',v_model=('opacity',),min=.05,max=1,step=.05,style='width:90px',aria_label='Volume opacity',disabled=('volume_loading',))
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
                    html.Button('Beam view',click=lambda: self.reset_camera(True),disabled=('volume_loading',))
                    with html.Details(classes='beam-size'):
                        html.Summary('Contrast',title='Minimum and maximum map sample intensities to 0–1 for colour and opacity.')
                        for field,label in [('contrast_low','Minimum'),('contrast_high','Maximum')]:
                            with html.Label():
                                html.Span(label+' ')
                                html.Input(type='number',v_model=(field,),step=('contrast_step',),aria_label='Contrast '+label.lower(),disabled=('volume_loading',))
                        html.Button('Reset contrast',click=self.reset_contrast,
                                    title='Restore the initial contrast range for this sample',disabled=('volume_loading',))
                    with html.Div(classes='view-help-anchor'):
                        with html.Button(id='view-help',classes='rotation-button',title='Help on view controls',raw_attrs=['aria-label="View controls"']):
                            quasar.QIcon(name='help_outline',raw_attrs=['aria-hidden="true"'])
                        with quasar.QMenu(target='#view-help',classes='view-help',no_refocus=True):
                            html.Strong('View controls')
                            html.P('In the µCT volume viewer, click and drag with the left mouse button to view the sample from other directions. Scroll the mouse wheel to zoom in or out.')
                            html.P('Hold Shift while dragging with the left button to pan, or Ctrl to roll the view. Hold both Shift and Ctrl to zoom. You can also pan with the middle button and zoom with the right button.')
                            html.P('Hold Alt+Shift and drag with the left button to move the beam.')
                            html.P('The sample rotates about Y; the beam travels along Z, from light to dark.')
                self.workspace.build()
                with html.Div(classes='app-footer'):
                    html.Span('{{ volume_summary }}')
                    html.Span('{{ project_error }}',v_if=('project_error',),role='alert',classes='picker-error')
                    html.Span('{{ saved_view_error }}',v_if=('saved_view_error',),role='alert',classes='picker-error')
                    html.Span('{{ workspace_error }}',v_if=('workspace_error',),role='alert',classes='picker-error')
                    html.Span('{{ status }}')
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
                with quasar.QDialog(model_value=('show_sample_settings',),update_model_value=(self.close_sample_settings,'[$event]')):
                    with quasar.QCard(classes='sample-settings-card',raw_attrs=['role="dialog"','aria-labelledby="sample-settings-title"']):
                        with quasar.QCardSection():
                            html.H2('Sample settings',id='sample-settings-title')
                            with html.Div(v_if=('sample_choice',)):
                                html.Label('Sample name',raw_attrs=['for=\"sample-name\"'])
                                html.Input(id='sample-name',v_model=('sample_name_draft',),disabled=('volume_loading',))
                                html.Button('Rename sample',click=self.rename_sample,disabled=('volume_loading',))
                            with html.Div(v_if=('sample_pixel_size_editable',)):
                                html.H3('Pixel size (µm)')
                                html.P('User-supplied pixel size from TIFF import. Changes are saved to OME-Zarr when this dialog closes.',classes='settings-help')
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
                            html.P(BUILD, classes='about-muted')
                            html.P(COLLABORATION)
                            with html.Div(classes='infrastructure-links'):
                                for label,url,image in [('InfraVis','https://infravis.se/','infravis.svg'),
                                                        ('MAX IV','https://www.maxiv.lu.se/','maxiv.png'),
                                                        ('NAISS','https://www.naiss.se/','naiss.png')]:
                                    with html.A(href=url, target='_blank', rel='noopener noreferrer', title=label,aria_label=label):
                                        if image.endswith('.svg'):
                                            logo = (Path(__file__).parent/'assets/logos'/image).read_text()
                                            logo = re.sub(r'<style>.*?</style>', '', logo[logo.index('<svg'):], flags=re.S)
                                            logo = logo.replace('class="cls-2"', 'fill="currentColor"').replace('class="cls-1"', 'fill="url(#gradient-rainbow_2_copy)"')
                                            html.Span(logo,classes='infrastructure-logo',raw_attrs=['aria-hidden="true"'])
                                        else:
                                            html.Span(classes='infrastructure-logo monochrome-logo',style=f'mask-image:url(/nim-assets/logos/{image});-webkit-mask-image:url(/nim-assets/logos/{image})',raw_attrs=['aria-hidden="true"'])
                            if COPYRIGHT:
                                html.P(COPYRIGHT, classes='about-muted')
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
                                        ('Trame','trame','https://kitware.github.io/trame/'),
                                        ('VTK','vtk','https://vtk.org/'),
                                        ('trame-vtk','trame-vtk','https://github.com/Kitware/trame-vtk'),
                                        ('trame-quasar','trame-quasar','https://github.com/Kitware/trame-quasar'),
                                        ('trame-dockview','trame-dockview','https://github.com/Kitware/trame-dockview'),
                                        ('Plotly','plotly','https://plotly.com/python/'),
                                        ('trame-plotly','trame-plotly','https://github.com/Kitware/trame-plotly'),
                                        ('NumPy','numpy','https://numpy.org/'),
                                        ('tifffile','tifffile','https://github.com/cgohlke/tifffile'),
                                        ('ngff-zarr','ngff-zarr','https://ngff-zarr.readthedocs.io/')]:
                                    try:
                                        installed = version(package)
                                    except PackageNotFoundError:
                                        installed = 'unknown'
                                    with html.Div(classes='dependency-item'):
                                        html.A(label, href=url, target='_blank', rel='noopener noreferrer')
                                        html.Span(installed)
                            html.P('Dependencies retain their own licences.', classes='about-muted')
                        with quasar.QCardActions(align='right'):
                            html.Button('Close', click='show_about = false')
                with quasar.QDialog(v_model=('show_volume_picker',), persistent=True,position='top'):
                    with quasar.QCard(classes='volume-picker', raw_attrs=['role="dialog"', 'aria-labelledby="volume-picker-title"']):
                        with quasar.QCardSection():
                            html.H2('{{ picker_mode === \"project_directory\" ? \"Select project directory\" : picker_mode === \"project\" ? \"Open project\" : picker_mode === \"relink\" ? \"Locate sample data\" : project_name ? \"Add sample\" : \"Open CT volume\" }}', id='volume-picker-title')
                            html.Label('Directory on application host', raw_attrs=['for="volume-directory"'])
                            html.Input(id='volume-directory', type='text',v_model=('volume_directory',),disabled=('volume_loading',),
                                       keydown_enter=self.list_volume_directory,__events=[('keydown_enter','keydown.enter.prevent')])
                            with html.Div(classes='picker-actions'):
                                html.Button('Parent directory',click=self.parent_volume_directory,disabled=('volume_loading',))
                                html.Button('Refresh',click=self.list_volume_directory,disabled=('volume_loading',))
                            with quasar.QTable(id='volume-files',classes='file-table',
                                               rows=('volume_entries',),row_key='path',
                                               columns=('file_columns', [dict(name='name',label='Name',field='name',align='left',sortable=True),
                                                        dict(name='size',label='Size',field='size',align='right',sortable=True),
                                                        dict(name='modified',label='Modified',field='modified',align='left',sortable=True)]),
                                               pagination=("{rowsPerPage:0,sortBy:'name',descending:false}",),
                                               hide_bottom=True,dense=True,flat=True,
                                               raw_attrs=['aria-label="Files and directories"']):
                                with Template(raw_attrs=['#body="props"']):
                                    with html.Tr(click='!volume_loading && (volume_selection = props.row.path)',
                                                    dblclick=(self.open_selected_volume, "[props.row.path]"),
                                                    keydown_space='!volume_loading && (volume_selection = props.row.path)',
                                                    keydown_enter=(self.open_selected_volume, "[props.row.path]"),
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
                                html.Strong('{{ entry.name }}')
                                html.Div('{{ entry.kind }}{{ entry.size_detail ? " · " + entry.size_detail : "" }}')
                                html.Div('{{ entry.path }}',classes='file-detail-path')
                            with html.Div(v_if=("picker_mode !== 'project_directory' && /\\.tiff?$/i.test(volume_selection) && volume_prepared_path === volume_selection",)):
                                with html.Div(v_if=('project_name',)):
                                    html.Label('Conversion destination',raw_attrs=['for="import-destination-mode"'])
                                    with html.Select(id='import-destination-mode',v_model=('volume_import_mode',),disabled=('volume_loading',)):
                                        html.Option('In project',value='project')
                                        html.Option('External destination',value='external')
                                html.Button('Create new project',v_if=('!project_name',),click=self.show_new_project_for_tiff,disabled=('volume_loading',))
                                html.Label('OME-Zarr destination',raw_attrs=['for="volume-destination"'])
                                html.Input(id='volume-destination',type='text',v_model=('volume_destination',),disabled=("volume_loading || volume_import_mode === 'project'",))
                                html.P('Pixel size (µm)',classes='settings-help')
                                with html.Label():
                                    html.Input(type='checkbox',v_model=('volume_voxel_linked',),
                                               change="window.nimPixelSizes.begin('volume')",
                                               disabled=('volume_loading',))
                                    html.Span('Preserve XYZ ratio')
                                with html.Div(classes='sample-spacing-fields'):
                                    for axis in 'xyz':
                                        with html.Span(classes='axis-number'):
                                            html.Span(axis.upper(),classes='axis-prefix',raw_attrs=['aria-hidden="true"'])
                                            html.Input(type='number',v_model=(f'volume_voxel_{axis}',),step=1,min=0,
                                                       focus="window.nimPixelSizes.begin('volume')",
                                                       input=f"window.nimPixelSizes.change('volume','{axis}',$event.target.value)",
                                                       raw_attrs=[f'aria-label="Pixel size {axis.upper()} (µm)"'],disabled=('volume_loading',))
                            with html.Div(v_if=("picker_mode === 'project_directory'",)):
                                html.Label('New folder name',raw_attrs=['for="project-new-folder"'])
                                html.Input(id='project-new-folder',type='text',v_model=('project_new_folder',))
                                html.Button('Create folder',click=self.create_project_folder)
                            with html.Label(v_if=("picker_mode !== 'project_directory'",)):
                                html.Span('Voxel array size limit (MiB) ',title='Maximum size of the voxel array loaded into RAM for volume rendering.')
                                html.Input(type='number',v_model=('volume_preview_mib',),min=1,step=16,disabled=('volume_loading',))
                            html.P('{{ volume_error }}',v_if=('volume_error',),classes='picker-error',role='alert')
                            html.P('{{ volume_progress }}',v_if=('volume_loading',),role='status')
                        with quasar.QCardActions(align='right'):
                            html.Button('Cancel',click=self.cancel_volume_load)
                            html.Button('Use this directory',v_if=("picker_mode === 'project_directory'",),click=self.finish_project_directory)
                            html.Button('{{ picker_mode === \"project_directory\" ? \"Open folder\" : \"Open\" }}',click=self.open_selected_volume,disabled=("volume_loading || (picker_mode === 'project_directory' && !volume_selection) || (picker_mode !== 'project_directory' && /\\.tiff?$/i.test(volume_selection) && volume_prepared_path !== volume_selection)",))
        self.layout = layout
