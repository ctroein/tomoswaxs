"""Conservative display bounds for the currently loaded scalar array."""
import math

import numpy as np


def transparent_crop(values, threshold, *, empty_none=False):
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
            if empty_none:return None
            return tuple(slice(0,min(2,size)) for size in values.shape)
        hi=n-1
        while hi>lo and not occupied(axis,hi):hi-=1
        bounds.append(slice(max(0,lo-1),min(n,hi+2)))
    return tuple(bounds)


def refine_preview(volume, budget_mib, threshold, cancel=None, cache=None):
    """Choose once from coarse bounds; never inspect the refined array again."""
    from .volumes import ImportCancelled
    if cancel is not None and cancel.is_set():raise ImportCancelled('Load cancelled.')
    selection=transparent_crop(volume.values,threshold,empty_none=True)
    volume.display_threshold=float(threshold)
    volume.display_selection=selection if selection is not None else tuple(slice(0,min(2,n)) for n in volume.values.shape)
    if selection is None:return volume
    if all(s.start==0 and s.stop==n for s,n in zip(selection,volume.values.shape)):
        return volume
    source=volume.source
    # Map the retained coarse cells (including their margin) through physical
    # cell edges. This handles anisotropic spacing and translated NGFF levels.
    low=volume.origin+(np.array([s.start for s in selection][::-1])-.5)*volume.spacing
    high=volume.origin+(np.array([s.stop for s in selection][::-1])-.5)*volume.spacing
    start=np.floor((low-source.origin)/source.spacing+.5+1e-8).astype(int)
    stop=np.ceil((high-source.origin)/source.spacing+.5-1e-8).astype(int)
    crop=tuple((max(a,int(c)),min(b,int(d))) for (a,b),c,d in zip(volume.crop,start,stop))
    if any(a>=b for a,b in crop):return volume
    options=source.level_options(budget_mib,crop)
    target=next((o for o in options if o['fits'] and
                 np.all(np.asarray(o['spacing'])<=volume.spacing*(1+1e-8)) and
                 np.any(np.asarray(o['spacing'])<volume.spacing*(1-1e-8))),None)
    if target is None:return volume
    if cancel is not None and cancel.is_set():raise ImportCancelled('Load cancelled.')
    finer=source.preview(budget_mib,cancel,crop,target['level'],cache=cache,contrast=volume.contrast)
    # crop describes the coverage tested at the base level, including discarded
    # transparent margins. Do not narrow the user's crop or recursively refine.
    finer.crop=volume.crop
    finer.requested_level=volume.requested_level
    finer.display_threshold=float(threshold)
    finer.display_selection=tuple(slice(0,n) for n in finer.values.shape)
    finer.refined_from=volume.level
    finer.refinement_crop=crop
    finer.refinement_spacing=tuple(volume.spacing)
    return finer
