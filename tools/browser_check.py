"""Exercise a running installed application; retain a Playwright trace on failure."""
import argparse
import re
from pathlib import Path
import tempfile
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


# The narrow beam alone must not satisfy the rendered-volume check.
SCENE_RENDERED = "() => [...document.querySelectorAll('#volume-interaction canvas, #volume-interaction img')].some(c => {\n    if (c.tagName === 'IMG' && (!c.complete || !c.naturalWidth)) return false;\n    const sample=document.createElement('canvas'); sample.width=64; sample.height=64;\n    const ctx=sample.getContext('2d'); ctx.drawImage(c,0,0,64,64);\n    const bytes=ctx.getImageData(0,0,64,64).data;\n    let bright=0;\n    for(let i=0;i<bytes.length;i+=4) if(Math.max(bytes[i],bytes[i+1],bytes[i+2])>60) bright++;\n    return bright/(64*64) > .02;\n})"

def check_volume_controls(page):
    page.locator('.nim-tab-title').filter(has_text=re.compile('^Crop$')).click()
    start=page.get_by_role('spinbutton',name='Crop X start index',exact=True)
    end=page.get_by_role('spinbutton',name='Crop X end index',exact=True)
    full=int(end.input_value());lo=full//4;hi=3*full//4
    start.fill(str(lo));end.fill(str(hi));end.press('Enter')
    page.wait_for_function('([lo,hi]) => !window.trame.state.get("render_loading") && window.trame.state.get("render_loaded").includes(`${hi-lo} ×`)',arg=[lo,hi])
    slider=page.get_by_role('slider',name='Crop X range',exact=True)
    handle=slider.locator('.q-slider__thumb').first.bounding_box()
    x,y=handle['x']+handle['width']/2,handle['y']+handle['height']/2
    page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+10,y,steps=5);page.mouse.up()
    expect(start).not_to_have_value(str(lo))
    lo=int(start.input_value())
    page.wait_for_function('width => !window.trame.state.get("render_loading") && window.trame.state.get("render_loaded").includes(`${width} ×`)',arg=hi-lo)
    page.locator('.nim-tab-title').filter(has_text=re.compile('^Resolution$')).click()
    page.get_by_role('combobox',name='OME-Zarr level',exact=True).select_option('0')
    page.wait_for_function('window.trame.state.get("render_level") === "0" && !window.trame.state.get("render_loading")')
    page.reload()
    page.wait_for_function('window.nimCrop && window.trame.state.get("workspace_ready")')
    page.locator('.nim-tab-title').filter(has_text=re.compile('^Crop$')).click()
    expect(start).to_have_value(str(lo));expect(end).to_have_value(str(hi))
    page.get_by_role('checkbox',name='3D handles',exact=True).check()
    page.get_by_role('checkbox',name='3D handles',exact=True).uncheck()
    page.get_by_role('button',name='Reset crop',exact=True).click()
    page.wait_for_function('full => !window.trame.state.get("render_loading") && window.trame.state.get("render_loaded").includes(`${full} ×`)',arg=full)
    print('Crop, explicit level, reset and reload passed.',flush=True)


def check_popouts(page):
    """Exercise live components in child documents and their return paths."""
    for title in ['µCT volume','SAXS 1D · synthetic','SAXS cake · synthetic']:
        if title == 'µCT volume':
            page.get_by_role('button',name='Beam view',exact=True).click()
        with page.expect_popup() as opened:
            page.get_by_role('button',name=f'Open in separate window: {title}',exact=True).click()
        child=opened.value
        child.wait_for_load_state()
        back=child.get_by_role('button',name=f'Return to main window: {title}',exact=True)
        expect(back).to_be_visible()
        expect(page.get_by_role('tab')).to_have_count(4)
        child.set_viewport_size({'width':800,'height':600})
        child.wait_for_function("document.documentElement.dataset.theme === 'light'")
        if title == 'µCT volume':
            child.wait_for_function(SCENE_RENDERED)
            before=page.evaluate("[window.trame.state.get('beam_x'),window.trame.state.get('beam_y')]")
            box=child.locator('#volume-interaction').bounding_box()
            child.keyboard.down('Alt');child.keyboard.down('Shift')
            child.mouse.move(box['x']+box['width']*.5,box['y']+box['height']*.5)
            child.mouse.down()
            child.mouse.move(box['x']+box['width']*.6,box['y']+box['height']*.55,steps=8)
            child.mouse.up();child.keyboard.up('Shift');child.keyboard.up('Alt')
            page.wait_for_function('before => JSON.stringify([window.trame.state.get("beam_x"),window.trame.state.get("beam_y")]) !== JSON.stringify(before)',arg=before)
        else:
            child.wait_for_function("document.querySelector('.js-plotly-plot')?.data?.length")
            before=child.locator('.js-plotly-plot').evaluate('(p)=>JSON.stringify(p.data)')
            x=float(page.locator('#coord-x-number').input_value())
            page.locator('#coord-x-number').fill(str(x+50))
            page.locator('#coord-x-number').press('Tab')
            child.wait_for_function("before=>JSON.stringify(document.querySelector('.js-plotly-plot').data)!==before",arg=before)
        page.get_by_role('button',name='Settings',exact=True).click()
        page.locator('#pref-theme').select_option('dark')
        child.wait_for_function("document.documentElement.dataset.theme === 'dark'")
        page.locator('#pref-theme').select_option('light')
        page.get_by_role('button',name='Close',exact=True).click()
        with child.expect_event('close'):
            back.click()
        expect(page.get_by_role('tab')).to_have_count(5)
    with page.expect_popup() as opened:
        page.get_by_role('button',name='Open in separate window: SAXS cake · synthetic',exact=True).click()
    opened.value.close()
    expect(page.get_by_role('tab')).to_have_count(5)
    print('Popout rendering, interaction, updates, theme and return passed.',flush=True)


