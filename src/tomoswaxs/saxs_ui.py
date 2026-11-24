"""Controls for selecting supplied scattering measurements."""
from trame.ui.html import DivLayout
from trame.widgets import html, quasar


def build_saxs_panel(app):
    with DivLayout(app.server,'nim_saxs') as layout:
        layout.root.classes='volume-controls-panel saxs-controls'
        html.P('No SAXS data loaded',v_if=('!saxs_available',),classes='settings-help')
        with html.Fieldset(disabled=('!saxs_available',),classes='saxs-fields'):
            with html.Div(classes='saxs-control-row'):
                html.Label('Scan / Y',raw_attrs=['for="saxs-scan"'])
                with html.Select(id='saxs-scan',v_model=('saxs_draft_scan',),change='window.nimSaxs.scan()'):
                    html.Option('{{ item.label }}',v_for='item in saxs_sources',key=('item.value',),value=('item.value',))
            for kind,label,index in [('x','X position','column'),('angle','Rotation','row')]:
                with html.Div(classes='saxs-control-row'):
                    html.Label(label,raw_attrs=[f'for="saxs-{kind}"'])
                    with html.Div(classes='saxs-coordinate'):
                        html.Button('−',click=f"window.nimSaxs.step('{kind}',-1)",raw_attrs=[f'aria-label="Previous SAXS {kind}"'])
                        with html.Span(classes='axis-number saxs-list-number'):
                            html.Input(id=f'saxs-{kind}',type='text',inputmode='decimal',role='spinbutton',
                                v_model=(f'saxs_input_{kind}',),input=f"window.nimSaxs.edit('{kind}')",
                                change=f"window.nimSaxs.position('{kind}',$event.target.value)",
                                keydown_enter=f"window.nimSaxs.position('{kind}',$event.target.value)",
                                keydown_up=f"window.nimSaxs.step('{kind}',1)",keydown_down=f"window.nimSaxs.step('{kind}',-1)",
                                __events=[('keydown_enter','keydown.enter.prevent'),('keydown_up','keydown.up.prevent'),('keydown_down','keydown.down.prevent')],
                                raw_attrs=['role="spinbutton"',f'aria-label="SAXS {"X position (µm)" if kind=="x" else "sample rotation (°)"}"',(':aria-valuenow="(saxs_axes[saxs_draft_scan]?.x_by_angle?.[saxs_draft_row] || saxs_axes[saxs_draft_scan]?.x)?.[saxs_draft_column]"' if kind=='x' else ':aria-valuenow="saxs_axes[saxs_draft_scan]?.angle?.[saxs_draft_row]"')])
                            html.Span('µm' if kind=='x' else '°',classes='coordinate-unit',raw_attrs=['aria-hidden="true"'])
                        html.Button('+',click=f"window.nimSaxs.step('{kind}',1)",raw_attrs=[f'aria-label="Next SAXS {kind}"'])
                        if kind=='x':
                            with html.Button(classes='saxs-x-lock',click='window.nimSaxs.toggleXLock()',
                                    title='Keep approximate X when rotation changes',
                                    raw_attrs=['aria-label="Lock approximate SAXS X"',':aria-pressed="saxs_lock_x"']):
                                quasar.QIcon(name=("saxs_lock_x ? 'lock' : 'lock_open'",),size='1rem',raw_attrs=['aria-hidden="true"'])
                html.Input(type='range',min=0,max=(f"Math.max(0,(saxs_axes[saxs_draft_scan]?.{kind}?.length || 1)-1)",),step=1,
                    v_model_number=(f'saxs_draft_{index}',),input='window.nimSaxs.select()',change='window.nimSaxs.select(true)',raw_attrs=[f'aria-label="SAXS {kind} index"'])
            html.P('{{ saxs_flag }}',v_if=('saxs_flag',),classes='saxs-flag',raw_attrs=['role="status"'])
            with html.Label(classes='beam-visibility'):
                html.Input(type='checkbox',v_model=('beam_visible',))
                html.Span(' Show beam')
            with html.Details(classes='beam-size'):
                html.Summary('Beam size')
                with html.Div(classes='beam-radius-controls',role='group',aria_label='Radius (µm)'):
                    html.Span('Radius (µm)',classes='radius-label')
                    for axis in 'xy':
                        quasar.QInput(type='number',v_model=(f'radius_{axis}',),prefix=axis.upper(),
                                      outlined=True,dense=True,hide_bottom_space=True,
                                      dark=("ui_theme === 'dark'",),classes='beam-radius',disable=('volume_loading || !saxs_available',),
                                      raw_attrs=[f'aria-label="{axis.upper()} radius (µm)"',
                                                 'step="10"','min="10"','max="500"'])
            with html.Details():
                html.Summary('Measurement details')
                with html.Table(classes='saxs-readbacks'):
                    with html.Tr():
                        html.Th('Frame');html.Td('{{ saxs_frame }}')
                    for key,label in [('x_um','Motor X (µm)'),('y_um','Motor Y (µm)'),('angle','Motor rotation (°)')]:
                        with html.Tr():
                            html.Th(label);html.Td('{{ saxs_recorded.'+key+' }}')
                    with html.Tr():
                        html.Th('Y source');html.Td('{{ saxs_y_source }}')
            with html.Details(classes='saxs-registration'):
                html.Summary('CT registration')
                with html.Div(classes='registration-fields'):
                    html.Label('Model',raw_attrs=['for="registration-model"'])
                    with html.Select(id='registration-model',v_model=('saxs_map_model',),change='window.nimSaxs.select(true)'):
                        html.Option('ForMAX motor stack',value='stack')
                        html.Option('Motor differences from CT reference',value='motors')
                        html.Option('Manual scan origin',value='manual')
                html.P('Initial CT reference: {{ saxs_registration_source.split("/").pop() }}',title=('saxs_registration_source',),classes='settings-help registration-source')
                with html.Table(v_if=("saxs_map_model !== 'manual'",),classes='registration-motors'):
                    with html.Thead():
                        with html.Tr():
                            for text in ('Motor','CT ref. (mm)','X factor','Y factor'):html.Th(text)
                    with html.Tbody():
                        with html.Tr(v_for='motor in saxs_map_motors',key=('motor.name',)):
                            html.Td('{{ motor.name }}')
                            for key in ('reference','x','y'):
                                with html.Td():
                                    html.Input(type='number',step='any',value=(f'window.nimSaxs.formatCoordinate(motor.{key})',),
                                        change=f"window.nimSaxs.motorPlacement(motor.name,'{key}',$event.target.value)",
                                        disabled=("saxs_map_model === 'stack' && ['tomo_xf','tomo_zf'].includes(motor.name)" if key=='y' else 'false',),
                                        raw_attrs=[f":aria-label=\"motor.name + ' {key}'\""])
                for label,prefix in [('Scan origin (µm)','origin'),('CT offset (µm)','offset'),('Beam-centre shift (µm)','camera')]:
                    with html.Div(classes='registration-coordinate',v_if=("saxs_map_model === 'manual'" if prefix=='origin' else "saxs_map_model !== 'manual'" if prefix=='camera' else 'true',)):
                        html.Label(label)
                        with html.Div(classes='saxs-placement-row'):
                            for axis in 'xy':
                                key=f'{axis}_{prefix}' if prefix!='camera' else f'camera_{axis}'
                                with html.Span(classes='axis-number'):
                                    html.Span(axis.upper(),classes='axis-prefix',raw_attrs=['aria-hidden="true"'])
                                    html.Input(type='number',step='any',value=(f'window.nimSaxs.formatCoordinate(saxs_map_{key})',),
                                        change=f"window.nimSaxs.placement('{key}',$event.target.value)",raw_attrs=[f'aria-label="{label} {axis.upper()}"'])
                with html.Div(classes='registration-coordinate',v_if=("saxs_map_model === 'stack'",)):
                    html.Label('Trajectory correction (µm)',title='X and Z coefficients of the fitted angular beam correction in the centred CT frame.')
                    with html.Div(classes='saxs-placement-row'):
                        for axis in 'xz':
                            with html.Span(classes='axis-number'):
                                html.Span(axis.upper(),classes='axis-prefix',raw_attrs=['aria-hidden="true"'])
                                html.Input(type='number',step='any',value=(f'window.nimSaxs.formatCoordinate(saxs_map_pivot_{axis})',),
                                    change=f"window.nimSaxs.placement('pivot_{axis}',$event.target.value)",raw_attrs=[f'aria-label="Trajectory correction {axis.upper()} (µm)"'])
                with html.Div(v_if=("saxs_map_model === 'manual'",)):
                    for axis in 'xy':
                        with html.Label():
                            html.Span(f'{axis.upper()} direction ')
                            with html.Select(v_model_number=(f'saxs_map_{axis}_sign',),change='window.nimSaxs.select(true)',raw_attrs=[f'aria-label="SAXS {axis.upper()} direction"']):
                                html.Option('Same',value=1);html.Option('Reversed',value=-1)
                with html.Label():
                    html.Span('Sample Y from image ')
                    with html.Select(v_model=('rotation_axis',),raw_attrs=['aria-label="Sample Y from image"']):
                        for axis in 'xyz':html.Option(axis.upper(),value=axis)
                with html.Label():
                    html.Span('Rotation direction ')
                    with html.Select(v_model_number=('saxs_map_angle_sign',),change='window.nimSaxs.select(true)',raw_attrs=['aria-label="SAXS rotation direction"']):
                        html.Option('Same',value=1);html.Option('Reversed',value=-1)
                with html.Label():
                    html.Span('Rotation offset (°) ')
                    html.Input(type='number',step='any',v_model_number=('saxs_map_angle_offset',),change='window.nimSaxs.select(true)',raw_attrs=['aria-label="SAXS rotation offset (°)"'])
        html.P('Loading SAXS measurement…',v_if=('saxs_loading',),raw_attrs=['role="status"'])
        html.P('{{ saxs_error || saxs_input_notice }}',v_if=('saxs_error || saxs_input_notice',),classes='picker-error',raw_attrs=['role="alert"'])
