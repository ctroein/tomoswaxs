"""Decoded reuse preserves selected values and honours memory/cancellation."""
import threading
import unittest

import dask.array as da
import numpy as np

from tomoswaxs.volume_cache import DecodedChunkCache
from tomoswaxs.volumes import ImportCancelled


class Reader:
    def __init__(self,values):
        self.values=values
        self.shape=values.shape;self.dtype=values.dtype;self.ndim=values.ndim
        self.reads=0
        self.cancel=None
        self.lock=threading.Lock()

    def __getitem__(self,key):
        with self.lock:self.reads+=1
        if self.cancel:self.cancel.set()
        return self.values[key]


class VolumeCacheChecks(unittest.TestCase):
    def test_overlap_stride_edges_and_source_identity(self):
        values=np.arange(21*23*25,dtype='>f4').reshape(21,23,25)
        values[8,9,10]=np.nan
        reader=Reader(values)
        data=da.from_array(reader,chunks=(7,8,9),asarray=False,meta=np.empty((0,0,0),dtype=values.dtype))
        cache=DecodedChunkCache();cache.resize(2**20)
        first=(slice(2,19),slice(3,22),slice(4,24))
        a=cache.read(data,first,('a',0),None,2**20)
        np.testing.assert_array_equal(a,values[first]);count=reader.reads
        for step in (1,2,11):
            selection=tuple(slice(s.start+1,s.stop-1,step) for s in first)
            b=cache.read(data,selection,('a',0),None,2**20)
            np.testing.assert_array_equal(b,values[selection])
        self.assertEqual(reader.reads,count,'Overlapping requests should reuse decoded blocks')
        cache.read(data,first,('b',0),None,2**20)
        self.assertGreater(reader.reads,count)
        self.assertLessEqual(cache.nbytes,cache.limit)

    def test_eviction_resize_and_old_work_cannot_repopulate_after_clear(self):
        cache=DecodedChunkCache();cache.resize(16)
        epoch=cache.epoch;v=np.ones(2,dtype=np.float32)
        cache.put('a',v,epoch);cache.put('b',v,epoch)
        cache.get('a',epoch);cache.put('c',v,epoch)
        self.assertIsNone(cache.get('b',epoch))
        cache.resize(8);self.assertEqual(cache.nbytes,8)
        cache.clear();cache.put('late',v,epoch)
        self.assertEqual(cache.nbytes,0)
        cache.put('too-large',np.ones(10),cache.epoch)
        self.assertEqual(cache.nbytes,0)

    def test_cancel_retains_completed_block_and_does_not_read_more(self):
        reader=Reader(np.zeros((12,12,12),dtype=np.uint16))
        data=da.from_array(reader,chunks=6,asarray=False,meta=np.empty((0,0,0),dtype=np.uint16))
        cache=DecodedChunkCache();cache.resize(2**20)
        reader.cancel=threading.Event()
        with self.assertRaises(ImportCancelled):
            cache.read(data,(slice(0,12),)*3,'a',reader.cancel,1)
        self.assertEqual(reader.reads,1)
        self.assertEqual(cache.nbytes,6**3*2)