def file_row(page,path):
    return page.locator('#volume-files tbody tr').filter(
        has=page.get_by_role('cell',name=Path(path).name,exact=True))


def check_directory_navigation(page):
    """Exercise selection, sorting and navigation in a scrolling table."""
    with tempfile.TemporaryDirectory(prefix='nim-picker-check-') as folder:
        root = Path(folder)
        for index in range(30):
            (root/f'{index:02d}_directory_with_a_long_descriptive_volume_name').mkdir()
        last = sorted(root.iterdir())[-1]
        page.get_by_role('button',name='Open volume',exact=True).click()
        directory = page.locator('#volume-directory')
        previous = directory.input_value()
        directory.fill(str(root))
        directory.press('Enter')
        rows=page.locator('#volume-files tbody tr')
        expect(rows).to_have_count(30)
        file_row(page,last).click()
        expect(directory).to_have_value(str(root))
        expect(page.locator('#volume-file-details')).to_contain_text('Directory')
        page.locator('#volume-files thead th').filter(has_text='Name').click()
        expect(rows.first).to_contain_text(last.name)
        file_row(page,last).dblclick()
        expect(directory).to_have_value(str(last))
        page.get_by_role('button',name='Parent directory',exact=True).click()
        expect(directory).to_have_value(str(root))
        file_row(page,last).click()
        file_row(page,last).press('Enter')
        expect(directory).to_have_value(str(last))
        directory.fill(str(root))
        directory.press('Enter')
        file_row(page,last).click()
        page.get_by_role('button',name='Open',exact=True).click()
        expect(directory).to_have_value(str(last))
        directory.fill(previous)
        directory.press('Enter')
        page.get_by_role('button',name='Cancel',exact=True).click()
    print('File selection, sorting, double-click, Enter and path navigation passed.',flush=True)


