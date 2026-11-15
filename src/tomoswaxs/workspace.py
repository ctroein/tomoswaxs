"""Dockable volume and SAXS panels, independent of application controls."""
from trame.ui.html import DivLayout
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
            with html.Div(id='volume-interaction',style=("'width:100%;height:100%;position:relative;pointer-events:' + (volume_loading ? 'none' : 'auto')",)):
                app.view = vtk_widgets.VtkRemoteView(app.window,interactive_ratio=1,interactive_quality=75,still_quality=95,
                    interactor_events=('camera_events',['EndAnimation']),EndAnimation=app.schedule_project_save,
                    style='width:100%;height:100%')
        with DivLayout(app.server, 'nim_iq') as layout:
            layout.root.classes = 'dock-panel'
            with html.Div(classes='plot-toolbar'):
                with html.Label():
                    html.Input(type='checkbox',v_model=('log_iq',),raw_attrs=['aria-label="Log intensity"'])
                    html.Span(' Log I')
            app.curve = self.plot()
        with DivLayout(app.server, 'nim_cake') as layout:
            layout.root.classes = 'dock-panel'
            app.cake = self.plot()
        self.build_volume_controls()

    def build_volume_controls(self):
        app=self.app
        with DivLayout(app.server,'nim_crop') as layout:
            layout.root.classes='volume-controls-panel'
            html.P('Bounds in full-resolution image voxel indices. End indices are exclusive.',classes='settings-help')
            with html.Div(classes='crop-column-labels',raw_attrs=['aria-hidden="true"']):
                html.Span('Start');html.Span();html.Span('End')
            for axis in 'xyz':
                with html.Div(classes='crop-axis-row'):
                    for side in ('min','max'):
                        if side=='max':
                            quasar.QRange(v_model=(f'crop_draft_{axis}',),min=('0',),max=(f'crop_max_{axis}',),step=('1',),
                                dark=("ui_theme === 'dark'",),dense=True,
                                update_model_value=f"window.nimCrop.change('{axis}',$event)",
                                change=f"window.nimCrop.change('{axis}',$event,true)",
                                disable=('volume_loading',),classes='crop-range',
                                raw_attrs=[f'aria-label="Crop {axis.upper()} range"'])
                        with html.Span(classes='axis-number'):
                            html.Span(axis.upper(),classes='axis-prefix',raw_attrs=['aria-hidden="true"'])
                            html.Input(type='number',min=0,max=(f'crop_max_{axis}',),step=1,
                                raw_attrs=[f'v-model.number="crop_draft_{axis}.{side}"',
                                           f'aria-label="Crop {axis.upper()} {"start" if side=="min" else "end"} index"'],
                                input=f"window.nimCrop.edit('{axis}','{side}',$event.target.value)",
                                change='window.nimCrop.submit(true)',
                                keydown_enter='window.nimCrop.submit(true)',__events=[('keydown_enter','keydown.enter.prevent')],disabled=('volume_loading',))
            with html.Div(classes='crop-actions'):
                html.Button('Reset crop',click='window.nimCrop.reset()',disabled=('volume_loading',))
                html.Button('Copy coordinates',click='window.nimCrop.copy()')
            with html.Label():
                html.Input(type='checkbox',v_model=('crop_handles',),disabled=('volume_loading',))
                html.Span(' 3D handles')
            html.P('{{ crop_notice }}',v_if=('crop_notice',),role='status',classes='settings-help')
            html.P('{{ render_target }}',classes='settings-help')
            self.render_status()
        with DivLayout(app.server,'nim_resolution') as layout:
            layout.root.classes='volume-controls-panel'
            html.Label('OME-Zarr level',raw_attrs=['for="render-level"'])
            with html.Select(id='render-level',v_model=('render_level',),change='window.nimCrop.submit(true)',disabled=('volume_loading',)):
                html.Option('{{ item.label }}',v_for='item in render_options',key=('item.value',),value=('item.value',),disabled=('item.disabled',))
            html.P('Level 0 is full resolution. Auto selects a level for the current crop and array size limit.',classes='settings-help')
            html.Label('Voxel array size limit (MiB)',raw_attrs=['for="render-limit"'])
            html.Input(id='render-limit',type='number',v_model_number=('volume_preview_mib',),min=1,step=64,
                input='window.nimCrop.limit($event.target.value)',change='window.nimCrop.submit(true)',disabled=('volume_loading',),title='Maximum voxel array size loaded into RAM for rendering.')
            html.H4('Loaded array')
            html.P('{{ render_loaded }}',role='status')
            self.render_status()

    def render_status(self):
        html.P('Loading volume region…',v_if=('render_loading',),role='status',classes='settings-help')
        html.Button('Cancel loading',v_if=('render_loading',),click=self.app.cancel_volume_render)
        html.P('{{ render_error }}',v_if=('render_error',),role='alert',classes='picker-error')

    def build(self):
        self.dock = dockview.DockView(ref='nimDock',theme=("ui_theme === 'dark' ? 'Dark' : 'Light'",),
            components=('{defaultTabComponent: \'nim_tab\'}',),popout_url='/nim-assets/popout.html',
            classes='dock-workspace',raw_attrs=[':aria-busy="!workspace_ready"'],default_renderer='always',floating_group_bounds='boundedWithinViewport',
            ready='window.nimWorkspace.ready(() => trame.refs.nimDock)',
            layout_changed='window.nimWorkspace.changed($event)',
            remove_panel='window.nimWorkspace.removed($event)',
            panel_visibility='window.nimWorkspace.visibility($event)')

    def plot(self):
        figure = plotly.Figure(classes='plot',style='width:100%;height:100%',display_logo=False,responsive=True)
        figure.layout = (f"window.nimPreferences.plotLayout({figure.key}.layout, ui_theme, ui_text_scale)",)
        figure.data = (f"window.nimPreferences.plotData({figure.key}.data, ui_theme, ui_text_scale)",)
        return figure
