"""Geometry checks for the isolated mixed-resolution rendering experiment."""
from copy import copy
import unittest

import numpy as np
from vtk.util.numpy_support import vtk_to_numpy

from tools.brick_rendering import partition_boxes, brick_order, Brick, physical_crop
from tomoswaxs.volume_viewing import array_source


class BrickChecks(unittest.TestCase):
    def test_bsp_order_puts_near_outer_slab_last(self):
        for axis in range(3):
            for sign,side in [(-1,0),(1,1)]:
                eye=np.zeros(3);eye[axis]=sign*4
                order=brick_order(eye,[-1]*3,[1]*3)
                self.assertEqual(sorted(order),list(range(7)))
                self.assertEqual(order[-1],axis*2+side)

    def test_regions_cover_every_cell_exactly_once(self):
        shape=(13,15,17);core=((3,10),(4,11),(5,12))
        counts=np.zeros(shape,dtype=np.uint8)
        for box in partition_boxes(shape,core):counts[tuple(slice(a,b) for a,b in box)]+=1
        np.testing.assert_array_equal(counts,np.ones(shape,dtype=np.uint8))
        with self.assertRaises(ValueError):partition_boxes(shape,((0,10),(4,11),(5,12)))

    def test_cell_geometry_preserves_centres_and_boundary_faces(self):
        values=np.arange(4*5*6,dtype=np.float32).reshape(4,5,6)
        brick=Brick(values,np.array([.2,.3,.4]),np.array([-1.,-2.,-3.]))
        image=brick.image()
        self.assertEqual(image.GetDimensions(),(7,6,5))
        np.testing.assert_allclose(image.GetBounds(),[-1,.2,-2,-.5,-3,-1.4])
        np.testing.assert_array_equal(vtk_to_numpy(image.GetCellData().GetScalars()),values.ravel())

    def test_nested_levels_share_bit_identical_faces(self):
        origin=np.array([-.8762,-.8762,-.482625])
        coarse=Brick(np.ones((4,4,6),dtype=np.float32),np.full(3,.0052),origin,origin)
        fine=Brick(np.ones((8,8,8),dtype=np.float32),np.full(3,.0026),origin+[6*.0052,0,0],origin)
        self.assertEqual(coarse.image().GetBounds()[1],fine.image().GetBounds()[0])

    def test_level_offsets_are_used_and_non_nested_edges_are_rejected(self):
        source=array_source(np.zeros((12,16,20),dtype=np.uint16),.1,np.zeros(3))
        coarse=copy(source.images[0]);coarse.data=coarse.data[::2,::2,::2]
        coarse.scale=dict.fromkeys('xyz',.2);coarse.translation=dict.fromkeys('xyz',.05)
        source.images.append(coarse)
        crop,faces=physical_crop(source,1,((1,4),(2,6),(1,5)))
        self.assertEqual(crop,((2,8),(4,12),(2,10)))
        coarse.translation['x']=.08
        with self.assertRaisesRegex(ValueError,'nested'):physical_crop(source,1,((1,4),(2,6),(1,5)))