def check_projects(page):
    """Create a project from TIFF import, switch samples and reopen the manifest."""
    import json
    import numpy as np
    import tifffile
    from tomoswaxs.volumes import import_tiff
    with tempfile.TemporaryDirectory(prefix='nim-project-check-') as folder:
        root=Path(folder)
        source=root/'source.tif'
        tifffile.imwrite(source,np.arange(32**3,dtype='uint16').reshape(32,32,32),metadata={'axes':'ZYX'})
        second=import_tiff(source,root/'second.ome.zarr',100)
        page.get_by_role('button',name='Open volume',exact=True).click()
        page.locator('#volume-directory').fill(str(root))
        page.locator('#volume-directory').press('Enter')
        file_row(page,source).click()
        page.get_by_role('spinbutton',name='Pixel size X (µm)',exact=True).fill('100')
        page.get_by_role('button',name='Create new project',exact=True).click()
        page.get_by_role('button',name='Choose project directory',exact=True).click()
        page.locator('#volume-directory').fill(str(root))
        page.locator('#volume-directory').press('Enter')
        page.locator('#project-new-folder').fill('experiment')
        page.get_by_role('button',name='Create folder',exact=True).click()
        expect(page.locator('#volume-directory')).to_have_value(str(root/'experiment'))
        page.get_by_role('button',name='Use this directory',exact=True).click()
        expect(page.locator('#new-project-directory')).to_have_value(str(root/'experiment'))
        page.get_by_role('button',name='Create project',exact=True).click()
        expect(page.locator('.project-card')).not_to_be_visible()
        expect(page.locator('#volume-destination')).to_be_disabled()
        expect(page.get_by_role('spinbutton',name='Pixel size X (µm)',exact=True)).to_have_value('100')
        assert str(root/'experiment'/'data') in page.locator('#volume-destination').input_value()
        page.get_by_role('button',name='Open',exact=True).click()
        expect(page.locator('#volume-picker-title')).not_to_be_visible(timeout=60000)
        manifest=root/'experiment'/'project.json'
        expect(page.locator('.project-name')).to_have_text('experiment')
        first_id=json.loads(manifest.read_text())['active_sample_id']
        page.get_by_role('button',name='Sample settings',exact=True).click()
        page.locator('#sample-name').fill('First sample')
        page.get_by_role('button',name='Rename sample',exact=True).click()
        page.get_by_role('combobox',name='File direction for sample Y',exact=True).select_option('z')
        page.get_by_role('button',name='Close',exact=True).click()
        expect(page.locator('.sample-settings-card')).not_to_be_visible()
        page.locator('#coord-x-number').fill('150')
        page.locator('#coord-x-number').press('Tab')
        page.wait_for_function("window.trame.state.get('beam_x')===150")
        page.get_by_role('button',name='Saved views',exact=True).click()
        page.get_by_role('menuitem',name='Save current view…',exact=True).click()
        page.locator('#saved-view-name').fill('Beam intersection')
        page.get_by_role('button',name='Save',exact=True).click()
        expect(page.locator('.saved-view-card')).not_to_be_visible()
        page.locator('#coord-x-number').fill('200')
        page.locator('#coord-x-number').press('Tab')
        page.get_by_role('button',name='Saved views',exact=True).click()
        page.get_by_role('menuitem',name='Beam intersection',exact=True).click()
        expect(page.locator('#coord-x-number')).to_have_value('150')
        first=next(sample for sample in json.loads(manifest.read_text())['samples'] if sample['id']==first_id)
        assert first['saved_views'][0]['name']=='Beam intersection'
        page.get_by_role('button',name='Add sample',exact=True).click()
        file_row(page,second).click()
        page.get_by_role('button',name='Open',exact=True).click()
        expect(page.locator('#volume-picker-title')).not_to_be_visible()
        page.get_by_role('combobox',name='Active sample',exact=True).select_option(first_id)
        expect(page.get_by_role('combobox',name='Active sample',exact=True)).to_be_enabled()
        expect(page.locator('#coord-x-number')).to_have_value('150')
        page.locator('#open-project').click()
        page.get_by_role('menuitem',name='Close project',exact=True).click()
        expect(page.locator('.project-card')).not_to_be_visible()
        expect(page.locator('.project-name')).to_have_text('Standalone inspection')
        page.locator('#open-project').click()
        page.get_by_role('menuitem',name='Open project…',exact=True).click()
        page.locator('#open-project-path').fill(str(manifest))
        page.get_by_role('button',name='Open project',exact=True).click()
        expect(page.locator('.project-card')).not_to_be_visible()
        expect(page.get_by_role('combobox',name='Active sample',exact=True)).to_be_enabled()
        expect(page.locator('#coord-x-number')).to_have_value('150')
        page.get_by_role('button',name='Sample settings',exact=True).click()
        expect(page.get_by_role('combobox',name='File direction for sample Y',exact=True)).to_have_value('z')
        page.get_by_role('button',name='Close',exact=True).click()
        expect(page.locator('.sample-settings-card')).not_to_be_visible()
        page.locator('#open-project').click()
        page.get_by_role('menuitem',name='Close project',exact=True).click()
        expect(page.locator('.project-card')).not_to_be_visible()
        page.get_by_role('button',name='Add to project',exact=True).click()
        page.get_by_role('button',name='Add to existing project',exact=True).click()
        page.locator('#open-project-path').fill(str(manifest))
        page.get_by_role('button',name='Open project',exact=True).click()
        expect(page.locator('.project-card')).not_to_be_visible()
        expect(page.locator('#coord-x-number')).to_have_value('150')
        assert len(json.loads(manifest.read_text())['samples'])==3
        page.locator('#open-project').click()
        page.get_by_role('menuitem',name='Close project',exact=True).click()
        expect(page.locator('.project-card')).not_to_be_visible()
        assert not (second/'nim-view.json').exists()
    print('Project creation, TIFF import, sample switching and reopening passed.',flush=True)


