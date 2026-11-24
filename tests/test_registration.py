import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import h5py
import numpy as np
from tomoswaxs.registration import initial_placement,positions,angles,motor_rows,stack_rows,rotation_warning
from tomoswaxs.orientation import sample_transform,sample_rotation
from tomoswaxs.scattering_data import MeasurementIndex

class RegistrationChecks(unittest.TestCase):
    def scan(self,root,y=-2.12355,tab_y=-40.70906):
        x=np.tile(np.linspace(-3100,-1000,421),51)
        index=MeasurementIndex(x,np.full(len(x),y*1000),np.repeat(np.linspace(90,270,51),421),np.linspace(-3100,-1000,421),np.linspace(90,270,51))
        return SimpleNamespace(path=Path(root)/'Scattering data'/'scan-0135_eiger_integrated.h5',metadata=Path('scan-0135.h5'),index=index,
            start_positioners=dict(tab_x=-2.098675,tab_y=tab_y,swaxs_x=-.005,swaxs_y=y,tomo_xf=1.304455,tomo_zf=-.4986))

    def test_bundle_reference_stage_contributions_and_sparse_y_share_one_origin(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'Metadata_CT';folder.mkdir()
            reference=dict(tab_x=-2.97059,tab_y=-36.7157025,swaxs_x=-.2487,swaxs_y=-5.85325,tomo_xf=1.304495,tomo_zf=-.48242)
            with h5py.File(folder/'Radiographs.h5','w') as f:
                for key,value in reference.items():f['entry/instrument/start_positioners/'+key]=value
            scan=self.scan(root)
            mapping=initial_placement([scan])
            self.assertEqual(mapping['model'],'stack')
            x,y=positions(scan,mapping)
            self.assertAlmostEqual(x[210],-423.075)
            self.assertAlmostEqual(y[0],-129.7575)
            other=self.scan(root,-2.0465,-40.709015)
            _,other_y=positions(other,mapping)
            self.assertAlmostEqual(other_y[0]-y[0],77.095)
            # Loading only another Y scan must retain the CT reference and beam shift.
            m2=initial_placement([other]);np.testing.assert_allclose(positions(other,m2)[1],other_y)
            mapping['motors'][0]['x']=-1
            self.assertAlmostEqual(positions(scan,mapping)[0][210]-x[210],-2*(reference['tab_x']*-1+scan.start_positioners['tab_x'])*1000)
            mapping['angle_offset']=15
            self.assertAlmostEqual(angles(scan,mapping)[0],105)
            self.assertAlmostEqual(angles(scan,mapping)[-1],-75)
            mapping['angle_sign']=-1
            self.assertAlmostEqual(angles(scan,mapping)[0],-75)

    def test_motor_coefficients_and_unknown_fine_axis_are_explicit_parameters(self):
        scan=self.scan('/unused')
        m=initial_placement([scan]);m.update(model='motors',motors=motor_rows(scan.start_positioners),camera_x=0.,camera_y=0.)
        # Snapshot swaxs_x is deliberately outside the scan: per-frame positions must win.
        x,y=positions(scan,m)
        self.assertAlmostEqual(x[0],-3095)
        row=next(r for r in m['motors'] if r['name']=='tomo_zf')
        row.update(reference=-.5,x=2,y=-1)
        xx,yy=positions(scan,m)
        np.testing.assert_allclose(xx-x,2.8,atol=1e-10)
        np.testing.assert_allclose(yy-y,-1.4,atol=1e-10)

    def test_upper_stage_deltas_rotate_but_lower_stage_deltas_do_not(self):
        scan=self.scan('/unused')
        reference=dict(scan.start_positioners,tomo_xf=1.3,tomo_zf=-.5)
        m=initial_placement([scan],discover=False)
        m.update(model='stack',motors=stack_rows(reference))
        x,y=positions(scan,m)
        lower=np.tile(scan.index.nominal_x_um,51)-scan.start_positioners['swaxs_x']*1000
        np.testing.assert_allclose(x.reshape(51,421)[0]-lower[:421],4.455,atol=1e-9)
        np.testing.assert_allclose(x.reshape(51,421)[25]-lower[:421],-1.4,atol=1e-9)
        np.testing.assert_allclose(x.reshape(51,421)[50]-lower[:421],-4.455,atol=1e-9)
        np.testing.assert_allclose(y,0,atol=1e-9)
        # A display angle convention does not change mechanical stage angles.
        m.update(angle_offset=17,angle_sign=-1)
        np.testing.assert_array_equal(positions(scan,m)[0],x)

    def test_ct_stays_centred_and_rotates_about_viewer_y(self):
        for axis in 'xyz':
            alignment=sample_rotation(axis,0)
            for angle in (0,37,90,180,270):
                matrix=sample_transform(axis,angle)
                np.testing.assert_array_equal(matrix[:3,3],0)
                np.testing.assert_allclose(matrix[:3,:3] @ alignment.T @ [0,1,0],[0,1,0],atol=1e-12)
                point=np.array([.1,.2,.3,1])
                np.testing.assert_allclose(np.linalg.inv(matrix) @ matrix @ point,point,atol=1e-12)

    def test_trajectory_correction_preserves_beam_relative_to_ct_without_ct_orbit(self):
        scan=self.scan('/unused');m=initial_placement([scan],discover=False)
        m.update(model='stack',motors=stack_rows(scan.start_positioners),angle_offset=17.,angle_sign=-1.)
        old_x,_=positions(scan,m)
        m.update(pivot_x=-492.,pivot_z=-393.)
        corrected_x,_=positions(scan,m)
        theta=np.deg2rad(np.repeat(angles(scan,m),421))
        shift=m['pivot_x']*np.cos(theta)+m['pivot_z']*np.sin(theta)
        # Previously CT points were shifted by -R*p. Now the same relative
        # transverse ray coordinates result from shifting the beam by +R*p.
        rotated_point=80*np.cos(theta)+30*np.sin(theta)
        np.testing.assert_allclose(corrected_x-rotated_point,old_x-(rotated_point-shift),atol=1e-10)

    def test_swaxs_rotation_warning_handles_wraparound_and_absent_snapshot(self):
        scan=self.scan('/unused')
        self.assertEqual(rotation_warning(scan),'')
        for value in (180,-180,540,180.0001):
            scan.start_positioners['swaxs_ry']=value
            self.assertEqual(rotation_warning(scan),'')
        scan.start_positioners['swaxs_ry']=0
        self.assertIn('beamline scientists',rotation_warning(scan))
