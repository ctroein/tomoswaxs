"""Dockable volume and SAXS panels, independent of application controls."""
from trame.ui.html import DivLayout
from trame.widgets import dockview, html, plotly, vtk as vtk_widgets


class DockWorkspace:
    def __init__(self, app):
        self.app = app

    def build_panels(self):
        app = self.app
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

    def build(self):
        self.dock = dockview.DockView(ref='nimDock',theme=("ui_theme === 'dark' ? 'Dark' : 'Light'",),
            classes='dock-workspace',raw_attrs=[':aria-busy="!workspace_ready"'],default_renderer='always',floating_group_bounds='boundedWithinViewport',
            ready='window.nimWorkspace.ready(() => trame.refs.nimDock)',
            layout_changed='window.nimWorkspace.changed($event)',
            panel_visibility='window.nimWorkspace.visibility($event)')

    def plot(self):
        figure = plotly.Figure(classes='plot',style='width:100%;height:100%',display_logo=False,responsive=True)
        figure.layout = (f"window.nimPreferences.plotLayout({figure.key}.layout, ui_theme, ui_text_scale)",)
        figure.data = (f"window.nimPreferences.plotData({figure.key}.data, ui_theme, ui_text_scale)",)
        return figure