def check(url, artifacts, volume=None, import_output=None, dataset=None):
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        def response_error(response):
            # The standalone Trame client probes for a launcher before connecting
            # directly over WebSocket. A standalone server rejects that POST.
            launcher_probe = (response.status == 405 and response.request.method == 'POST'
                              and urlparse(response.url).path == '/paraview/')
            if response.status >= 400 and not launcher_probe:
                errors.append(f'HTTP {response.status}: {response.url}')
        page.on('response', response_error)
        page.set_default_timeout(30000)
        try:
            page.goto(url)
            page.wait_for_function("window.trame?.state && window.nimCoordinates && document.querySelectorAll('.js-plotly-plot').length === 2")
            page.wait_for_function("[...document.querySelectorAll('.js-plotly-plot')].every(p => p.data?.length)")
            page.wait_for_function("[...document.querySelectorAll('#volume-interaction canvas')].some(c => c.width > 0 && c.height > 0)")
            # VTK's remote view can display the received frame as an image or canvas.
            page.wait_for_function(SCENE_RENDERED)
            print('Volume and plots rendered.', flush=True)
            original = page.locator('.js-plotly-plot').first.evaluate('(p) => JSON.stringify(p.data[0].y)')
            page.locator('#coord-x-number').fill('450')
            page.locator('#coord-x-number').press('Tab')
            page.wait_for_function("window.trame.state.get('beam_x') === 450")
            page.wait_for_function("(before) => JSON.stringify(document.querySelector('.js-plotly-plot').data[0].y) !== before", arg=original)
            page.locator('#coord-angle-number').fill('185')
            page.locator('#coord-angle-number').press('Tab')
            page.wait_for_function("window.trame.state.get('angle') === -175")
            # Keyboard interaction with each actual range input.
            for field, canonical in [('x', 'beam_x'), ('y', 'beam_y'), ('angle', 'angle')]:
                before = page.evaluate('(key) => window.trame.state.get(key)', canonical)
                page.locator(f'#coord-{field}-range').focus()
                page.locator(f'#coord-{field}-range').press('ArrowRight')
                page.wait_for_function('([key,before]) => window.trame.state.get(key) !== before', arg=[canonical, before])
            page.get_by_role('button', name='Play', exact=True).click()
            page.wait_for_function("window.trame.state.get('rotation_playing') === true")
            angle = page.evaluate("window.trame.state.get('angle')")
            page.wait_for_function('(angle) => window.trame.state.get("angle") !== angle', arg=angle)
            page.get_by_role('button', name='Pause', exact=True).click()
            page.wait_for_function("window.trame.state.get('rotation_playing') === false")
            print('Coordinate controls and playback passed.', flush=True)
            page.get_by_role('button', name='Beam view', exact=True).click()
            box = page.locator('#volume-interaction').bounding_box()
            before = page.evaluate("[window.trame.state.get('beam_x'),window.trame.state.get('beam_y')]")
            page.keyboard.down('Alt')
            page.keyboard.down('Shift')
            page.mouse.move(box['x']+box['width']*.5, box['y']+box['height']*.5)
            page.mouse.down()
            page.mouse.move(box['x']+box['width']*.55, box['y']+box['height']*.55, steps=8)
            page.mouse.up()
            page.keyboard.up('Shift')
            page.keyboard.up('Alt')
            page.wait_for_function('before => JSON.stringify([window.trame.state.get("beam_x"),window.trame.state.get("beam_y")]) !== JSON.stringify(before)', arg=before)
            page.get_by_text('Beam size', exact=True).click()
            page.get_by_role('spinbutton', name='X radius (µm)', exact=True).fill('90')
            page.get_by_role('spinbutton', name='X radius (µm)', exact=True).press('Tab')
            page.wait_for_function("window.trame.state.get('radius_x') == 90")
            print('Beam drag and radius passed.', flush=True)
            page.get_by_role('button', name='Settings', exact=True).click()
            page.locator('#pref-theme').select_option('light')
            page.wait_for_function("document.documentElement.dataset.theme === 'light'")
            page.locator('#pref-scale').focus()
            page.locator('#pref-scale').press('ArrowRight')
            page.wait_for_function("window.trame.state.get('ui_text_scale') === 105")
            page.locator('#pref-layout').check()
            page.get_by_role('button', name='Close', exact=True).click()
            # Resize the dock grid and verify its serialized arrangement survives reload.
            expect(page.locator('.settings-dialog')).not_to_be_visible()
            previous=page.evaluate("JSON.stringify(JSON.parse(localStorage.getItem('nim-uct-saxs.preferences.v1')).layout.grid)")
            dividers=page.locator('.dock-workspace .dv-sash')
            divider=dividers.first.bounding_box()
            assert divider
            x,y=divider['x']+divider['width']/2,divider['y']+divider['height']/2
            page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+30,y+25,steps=6);page.mouse.up()
            page.wait_for_function("previous=>JSON.stringify(JSON.parse(localStorage.getItem('nim-uct-saxs.preferences.v1')).layout.grid)!==previous",arg=previous)
            saved=page.evaluate("JSON.parse(localStorage.getItem('nim-uct-saxs.preferences.v1')).layout")
            page.reload()
            page.wait_for_function("window.nimCoordinates && document.documentElement.dataset.theme === 'light'")
            expect(page.get_by_role('tab')).to_have_count(5)
            page.wait_for_function("saved=>JSON.stringify(window.nimWorkspace.currentLayout.grid)===JSON.stringify(saved.grid)",arg=saved)
            check_volume_controls(page)
            check_popouts(page)
            page.get_by_role('button', name='About', exact=True).click()
            expect(page.locator('#about-title')).to_be_visible()
            expect(page.locator('.dependency-item')).to_have_count(10)
            expect(page.locator('.infrastructure-logo')).to_have_count(3)
            page.get_by_text('MIT License', exact=True).click()
            expect(page.locator('.licence-text')).to_contain_text('Permission is hereby granted')
            for logo in page.locator('.infrastructure-logo').all():
                expect(logo).to_be_visible()
            page.get_by_role('button', name='Close', exact=True).click()
            if volume is not None:
                page.get_by_role('button',name='Open volume',exact=True).click()
                expect(page.locator('#volume-picker-title')).to_be_visible()
                page.locator('#volume-directory').fill(str(volume.parent))
                page.get_by_role('button',name='Refresh',exact=True).click()
                file_row(page,volume).click()
                if import_output is None:
                    raise ValueError('--volume requires --import-output for the TIFF import check')
                page.locator('#volume-destination').fill(str(import_output))
                page.get_by_role('spinbutton',name='Pixel size X (µm)',exact=True).fill('10')
                for axis in 'XYZ':
                    expect(page.get_by_role('spinbutton',name=f'Pixel size {axis} (µm)',exact=True)).to_have_value('10')
                page.get_by_role('button',name='Open',exact=True).click()
                page.wait_for_function('name => window.trame.state.get("volume_summary").includes(name)',arg=import_output.name,timeout=120000)
                expect(page.locator('#volume-picker-title')).not_to_be_visible()
                expect(page.locator('.project-name')).to_have_text('Standalone inspection')
                page.wait_for_function('window.trame.state.get("beam_limit_um") > 1600')
                # A physical position beyond the old synthetic-volume limits must work.
                page.locator('#coord-x-number').fill('2000')
                page.locator('#coord-x-number').press('Tab')
                page.wait_for_function('window.trame.state.get("beam_x") === 2000')
                print('TIFF import, explicit scale and expanded coordinates passed.',flush=True)
                dataset = import_output
            if dataset is not None:
                page.get_by_role('button',name='Open volume',exact=True).click()
                page.locator('#volume-directory').fill(str(dataset.parent))
                page.get_by_role('button',name='Refresh',exact=True).click()
                file_row(page,dataset).click()
                frame = page.locator('#volume-interaction img').get_attribute('src')
                page.get_by_role('button',name='Open',exact=True).click()
                expect(page.locator('#volume-picker-title')).not_to_be_visible(timeout=60000)
                page.wait_for_function('old => document.querySelector("#volume-interaction img").src !== old',arg=frame)
                page.wait_for_function(SCENE_RENDERED)
                expect(page.locator('.app-footer')).to_contain_text(dataset.name)
                print('OME-Zarr reopening passed.',flush=True)
            check_directory_navigation(page)
            check_projects(page)
            if errors:
                raise AssertionError('\n'.join(errors))
        except Exception:
            artifacts.mkdir(parents=True, exist_ok=True)
            context.tracing.stop(path=str(artifacts/'browser-trace.zip'))
            (artifacts/'browser-errors.txt').write_text('\n'.join(errors))
            raise
        else:
            context.tracing.stop()
            print('Browser checks passed.', flush=True)
        finally:
            context.close()
            browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8081')
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--volume',type=Path,help='Import this TIFF without pixel-size metadata at an explicitly entered test scale of 10 µm')
    parser.add_argument('--import-output',type=Path,help='New writable OME-Zarr destination for the TIFF check')
    parser.add_argument('--dataset',type=Path,help='Also reopen this OME-Zarr dataset')
    args = parser.parse_args()
    check(args.url,args.artifacts,args.volume.resolve() if args.volume else None,
          args.import_output.resolve() if args.import_output else None,
          args.dataset.resolve() if args.dataset else None)
