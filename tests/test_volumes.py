"""OME-Zarr round trips, bounded previews, pixel size and import failure paths."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest

import ngff_zarr as ngff
import numpy as np
import tifffile
from trame.app import get_server

from nim_ct_saxs.volumes import (VolumeSource, TiffBlocks, import_tiff, ImportCancelled,
                                directory_entries, tiff_spacing, import_pixel_size, replace_import_pixel_size)
from nim_ct_saxs.app import Demo


class VolumeChecks(unittest.TestCase):
    def fixture(self, folder, shape=(17,19,21)):
        source = np.linspace(-.02,.01,np.prod(shape),dtype=np.float32).reshape(shape)
        path=Path(folder)/'volume.tif'
        tifffile.imwrite(path,source,imagej=True,metadata={'axes':'ZYX'})
        return path,source

    def test_round_trip_preserves_values_and_anisotropic_coordinates(self):
        with tempfile.TemporaryDirectory() as folder:
            path,values=self.fixture(folder)
            out=import_tiff(path,Path(folder)/'image.ome.zarr',[10,11,12])
            source=VolumeSource(out)
            np.testing.assert_array_equal(source.read_region(np.s_[:,:,:]),values)
            np.testing.assert_allclose(source.spacing,[.01,.011,.012])
            np.testing.assert_allclose(source.origin,-(np.array(values.shape[::-1])-1)*source.spacing/2)
            self.assertGreater(len(source.images),1)
            fine=source.images[0]; coarse=source.images[1]
            for axis in 'xyz':
                self.assertAlmostEqual(coarse.scale[axis],2*fine.scale[axis])
                self.assertAlmostEqual(coarse.translation[axis],fine.translation[axis]+fine.scale[axis]/2)
            points=(np.array([0,3,7]),np.array([1,4,8]),np.array([2,5,9]))
            np.testing.assert_array_equal(source[points],values[points])

    def test_standalone_axis_edits_preserve_dataset(self):
        with tempfile.TemporaryDirectory() as folder:
            path,values=self.fixture(folder)
            output=import_tiff(path,Path(folder)/'image.zarr',10)
            settings=output/'nim-view.json'
            settings.write_text('{"rotation_axis":"z"}')
            before=settings.read_bytes()
            source=VolumeSource(output)
            app=Demo(get_server('test-read-only-axis',client_type='vue3'),volume=source.preview(1))
            self.assertEqual(app.state.rotation_axis,'z')
            with app.state:
                app.state.rotation_axis='x'
            app.rotation_axis_changed()
            self.assertEqual(settings.read_bytes(),before)
            self.assertTrue(app.persist_active())
            np.testing.assert_array_equal(source.read_region(np.s_[:,:,:]),values)

    def test_big_endian_tiff_pixels_and_pyramid_are_correct(self):
        with tempfile.TemporaryDirectory() as folder:
            for dtype in ('float32','uint16'):
                array=np.arange(70*71*72,dtype=dtype).reshape(70,71,72)
                path=Path(folder)/(dtype+'.tif')
                tifffile.imwrite(path,array,imagej=True,byteorder='>',metadata={'axes':'ZYX'})
                blocks=TiffBlocks(path)
                np.testing.assert_array_equal(blocks[np.s_[60:70,60:71,60:72]],array[60:70,60:71,60:72])
                source=VolumeSource(import_tiff(path,Path(folder)/(dtype+'.zarr'),10))
                np.testing.assert_array_equal(source.read_region(np.s_[:,:,:]),array)
                first=source.images[1].data.compute(scheduler='single-threaded')
                expected=array[:70,:70,:72].astype(float).reshape(35,2,35,2,36,2).mean(axis=(1,3,5))
                if dtype=='uint16':expected=np.floor(expected+.5)
                np.testing.assert_allclose(first,expected.astype(dtype))

    def test_preview_budget_and_source_remain_independent(self):
        with tempfile.TemporaryDirectory() as folder:
            path,values=self.fixture(folder,(97,91,85))
            out=import_tiff(path,Path(folder)/'image.ome.zarr',10)
            source=VolumeSource(out)
            preview=source.preview(1)
            self.assertLessEqual(preview.values.nbytes,1024**2)
            self.assertGreater(preview.level,0)
            self.assertEqual(source.shape,values.shape)
            self.assertTrue(np.all(preview.spacing > source.spacing))
            self.assertEqual(preview.values.dtype,values.dtype)

    def test_missing_scale_rejected_and_imagej_pixel_size_used(self):
        with tempfile.TemporaryDirectory() as folder:
            path,_=self.fixture(folder)
            self.assertIsNone(tiff_spacing(path))
            with self.assertRaisesRegex(ValueError,'Pixel size is missing'):
                import_tiff(path,Path(folder)/'missing.zarr')
            tifffile.imwrite(path,np.ones((8,9,10),dtype='float32'),imagej=True,
                             resolution=(2,4),metadata={'axes':'ZYX','unit':'um','spacing':3})
            np.testing.assert_allclose(tiff_spacing(path),[.5,.25,3])
            source=VolumeSource(import_tiff(path,Path(folder)/'scaled.zarr'))
            np.testing.assert_allclose(source.spacing,[.0005,.00025,.003])
            self.assertIsNone(import_pixel_size(source.path))
            override=import_tiff(path,Path(folder)/'override.zarr',1)
            self.assertIsNone(import_pixel_size(override))
            with self.assertRaises(ValueError):
                replace_import_pixel_size(override,2)

    def test_cancel_removes_partial_store_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            path,_=self.fixture(folder,(70,71,72))
            destination=Path(folder)/'image.zarr'
            cancel=threading.Event()
            def progress(text):
                if 'tasks in current level' in text:
                    cancel.set()
            with self.assertRaises(ImportCancelled):
                import_tiff(path,destination,10,cancel,progress)
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(folder).glob('.*.importing-*')),[])
            destination.mkdir(); (destination/'keep').write_text('original')
            with self.assertRaises(FileExistsError):
                import_tiff(path,destination,10)
            self.assertEqual((destination/'keep').read_text(),'original')

    def test_reject_rgb_and_invalid_scale(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'rgb.tif'
            tifffile.imwrite(path,np.zeros((8,9,3),dtype='uint8'),photometric='rgb')
            with self.assertRaisesRegex(ValueError,'scalar ZYX'):
                TiffBlocks(path)
            path,_=self.fixture(folder)
            for scale in (0,-1,float('nan'),float('inf')):
                with self.assertRaisesRegex(ValueError,'Pixel size'):
                    import_tiff(path,Path(folder)/'invalid.zarr',scale)

    def test_gui_import_and_failed_open_keep_previous_scene(self):
        with tempfile.TemporaryDirectory() as folder:
            path,source=self.fixture(folder)
            app=Demo(get_server('test-ngff-loading',client_type='vue3'),data_directory=Path(folder))
            with app.state:
                app.state.volume_selection=str(path)
            app.volume_selection_changed()
            with app.state:
                app.state.volume_voxel_x=1000
                app.state.volume_voxel_y=1000
                app.state.volume_voxel_z=1000
            asyncio.run(app._load_selected_volume())
            self.assertFalse(app.state.volume_error,app.state.volume_error)
            np.testing.assert_array_equal(app.volume,source)
            self.assertGreater(app.state.beam_limit_um,1600)
            app.receive_pose({'beam_x':2500},True)
            self.assertEqual(app.state.beam_x,2500)
            self.assertIsInstance(app.signal_volume,VolumeSource)
            self.assertIn('SYNTHETIC SAXS',app.state.data_notice)
            with app.state:
                app.state.volume_selection=str(Path(folder)/'missing.zarr')
            asyncio.run(app._load_selected_volume())
            self.assertTrue(app.state.volume_error)
            np.testing.assert_array_equal(app.volume,source)

    def test_open_rpc_returns_immediately_and_serialises_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            path,_=self.fixture(folder)
            output=import_tiff(path,Path(folder)/'image.zarr',10)
            app=Demo(get_server('test-background-open',client_type='vue3'))
            app.state.volume_selection=str(output)
            async def check():
                self.assertIsNone(app.open_selected_volume())
                job=app._volume_task
                self.assertFalse(job.done())
                self.assertIsNone(app.open_selected_volume())
                self.assertIs(app._volume_task,job)
                await job
                self.assertFalse(app.state.volume_error,app.state.volume_error)
            asyncio.run(check())

    def test_import_pixel_size_updates_every_level_without_changing_chunks(self):
        with tempfile.TemporaryDirectory() as folder:
            path,values=self.fixture(folder)
            output=import_tiff(path,Path(folder)/'image.ome.zarr',[2,3,4])
            source=VolumeSource(output)
            before=[source.geometry(image) for image in source.images]
            metadata=output/'zarr.json'
            before_stat=metadata.stat()
            files={p.relative_to(output):hashlib.sha256(p.read_bytes()).digest()
                   for p in output.rglob('*') if p.is_file() and p!=metadata}
            replace_import_pixel_size(output,[5,9,8])
            after=VolumeSource(output)
            for old,image in zip(before,after.images):
                scale,origin=after.geometry(image)
                np.testing.assert_allclose(scale,old[0]*[2.5,3,2])
                np.testing.assert_allclose(origin,old[1]*[2.5,3,2])
            np.testing.assert_array_equal(after.read_region(np.s_[:,:,:]),values)
            np.testing.assert_allclose(import_pixel_size(output),[5,9,8])
            self.assertEqual(files,{p.relative_to(output):hashlib.sha256(p.read_bytes()).digest()
                                   for p in output.rglob('*') if p.is_file() and p!=metadata})
            self.assertEqual(metadata.stat().st_ino,before_stat.st_ino)
            self.assertEqual(metadata.stat().st_uid,before_stat.st_uid)
            stable=metadata.read_bytes()
            for invalid in ([0,1,1],[1,float('nan'),1],[-1,2,3]):
                with self.assertRaises(ValueError):
                    replace_import_pixel_size(output,invalid)
                self.assertEqual(metadata.read_bytes(),stable)
            # Imports with an existing physical pixel size are outside this editor.
            doc=json.loads(stable)
            doc['attributes']['nim_import']['source_spacing_available']=True
            metadata.write_text(json.dumps(doc))
            self.assertIsNone(import_pixel_size(output))
            with self.assertRaises(ValueError):
                replace_import_pixel_size(output,[1,1,1])

    def test_sample_spacing_refresh_uses_cached_preview_and_survives_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            path,_=self.fixture(folder)
            output=import_tiff(path,Path(folder)/'image.ome.zarr',10)
            app=Demo(get_server('test-pixel-size-editor',client_type='vue3'),volume=VolumeSource(output).preview())
            cached=app.volume
            self.assertTrue(app.state.sample_pixel_size_editable)
            app.state.update(sample_voxel_x=3,sample_voxel_y=4,sample_voxel_z=5,angle=35)
            app.close_sample_settings()
            self.assertIs(app.volume,cached)
            self.assertEqual(app.state.angle,35)
            np.testing.assert_allclose(app.volume_source.spacing,[.003,.004,.005])
            np.testing.assert_allclose(app.mapper.GetInput().GetSpacing(),app.spacing)
            self.assertFalse(app.state.show_sample_settings)
            self.assertFalse(app.state.sample_settings_notice)
            metadata=output/'zarr.json'
            stamp=metadata.stat().st_mtime_ns
            app.close_sample_settings()
            self.assertEqual(metadata.stat().st_mtime_ns,stamp,'Closing without changes leaves metadata untouched')
            app.state.sample_voxel_x=0
            app.close_sample_settings()
            self.assertTrue(app.state.show_sample_settings)
            self.assertIn('positive',app.state.sample_settings_notice)
            self.assertEqual(metadata.stat().st_mtime_ns,stamp)
            reopened=VolumeSource(output)
            np.testing.assert_allclose(reopened.spacing,[.003,.004,.005])

    def test_directory_lists_zarr_as_image_and_tiff_as_import(self):
        with tempfile.TemporaryDirectory() as folder:
            path,_=self.fixture(folder)
            out=import_tiff(path,Path(folder)/'image.ome.zarr',10)
            _,entries=directory_entries(folder)
            by_name={entry['name']:entry for entry in entries}
            self.assertEqual(by_name[out.name]['kind'],'OME-Zarr volume')
            self.assertIsNone(by_name[out.name]['size'])
            self.assertEqual(by_name[path.name]['kind'],'TIFF volume')
            self.assertEqual(by_name[path.name]['size'],path.stat().st_size)
            self.assertEqual(by_name[path.name]['modified'],path.stat().st_mtime)
            self.assertIn('bytes',by_name[path.name]['size_detail'])

    def test_single_level_store_uses_bounded_stride_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            array=np.arange(128**3,dtype='float32').reshape(128,128,128)
            image=ngff.to_ngff_image(array,dims=('z','y','x'),scale=dict(x=2,y=3,z=4),
                                    translation=dict(x=7,y=8,z=9),axes_units=dict.fromkeys('xyz','micrometer'))
            multiscales=ngff.to_multiscales(image,scale_factors=[],chunks=32,cache=False)
            path=Path(folder)/'single.zarr'
            ngff.to_ome_zarr(path,multiscales,version='0.5')
            source=VolumeSource(path); preview=source.preview(1)
            self.assertEqual(preview.stride,2)
            self.assertLessEqual(preview.values.nbytes,1024**2)
            np.testing.assert_array_equal(preview.values,array[::2,::2,::2])
            np.testing.assert_allclose(preview.spacing,[.004,.006,.008])
            np.testing.assert_allclose(preview.origin,[.007,.008,.009])
            app=Demo(get_server('test-translated-source',client_type='vue3'),volume=preview)
            self.assertAlmostEqual(app.state.beam_x,134.)
            self.assertAlmostEqual(app.state.beam_y,198.5)

    def test_compressed_tiff_is_read_in_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'compressed.tif'
            array=np.arange(9*11*13,dtype='uint16').reshape(9,11,13)
            tifffile.imwrite(path,array,imagej=True,compression='deflate',metadata={'axes':'ZYX'})
            blocks=TiffBlocks(path)
            self.assertIsNone(blocks.offset)
            np.testing.assert_array_equal(blocks[np.s_[1:4,2:7,3:8]],array[1:4,2:7,3:8])
            source=VolumeSource(import_tiff(path,Path(folder)/'compressed.zarr',2))
            np.testing.assert_array_equal(source.read_region(np.s_[:,:,:]),array)

    def test_incomplete_import_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'incomplete'):
                VolumeSource(Path(folder)/'.image.zarr.importing-unfinished')

    def test_invalid_contrast_preserves_transfer_function(self):
        app=Demo(get_server('test-ngff-contrast',client_type='vue3'))
        before=app.transfer.GetRange()
        with app.state:
            app.state.contrast_high=app.state.contrast_low
        self.assertEqual(before,app.transfer.GetRange())
