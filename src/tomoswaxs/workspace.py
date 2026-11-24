"""Dockable volume and SAXS panels, independent of application controls."""
from trame.ui.html import DivLayout
from .saxs_ui import build_saxs_panel
from trame.widgets import dockview, html, plotly, quasar, vtk as vtk_widgets


class DockWorkspace:
    def __init__(self, app):
        self.app = app

    def build_panels(self):
        app = self.app
        # Dockview passes its native APIs as attrs to this Trame template.
        with DivLayout(app.server, 'nim_tab'):
            with html.Div(classes='nim-tab',raw_attrs=[
                    '@vue:mounted="window.nimWorkspace.mountTab($event.el, $attrs.params)"',
                    '@vue:unmounted="window.nimWorkspace.unmountTab($event.el)"']):
                html.Span('{{ $attrs.params.api.title }}',classes='nim-tab-title')
                with html.Label(v_if=("$attrs.params.api.id === 'iq'",),classes='nim-tab-control',
                                raw_attrs=['@pointerdown.stop','@mousedown.stop','@click.stop','@keydown.stop']):
                    html.Input(type='checkbox',v_model=('log_iq',),disabled=('!has_sample',),raw_attrs=['aria-label="Log intensity"'])
                    html.Span('Log I')
                self.volume_help()
                with html.Button(classes=("'nim-tab-action' + (workspace_detached.includes($attrs.params.api.id) ? ' is-detached' : '')",),
                        click='window.nimWorkspace.popout($attrs.params)',
                        title=("workspace_detached.includes($attrs.params.api.id) ? 'Return to main window' : 'Open in separate window'",),
                        raw_attrs=[':aria-label="(workspace_detached.includes($attrs.params.api.id) ? \'Return to main window: \' : \'Open in separate window: \') + $attrs.params.api.title"',
                                   '@pointerdown.stop','@mousedown.stop','@click.stop'],
                        disabled=('workspace_busy.includes($attrs.params.api.id)',)):
                    app.svg_icon('open-window.svg')
                html.Button('×',classes='nim-tab-action nim-tab-close',
                    click='$attrs.params.api.close()',title='Close tab',
                    raw_attrs=[':aria-label="\'Close tab: \' + $attrs.params.api.title"','@pointerdown.stop','@mousedown.stop','@click.stop'])
        with DivLayout(app.server, 'nim_volume') as layout:
            layout.root.style = 'width:100%;height:100%;position:relative;'
            with html.Div(id='volume-interaction',v_show=('has_sample',),style=("'width:100%;height:100%;position:relative;pointer-events:' + (volume_loading ? 'none' : 'auto')",)):
                app.view = vtk_widgets.VtkRemoteView(app.window,interactive_ratio=1,interactive_quality=75,still_quality=95,
                    interactor_events=('camera_events',['EndAnimation']),EndAnimation=app.camera_rendered,
                    style='width:100%;height:100%')
        with DivLayout(app.server, 'nim_iq') as layout:
            layout.root.classes = 'dock-panel'
            app.curve = self.plot()
        with DivLayout(app.server, 'nim_cake') as layout:
            layout.root.classes = 'dock-panel'
            app.cake = self.plot()
        self.build_volume_controls()
        build_saxs_panel(app)

    def volume_help(self):
        with html.Div(v_if=("$attrs.params.api.id === 'volume'",),classes='view-help-anchor',
                      raw_attrs=['@pointerdown.stop','@mousedown.stop','@click.stop','@keydown.stop']):
            with html.Button(classes='nim-tab-action',title='Help on view controls',click='window.nimWorkspace.viewHelp($event)',
                             raw_attrs=['aria-label="View controls"','aria-haspopup="dialog"']):
                quasar.QIcon(name='help_outline',size='1rem',raw_attrs=['aria-hidden="true"'])
            with html.Div(classes='view-help',raw_attrs=['popover="auto"','role="dialog"','aria-label="View controls"']):
                html.Strong('View controls')
                html.P('In the µCT volume viewer, click and drag with the left mouse button to view the sample from other directions. Scroll the mouse wheel to zoom in or out.')
                html.P('Hold Shift while dragging with the left button to pan, or Ctrl to roll the view. Hold both Shift and Ctrl to zoom. You can also pan with the middle button and zoom with the right button.')
                html.P('Hold Alt+Shift and drag with the left button to move the beam.')
                html.P('The sample rotates about Y; the beam travels along Z, from light to dark.')


    def build_volume_controls(self):
        app=self.app
        with DivLayout(app.server,'nim_crop') as layout:
            layout.root.classes='volume-controls-panel'
            with html.Div(classes='detail-controls'):
                with html.Label(classes='detail-enable'):
                    html.Input(id='auto-detail',type='checkbox',v_model=('detail_enabled',),
                               change='window.nimCrop.detail(true,$event.target.checked)',disabled=('!has_volume || volume_loading',))
                    html.Span('Auto detail')
                html.Button("{{ detail_frozen ? 'Unfreeze region' : 'Freeze region' }}",
                            id='freeze-region',click='window.nimCrop.freeze()',
                            disabled=('!detail_enabled || !has_volume || volume_loading',),
                            raw_attrs=[':aria-pressed="detail_frozen"'])
            with html.Div(classes='detail-depth-row'):
                html.Label('Depth',raw_attrs=['for="detail-depth"'])
                html.Input(id='detail-depth',type='range',min=0,max=100,step=1,v_model_number=('detail_depth',),
                           input='window.nimCrop.detail(false,null,$event.target.value)',change='window.nimCrop.detail(true,null,$event.target.value)',
                           disabled=('!detail_enabled || detail_frozen || !has_volume || volume_loading',),
                           title='Thin region to full depth; thickness follows zoom.')
                html.Span("{{ detail_depth >= 100 ? 'Full' : detail_depth_um }}",classes='detail-depth-value')
            html.P('{{ detail_notice }}',v_if=('detail_notice',),role='status',classes='settings-help')
            with html.Div(classes='crop-units-row'):
                html.Label('Units',raw_attrs=['for="crop-units"'])
                with html.Select(id='crop-units',v_model=('crop_units',),title='Image coordinates before sample orientation. End bounds are exclusive.'):
                    html.Option('Voxels',value='voxel');html.Option('µm',value='um')
                with html.Div(classes='crop-actions'):
                    with html.Button(click='window.nimCrop.reset()',disabled=('volume_loading || !has_volume',),title='Reset crop',raw_attrs=['aria-label="Reset crop"']):
                        quasar.QIcon(name='refresh',size='1rem',raw_attrs=['aria-hidden="true"'])
                    with html.Button(click='window.nimCrop.copy()',disabled=('!has_volume',),title='Copy coordinates',
                                     raw_attrs=['aria-label="Copy coordinates"']):
                        quasar.QIcon(name='content_copy',size='1rem',raw_attrs=['aria-hidden="true"'])
                    with html.Label():
                        html.Input(type='checkbox',v_model=('crop_handles',),disabled=('volume_loading || !has_volume',))
                        html.Span(' 3D handles')
            for axis in 'xyz':
                with html.Div(classes='crop-axis-row'):
                    html.Label(axis.upper(),raw_attrs=[f'for="crop-{axis}-min"'])
                    for side in ('min','max'):
                        if side=='max':
                            quasar.QRange(v_model=(f'crop_draft_{axis}',),min=('0',),max=(f'crop_max_{axis}',),step=('1',),
                                dark=("ui_theme === 'dark'",),dense=True,
                                update_model_value=f"window.nimCrop.change('{axis}',$event)",
                                change=f"window.nimCrop.change('{axis}',$event,true)",
                                disable=('volume_loading || !has_volume',),classes='crop-range',
                                raw_attrs=[f'aria-label="Crop {axis.upper()} range"'])
                        with html.Span(classes='axis-number'):
                            physical=f"window.nimCrop.display('{axis}',crop_draft_{axis}.{side},crop_units,crop_origin_um,crop_spacing_um)"
                            commit=f"window.nimCrop.commit('{axis}','{side}',$event)"
                            html.Input(type='number',id=f'crop-{axis}-{side}',
                                min=(f"window.nimCrop.display('{axis}',0,crop_units,crop_origin_um,crop_spacing_um)",),
                                max=(f"window.nimCrop.display('{axis}',crop_max_{axis},crop_units,crop_origin_um,crop_spacing_um)",),
                                step=(f"crop_units === 'um' ? crop_spacing_um[{'xyz'.index(axis)}] : 1",),value=(physical,),
                                raw_attrs=[f":aria-label=\"'Crop {axis.upper()} {'start' if side=='min' else 'end'} ' + (crop_units === 'um' ? '(µm)' : 'index')\""],
                                input=f"window.nimCrop.input('{axis}','{side}',$event)",
                                change=commit,keydown_enter=commit,__events=[('keydown_enter','keydown.enter.prevent')],disabled=('volume_loading || !has_volume',))
            html.P('{{ crop_notice }}',v_if=('crop_notice',),role='status',classes='settings-help')
            html.P('{{ render_target }}',classes='settings-help')
            with html.Div(classes='resolution-choice'):
                html.Label('OME-Zarr level',raw_attrs=['for="render-level"'])
                with html.Select(id='render-level',v_model=('render_level',),change='window.nimCrop.submit(true)',disabled=('volume_loading || !has_volume || detail_enabled',),
                                 title='Level 0 is full resolution. Auto selects a level for the current crop and array size limit.'):
                    html.Option("{{ detail_enabled && item.value === 'auto' ? 'Auto detail (L' + detail_level + ')' : item.label }}",v_for='item in render_options',key=('item.value',),value=('item.value',),disabled=('item.disabled',))
            with html.Div(classes='resolution-limit'):
                html.Label('Voxel array limit (MiB)',raw_attrs=['for="render-limit"'])
                html.Input(id='render-limit',type='number',v_model_number=('volume_preview_mib',),min=1,step=64,
                    input='window.nimCrop.limit($event.target.value)',change='window.nimCrop.submit(true)',disabled=('volume_loading || !has_volume',),title='Maximum voxel array size loaded into RAM for rendering.')
            html.P("{{ 'Loaded ' + render_loaded }}",role='status',classes='loaded-array-summary')
            html.P("{{ 'Rendered ' + render_display }}",v_if=("render_level === 'auto' || detail_enabled",),classes='loaded-array-summary')
            self.render_status()

    def render_status(self):
        html.P('Loading volume region…',v_if=('render_loading',),role='status',classes='settings-help')
        html.Button('Cancel loading',v_if=('render_loading',),click=self.app.cancel_volume_render)
        html.P('{{ render_error }}',v_if=('render_error',),role='alert',classes='picker-error')

    def build(self):
        self.dock = dockview.DockView(ref='nimDock',theme=("ui_theme === 'dark' ? 'Dark' : 'Light'",),
            v_show=('has_sample',),
            components=('{defaultTabComponent: \'nim_tab\'}',),popout_url='/nim-assets/popout.html',
            classes='dock-workspace',raw_attrs=[':aria-busy="!workspace_ready"'],default_renderer='always',floating_group_bounds='boundedWithinViewport',
            ready='window.nimWorkspace.ready(() => trame.refs.nimDock)',
            layout_changed='window.nimWorkspace.changed($event)',
            remove_panel='window.nimWorkspace.removed($event)',
            panel_visibility='window.nimWorkspace.visibility($event)')

    def plot(self):
        figure = plotly.Figure(classes='plot',v_show=('has_sample',),style='width:100%;height:100%',display_logo=False,responsive=True)
        figure.layout = (f"window.nimPreferences.plotLayout({figure.key}.layout, ui_theme, ui_text_scale, ui_plot_scale)",)
        figure.data = (f"window.nimPreferences.plotData({figure.key}.data, ui_theme, ui_text_scale, ui_plot_scale)",)
        return figure
