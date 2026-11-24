"""Conservative display bounds for the currently loaded scalar array."""
import math

import numpy as np


def transparent_crop(values, threshold):
    """ZYX slices, stopping at the first occupied plane on each face.

    A one-voxel transparent margin preserves linear interpolation. Nonfinite
    values are retained, and no absolute epsilon is applied to float data.
    """
    full=tuple(slice(0,n) for n in values.shape)
    if not np.isfinite(threshold):return full
    # Compare Python scalars without rounding the boundary to the array dtype.
    threshold=float(threshold)
    bounds=[]
    def occupied(axis,index):
        selection=[*bounds,*[slice(None)]*(3-len(bounds))];selection[axis]=index
        plane=values[tuple(selection)]
        maximum=plane.max().item()
        return bool(not math.isfinite(maximum) or maximum>threshold or
                    (values.dtype.kind=='f' and np.isneginf(plane.min())))
    for axis,n in enumerate(values.shape):
        lo=0
        while lo<n and not occupied(axis,lo):lo+=1
        if lo==n:
            return tuple(slice(0,min(2,size)) for size in values.shape)
        hi=n-1
        while hi>lo and not occupied(axis,hi):hi-=1
        bounds.append(slice(max(0,lo-1),min(n,hi+2)))
    return tuple(bounds)
