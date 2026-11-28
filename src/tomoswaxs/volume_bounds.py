"""Conservative display bounds for the currently loaded scalar array."""
import math

import numpy as np


def transparent_crop(values, threshold, *, empty_none=False, cancel=None):
    """ZYX slices, stopping at the first occupied plane on each face.

    A one-voxel transparent margin preserves linear interpolation. Nonfinite
    values are retained, and no absolute epsilon is applied to float data.
    """
    _check_cancel(cancel)
    full=tuple(slice(0,n) for n in values.shape)
    if not np.isfinite(threshold):return full
    # Compare Python scalars without rounding the boundary to the array dtype.
    threshold=float(threshold)
    bounds=[]
    def occupied(axis,index):
        _check_cancel(cancel)
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


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        from .volumes import ImportCancelled
        raise ImportCancelled('Load cancelled.')


def refine_preview(volume, budget_mib, threshold, cancel=None, cache=None):
    """Recheck each array and load the finest fitting level until no gain remains."""
    source=volume.source
    original_crop=volume.crop;requested=volume.requested_level
    base_spacing=tuple(volume.spacing);base_level=volume.level
    coverage=volume.refinement_crop or original_crop
    history=[(volume.level,volume.stride)]
    while True:
        _check_cancel(cancel)
        selection=transparent_crop(volume.values,threshold,empty_none=True,cancel=cancel)
        volume.display_threshold=float(threshold)
        volume.display_selection=selection if selection is not None else tuple(slice(0,min(2,n)) for n in volume.values.shape)
        if selection is None:
            volume.refinement_stop='empty';return volume
        # Map retained cells, including their interpolation margin, to the
        # full-resolution frame. Coverage only shrinks; the manual crop stays.
        low=volume.origin+(np.array([s.start for s in selection][::-1])-.5)*volume.spacing
        high=volume.origin+(np.array([s.stop for s in selection][::-1])-.5)*volume.spacing
        start=np.floor((low-source.origin)/source.spacing+.5+1e-8).astype(int)
        stop=np.ceil((high-source.origin)/source.spacing+.5-1e-8).astype(int)
        crop=tuple((max(a,int(c)),min(b,int(d))) for (a,b),c,d in zip(coverage,start,stop))
        if any(a>=b for a,b in crop):
            volume.refinement_stop='empty';return volume
        options=source.level_options(budget_mib,crop)
        finer_options=[o for o in options
                       if np.all(np.asarray(o['spacing'])<=volume.spacing*(1+1e-8))
                       and np.any(np.asarray(o['spacing'])<volume.spacing*(1-1e-8))]
        target=next((o for o in finer_options if o['fits']),None)
        if target is None:
            volume.refinement_stop='limit' if finer_options else 'finest'
            return volume
        _check_cancel(cancel)
        finer=source.preview(budget_mib,cancel,crop,target['level'],cache=cache,contrast=volume.contrast)
        _check_cancel(cancel)
        history.append((finer.level,finer.stride))
        finer.crop=original_crop;finer.requested_level=requested
        finer.refined_from=base_level
        finer.refinement_history=tuple(history)
        finer.refinement_crop=crop
        # Absence outside the final read was first tested at the base spacing.
        # Keep that conservative coverage bound for Auto detail reuse checks.
        finer.refinement_spacing=base_spacing
        volume=finer;coverage=crop
