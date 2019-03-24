"""
Handles antenna beam models
"""
from __future__ import absolute_import, division, print_function

import numpy as np
from astropy.constants import c
from scipy.special import j1
import copy
from pyuvdata import UVBeam


def airy_disk(za_array, freqs, diameter=15.0, **kwargs):
    """
    Airy disk function for an antenna of specified diameter.

    Args:
        za_array: 1D ndarray, zenith angle [radians]
        freqs: 1D array, observing frequencies [Hz]
        diameter: float, antenna diameter [meters]

    Returns:
        beam: 2D array of shape (Npix, Nfreqs) where Npix = len(za_array)
    """
    # set za values greater than pi/2 to pi/2, such that beam doesn't rise to unity at np.pi
    za_arr = za_array.copy()
    za_arr[za_arr > np.pi / 2] = np.pi / 2
    xvals = diameter / 2. * np.sin(za_arr.reshape(-1, 1)) * 2. * np.pi * freqs.reshape(1, -1) / c.value
    zeros = np.isclose(xvals, 0.0)
    beam = (2.0 * np.true_divide(j1(xvals), xvals, where=~zeros))**2.0
    beam[zeros] = 1.0

    return beam


class PowerBeam(UVBeam):
    """
    Interface for using beamfits files.
    """

    def __init__(self, beamfits=None):
        """
        Initialize a PowerBeam object

        Args:
            beamfits : str or UVBeam
                A path to beamfits file or a UVBeam object
            interp_mode : str
                Interpolation method. See pyuvdata.UVBeam
        """
        # initialize
        super(PowerBeam, self).__init__()

        # read a beamfits
        if beamfits is not None:
            self.read_beamfits(beamfits)

        # convert to power if efield
        if self.beam_type == 'efield':
            self.efield_to_power()


    def interp_freq(self, freqs, inplace=False, kind='linear', run_check=True):
        """
        Interpolate object across frequency.

        Args:
            freqs: 1D frequency array [Hz]
            inplace: bool, if True edit data in place, otherwise return a new UVBeam
            kind: str, interpolation method. See scipy.interpolate.interp1d
            run_check: bool, if True run attribute check on output object

        Returns:
            If not inplace, returns UVBeam object with interpolated frequencies
        """
        # make a new object
        if inplace:
            new_beam = self
        else:
            new_beam = copy.deepcopy(self)

        interp_data, interp_bp = super(PowerBeam, self)._interp_freq(freqs, kind=kind)
        new_beam.data_array = interp_data
        new_beam.Nfreqs = interp_data.shape[3]
        new_beam.freqs = freqs.reshape(1, -1)
        new_beam.bandpass_array = interp_bp
        if hasattr(new_beam, 'saved_interp_functions'):
            delattr(new_beam, 'saved_interp_functions')

        if run_check:
            new_beam.check()

        if not inplace:
            return new_beam

    def beam_val(self, az, za, freqs, pol='pI', **kwargs):
        """
        Fast interpolation of power beam across the sky,
        using UVBeam "simple" interpolation methods.

        Note: this does not interpolate frequencies, instead
        it just takes the nearest neighbor of each requested
        frequency for speed. To interpolate the frequency axis
        ahead of time, see self.interp_freq().

        Args:
            az : float or ndarray, azimuth angle [radian], must have len(za)
            za : float or ndarray, zenith angle [radian], must have len(az)
            freqs : float or ndarray, frequencies [Hz]
            pol : str, requested visibility polarization, Ex: 'XX' or 'pI'.

        Returns:
            beam_value : ndarray of beam power, with shape (Npix, Nfreqs) where Npix = len(za)
        """
        # type checks
        assert self.beam_type == 'power', "beam_type must be power. See efield_to_power()"
        if isinstance(az, (float, np.float, int, np.int)):
            az = np.array([az])
        if isinstance(za, (float, np.float, int, np.int)):
            za = np.array([za])
        az = np.asarray(az)
        za = np.asarray(za)

        if self.pixel_coordinate_system == 'az_za':
            self.interpolation_function = 'az_za_simple'
        elif self.pixel_coordinate_system == 'healpix':
            self.interpolation_function = 'healpix_simple'

        if freqs is None:
            freqs = self.freqs[0]
        else:
            # get nearest neighbor of each reqeuested frequency
            if isinstance(freqs, (float, np.float, int, np.int)):
                freqs = np.array([freqs])
            freqs = np.asarray(freqs)
            assert freqs.ndim == 1, "input freqs array must be 1-dimensional"
            freq_dists = np.abs(self.freqs - freqs.reshape(-1, 1))
            nearest_dist = np.min(freq_dists, axis=1)
            nearest_inds = np.argmin(freq_dists, axis=1)
            freqs = self.freqs[0, nearest_inds]

        assert isinstance(pol, str), "requested polarization must be a single string"

        # interpolate
        if self.pixel_coordinate_system == 'az_za':
            # azimuth - zenith angle interpolation
            interp_beam, interp_basis = self._interp_az_za_rect_spline(az_array=az, za_array=za, freqs=freqs, reuse_spline=True, polarizations=[pol])

        elif self.pixel_coordinate_system == 'healpix':
            # healpix interpolation
            interp_beam, interp_basis = self._interp_healpix_bilinear(az_array=az, za_array=za, freqs=freqs, polarizations=[pol])

        return interp_beam[0, 0, 0].T


