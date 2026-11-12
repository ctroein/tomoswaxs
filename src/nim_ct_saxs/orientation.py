"""Image-to-laboratory orientation shared by rendering and ray sampling."""
import numpy as np


def sample_rotation(axis='y', angle_deg=0.):
    """Align the selected image axis with lab +Y, then rotate about lab Y."""
    alignments = {
        'x': [[0,-1,0], [1,0,0], [0,0,1]],
        'y': np.eye(3),
        'z': [[1,0,0], [0,0,1], [0,-1,0]],
    }
    if axis not in alignments:
        raise ValueError('Rotation axis must be X, Y or Z.')
    t = np.deg2rad(angle_deg)
    rotation = np.array([[np.cos(t),0,np.sin(t)], [0,1,0], [-np.sin(t),0,np.cos(t)]])
    return rotation @ np.asarray(alignments[axis])
