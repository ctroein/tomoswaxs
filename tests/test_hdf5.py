import tempfile
import threading
import unittest
from pathlib import Path
import h5py
import numpy as np
from tomoswaxs.volumes import Hdf5Blocks,hdf5_volumes,hdf5_spacing,hdf5_axes,import_hdf5,VolumeSource,ImportCancelled

class Hdf5Checks(unittest.TestCase):
    def test_block_reads_axis_mapping_and_conversion_preserve_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.h5';out=Path(folder)/'image.ome.zarr'
            values=np.arange(8*10*12,dtype='float32').reshape(8,10,12)-100
            with h5py.File(path,'w') as f:
                f['data/recon_abs']=values
                f['metadata/pixel_size_cm']=6.5e-5
                f['metadata/unrelated']=42
                f['metadata/reconstructed_vol_dimensions_Z(number-of-slices)_X(width)_Y(height)']='(8, 10, 12)'
            stamp=path.stat().st_mtime_ns
            self.assertEqual(len(hdf5_volumes(path)),1)
            self.assertEqual(hdf5_axes(path),'zxy')
            np.testing.assert_allclose(hdf5_spacing(path),[.65]*3)
            blocks=Hdf5Blocks(path,'/data/recon_abs','zxy')
            np.testing.assert_array_equal(blocks[(slice(1,3),slice(2,5),slice(3,7))],values[1:3,3:7,2:5].transpose(0,2,1))
            messages=[]
            import_hdf5(path,out,'/data/recon_abs',axes='zxy',progress=messages.append)
            stages=[m for m in messages if m.startswith('Writing resolution level')]
            self.assertEqual(stages,['Writing resolution level 1 of 2 (full resolution)','Writing resolution level 2 of 2'])
            self.assertEqual(messages[-2:],['Validating converted image…','Import complete.'])
            source=VolumeSource(out)
            np.testing.assert_array_equal(source.images[0].data.compute(),values.transpose(0,2,1))
            np.testing.assert_allclose(source.spacing,[.00065]*3)
            self.assertEqual(path.stat().st_mtime_ns,stamp)
            with self.assertRaises(FileExistsError):import_hdf5(path,out,'/data/recon_abs')

    def test_missing_spacing_multiple_choices_and_cancellation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.h5';out=Path(folder)/'image.ome.zarr'
            with h5py.File(path,'w') as f:
                f['first']=np.ones((8,8,8));f['second']=np.zeros((8,8,8))
            self.assertEqual(len(hdf5_volumes(path)),2)
            self.assertIsNone(hdf5_spacing(path))
            with self.assertRaisesRegex(ValueError,'Pixel size'):import_hdf5(path,out,'/first')
            cancel=threading.Event()
            def progress(_):cancel.set()
            with self.assertRaises(ImportCancelled):import_hdf5(path,out,'/first',[1,2,3],cancel,progress)
            self.assertFalse(out.exists())
            self.assertFalse(list(Path(folder).glob('.*.importing-*')))