class AnalyticBeam(object):

    def __init__(self, beam_type, gauss_width=None, diameter=None):
        """
        Instantiate an analytic beam model.

        Currently this class only supports single-polarization beam models.

        Args:
            beam_type : str or callable, type of beam to use. options=['uniform', 'gaussian', 'airy', callable]
            gauss_width : float, standard deviation [degrees] for gaussian beam
            diameter : float, dish diameter [meter] used for airy beam

        Notes:
            Uniform beam is a flat-top beam across the entire sky.
            Gaussian beam is a frequency independent, peak normalized Gaussian
                with respect to zenith angle.
            Airy beam uses the dish diameter to set the airy beam width as a function of frequency.
            callable is any function that takes (za_array, freqs) in units [radians, Hz] respectively
                and returns an ndarray of shape (Npix, Nfreqs) with power beam values, where
                Npix = len(za_array)
        """
        if beam_type not in ['uniform', 'gaussian', 'airy'] and not callable(beam_type):
            raise NotImplementedError("Beam type " + str(beam_type) + " not available yet.")
        self.beam_type = beam_type
        if beam_type == 'gaussian':
            if gauss_width is None:
                raise KeyError("gauss_width required for gaussian beam")
            self.gauss_width = gauss_width * np.pi / 180.  # deg -> radians
        elif beam_type == 'airy':
            if diameter is None:
                raise KeyError("Dish diameter required for airy beam")
            self.diameter = diameter

    def plot_beam(self, az, za, freqs, **kwargs):
        # TODO: needs development, and testing coverage?
        fig = pl.figure()
        pl.imshow(self.beam_val(az, za, freqs, **kwargs))
        pl.show()

    def beam_val(self, az, za, freqs, **kwargs):
        """
        Evaluation of an analytic beam model.

        Args:
            az : float or ndarray, azimuth angle [radian], must have len(za)
            za : float or ndarray, zenith angle [radian], must have len(az)
            freqs : float or ndarray, frequencies [Hz]
            kwargs : keyword arguments to pass if self.beam_type is callable

        Returns:
            beam_value : ndarray of beam power, with shape (Npix, Nfreqs) where Npix = len(za)
        """
        if self.beam_type == 'uniform':
            if isinstance(az, np.ndarray):
                beam_value = np.ones((len(za), len(freqs)), dtype=np.float)
            else:
                beam_value = 1.0
        elif self.beam_type == 'gaussian':
            beam_value = np.exp(-(za**2) / (2 * self.gauss_width**2))  # Peak normalized
            beam_value = np.repeat(beam_value[:, np.newaxis], len(freqs), axis=1)
        elif self.beam_type == 'airy':
            beam_value = airy_disk(za, freqs, diameter=self.diameter)
        elif callable(self.beam_type):
            beam_value = self.beam_type(za, freqs, **kwargs)

        return beam_value
