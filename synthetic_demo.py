"""Fabricated NIM GUI fixtures, not measurements or a scattering simulation."""
from pathlib import Path
import json
import numpy as np

NOTICE = 'SYNTHETIC DEMO: fabricated specimen and scattering; no scientific validity'


def make_volume(size=160):
    """Return uint16 ZYX voxels, scalar spacing and XYZ origin in invented mm."""
    if size < 32:
        raise ValueError('Use at least 32 voxels per axis')
    spacing = 3.2 / size
    axis = (np.arange(size, dtype=np.float32) - (size - 1) / 2) * spacing
    z, y, x = np.meshgrid(axis, axis, axis, indexing='ij', sparse=True)
    r = np.sqrt((x / .9)**2 + (y / .68)**2 + (z / 1.3)**2)
    edge = np.clip((1-r)/.045, 0, 1)
    shell = np.exp(-((r-.91)/.04)**2)
    texture = (np.sin(32*x+5*np.sin(6*z))*np.sin(28*y-7*z))**2
    lobes = np.exp(-(((x-.28)/.35)**2+(y/.43)**2+(z/.95)**2))
    lobes += .85*np.exp(-(((x+.32)/.32)**2+((y+.05)/.4)**2+((z-.12)/.9)**2))
    core = np.exp(-(((x-.1*np.sin(5*z))/.10)**2+((y-.08*np.cos(4*z))/.10)**2))
    pores = 1-.9*(np.sin(17*x)*np.cos(21*y)*np.sin(15*z) > .7)
    density = edge*(.13+.43*shell+.30*lobes+.13*texture+.35*core)*pores
    return np.uint16(np.clip(density, 0, 1)*65535), spacing, np.repeat(axis[0], 3)


def scattering(volume, spacing, origin, beam_x=.25, beam_y=0., angle_deg=0.):
    """Return q, phi, cake[phi,q], and its full-azimuth mean I(q).

    Beam: laboratory +Z; sample rotation: laboratory Y. X/Y are lab mm.
    q is invented nominal nm^-1; phi is degrees in [-180,180).
    Beam radii intentionally have no effect on this illustrative signal.
    """
    q = np.linspace(.02, 1.4, 256, dtype=np.float32)
    phi = np.linspace(-180, 180, 180, endpoint=False, dtype=np.float32)
    ray_z = np.linspace(-2.5, 2.5, 320)
    t = np.deg2rad(angle_deg)
    sx = np.cos(t)*beam_x-np.sin(t)*ray_z
    sy = np.full_like(ray_z, beam_y)
    sz = np.sin(t)*beam_x+np.cos(t)*ray_z
    indices = np.rint((np.stack([sx, sy, sz], axis=1)-origin)/spacing).astype(int)
    valid = np.all((indices >= 0) & (indices < np.array(volume.shape[::-1])), axis=1)
    ix, iy, iz = indices[valid].T
    values = volume[iz, iy, ix].astype(float)/65535
    strength = values.sum()*(ray_z[1]-ray_z[0])
    asymmetry = np.average(sx[valid], weights=values) if values.sum() else 0
    mixture = np.clip(.5+.6*asymmetry+.25*beam_y, 0, 1)
    radial = (8/(1+(q/.10)**2)
              +(1+2*mixture)*np.exp(-.5*((q-.30)/.025)**2)
              +(3-2*mixture)*np.exp(-.5*((q-.66)/.045)**2)
              +.8*np.exp(-.5*((q-1.02)/.06)**2))
    angular = 1+.72*np.cos(2*(np.deg2rad(phi)-t-.8*beam_x+.5*beam_y))
    cake = (.03+strength*angular[:, None]*radial[None, :]).astype(np.float32)
    cake *= np.random.default_rng(2026).uniform(.97, 1.03, cake.shape).astype(np.float32)
    return q, phi, cake, cake.mean(axis=0)


def generate(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    volume, spacing, origin = make_volume()
    np.savez_compressed(destination/'specimen.npz', volume=volume,
                        spacing_mm=spacing, origin_xyz_mm=origin, notice=NOTICE)
    q, phi, cake, iq = scattering(volume, spacing, origin)
    np.savez_compressed(destination/'scattering.npz', q=q, phi_deg=phi,
                        cake=cake, iq=iq, beam_xy_mm=[.25, 0.],
                        sample_angle_deg=0., notice=NOTICE)
    metadata = dict(notice=NOTICE, volume_axis_order='ZYX',
                    physical_coordinates='invented millimetres',
                    q_units='invented nominal nm^-1', intensity_units='arbitrary',
                    cake_axis_order='phi,q', integration='mean over all equal-width azimuth bins',
                    beam_direction='laboratory +Z', sample_rotation_axis='laboratory Y',
                    beam_size_effect='visual only', format='NumPy NPZ; not OME-NGFF')
    (destination/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
    return volume, spacing, origin


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).parent.parent/'data')
    args = parser.parse_args()
    generate(args.output)
    print(f'{NOTICE}\nWritten to {args.output}')
