"""Bounded decoded Dask blocks for repeated, overlapping volume reads."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from itertools import product
import threading

import dask
from dask.optimization import cull
import numpy as np


class DecodedChunkCache:
    def __init__(self):
        self._lock=threading.Lock()
        self._chunks=OrderedDict()
        self.limit=0
        self.nbytes=0
        self.epoch=0

    def resize(self, limit):
        with self._lock:
            self.limit=max(0,int(limit))
            self._evict()

    def clear(self):
        with self._lock:
            self.epoch+=1
            self._chunks.clear()
            self.nbytes=0

    def _evict(self):
        while self._chunks and self.nbytes>self.limit:
            _,value=self._chunks.popitem(last=False)
            self.nbytes-=value.nbytes

    def get(self, key, epoch):
        with self._lock:
            if epoch!=self.epoch:return None
            value=self._chunks.pop(key,None)
            if value is not None:self._chunks[key]=value
            return value

    def put(self, key, value, epoch):
        with self._lock:
            if epoch!=self.epoch or value.nbytes>self.limit:return
            old=self._chunks.pop(key,None)
            if old is not None:self.nbytes-=old.nbytes
            self._chunks[key]=value
            self.nbytes+=value.nbytes
            self._evict()

    def read(self, data, selection, identity, cancel, working_bytes):
        """Assemble selected voxels; only a bounded number of blocks are in flight.

        Use public Dask block access, preserving ngff-zarr's reader and geometry.
        Completed blocks remain reusable even if the requesting view is obsolete.
        """
        from .volumes import ImportCancelled

        epoch=self.epoch
        offsets=[np.r_[0,np.cumsum(chunks)] for chunks in data.chunks]
        indices=[range(int(np.searchsorted(edges,s.start,side='right')-1),
                       int(np.searchsorted(edges,s.stop-1,side='right')))
                 for edges,s in zip(offsets,selection)]
        result=np.empty(tuple(len(range(s.start,s.stop,s.step or 1)) for s in selection),dtype=data.dtype)

        def check():
            if cancel is not None and cancel.is_set():raise ImportCancelled('Load cancelled.')

        def fetch(index):
            check()
            key=(identity,index)
            value=self.get(key,epoch)
            if value is None:
                task=tasks[tuple(i-a for i,a in zip(index,starts))]
                # Cull once per block from the already optimized region graph,
                # rather than optimizing the entire source pyramid per miss.
                graph,_=cull(task.dask,[task.key])
                value=dask.get(graph,task.key)
                self.put(key,value,epoch)
            check()
            return index,value

        def copy(index,value):
            src=[];dst=[]
            for axis,(i,s) in enumerate(zip(index,selection)):
                step=s.step or 1
                lo=max(s.start,int(offsets[axis][i]))
                lo=s.start+((lo-s.start+step-1)//step)*step
                hi=min(s.stop,int(offsets[axis][i+1]))
                src.append(slice(lo-int(offsets[axis][i]),hi-int(offsets[axis][i]),step))
                dst.append(slice((lo-s.start)//step,(hi-s.start+step-1)//step))
            result[tuple(dst)]=value[tuple(src)]

        missing=[]
        for index in product(*indices):
            check()
            # Skip blocks with no selected voxel when stride exceeds chunk size.
            if any(s.start+max(0,(int(edges[i])-s.start+(s.step or 1)-1)//(s.step or 1))*(s.step or 1)
                   >=min(s.stop,int(edges[i+1])) for edges,i,s in zip(offsets,index,selection)):
                continue
            value=self.get((identity,index),epoch)
            if value is None:missing.append(index)
            else:copy(index,value)
        if not missing:return result
        starts=tuple(min(i[a] for i in missing) for a in range(data.ndim))
        stops=tuple(max(i[a] for i in missing)+1 for a in range(data.ndim))
        tasks=data.blocks[tuple(slice(a,b) for a,b in zip(starts,stops))].to_delayed()
        chunk_bytes=int(np.prod(data.chunksize))*data.dtype.itemsize
        workers=min(4,max(1,int(working_bytes)//max(1,chunk_bytes)))
        jobs=iter(missing)
        with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='volume-chunk') as pool:
            pending=set()
            try:
                for _ in range(workers):
                    index=next(jobs,None)
                    if index is not None:pending.add(pool.submit(fetch,index))
                while pending:
                    check()
                    done,pending=wait(pending,return_when=FIRST_COMPLETED)
                    for future in done:
                        index,value=future.result()
                        copy(index,value)
                        index=next(jobs,None)
                        if index is not None:pending.add(pool.submit(fetch,index))
                check()
            finally:
                for future in pending:future.cancel()
        return result
