"""Explicit in-memory sample for tests that exercise loaded-sample controls."""
import numpy as np
from tomoswaxs.app import Demo as Application
from tomoswaxs.volume_viewing import array_source


def Demo(*args,**kwargs):
    kwargs.setdefault('render_device','system')
    app=Application(*args,**kwargs)
    if kwargs.get('volume') is None:
        app.volume=np.zeros((160,160,160),dtype=np.uint16)
        app.spacing=.02;app.origin=np.full(3,-1.59)
        app._empty_source=array_source(app.volume,app.spacing,app.origin)
        app.state.update(has_sample=True,has_volume=True,sample_name='Test sample')
        app.sync_volume_controls();app.set_image_data();app.reset_camera();app.update_scene()
    return app
