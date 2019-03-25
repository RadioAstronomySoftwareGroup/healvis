from __future__ import absolute_import, division, print_function

import numpy as np
import yaml
import sys
import six
from six.moves import map, range, zip
import os

from pyuvdata import UVData
from pyuvdata import utils as uvutils

from . import observatory, version, beam_model, sky_model


def _parse_layout_csv(layout_csv):
    """ Interpret the layout csv file """

    with open(layout_csv, 'r') as fhandle:
        header = fhandle.readline()

    header = [h.strip() for h in header.split()]
    if six.PY2:
        str_format_code = 'a'
    else:
        str_format_code = 'U'
    dt = np.format_parser([str_format_code + '10', 'i4', 'i4', 'f8', 'f8', 'f8'],
                          ['name', 'number', 'beamid', 'e', 'n', 'u'], header)

    return np.genfromtxt(layout_csv, autostrip=True, skip_header=1,
                         dtype=dt.dtype)


def parse_telescope_params(tele_params):
    """
    Parse the "telescope" section of a healvis obsparam.

    Args:
        tele_params: Dictionary of telescope parameters

    Returns:
        dict of array properties:
            |  Nants_data: Number of antennas
            |  Nants_telescope: Number of antennas
            |  antenna_names: list of antenna names
            |  antenna_numbers: corresponding list of antenna numbers
            |  antenna_positions: Array of ECEF antenna positions
            |  telescope_location: ECEF array center location
            |  telescope_config_file: Path to configuration yaml file
            |  antenna_location_file: Path to csv layout file
            |  telescope_name: observatory name
    """
    layout_csv = tele_params['array_layout']
    if not os.path.exists(layout_csv):
        if not os.path.exists(layout_csv):
            raise ValueError('layout_csv file from yaml does not exist')

    ant_layout = _parse_layout_csv(layout_csv)
    tloc = tele_params['telescope_location'][1:-1]  # drop parens
    tloc = list(map(float, tloc.split(",")))
    tloc[0] *= np.pi / 180.
    tloc[1] *= np.pi / 180.   # Convert to radians
    tele_params['telescope_location'] = uvutils.XYZ_from_LatLonAlt(*tloc)

    E, N, U = ant_layout['e'], ant_layout['n'], ant_layout['u']
    antnames = ant_layout['name']
    return_dict = {}

    return_dict['Nants_data'] = antnames.size
    return_dict['Nants_telescope'] = antnames.size
    return_dict['antenna_names'] = np.array(antnames.tolist())
    return_dict['antenna_numbers'] = np.array(ant_layout['number'])
    antpos_enu = np.vstack((E, N, U)).T
    return_dict['antenna_positions'] = uvutils.ECEF_from_ENU(antpos_enu, *tloc) - tele_params['telescope_location']
    return_dict['array_layout'] = layout_csv
    return_dict['telescope_location'] = tele_params['telescope_location']
    return_dict['telescope_name'] = tele_params['telescope_name']

    return return_dict


def parse_freq_params(freq_params):
    """
    Parse the "freq" section of healvis obsparams

    Args:
        freq_params : dictionary

    Returns:
        dictionary
            | Nfreqs : int
            | channel_width : float, [Hz]
            | freq_array : 2D ndarray, shape (1, Nfreqs) [Hz]
    """
    # generate frequencies
    freq_array = np.linspace(freq_params['start_freq'], freq_params['start_freq'] + freq_params['bandwidth'], freq_params['Nfreqs'], endpoint=False).reshape(1, -1)

    # fill return dictionary
    return_dict = {}
    return_dict['Nfreqs'] = freq_params['Nfreqs']
    return_dict['freq_array'] = freq_array
    return_dict['channel_width'] = np.diff(freq_array[0])[0]

    return return_dict


def parse_time_params(time_params):
    """
    Parse the "time" section of healvis obsparams

    Args:
        time_params : dictionary

    Returns:
        dictionary
            | Ntimes : int
            | integration_time : float, [seconds]
            | time_array : 1D ndarray, shape (Ntimes,) [Julian Date]
    """
    # generate times
    time_arr = time_params['start_time'] + np.arange(time_params['Ntimes']) * time_params['integration_time'] / (24.0 * 3600.0)

    # fill return dictionary
    return_dictionary = {}
    return_dictionary['Ntimes'] = time_params['Ntimes']
    return_dictionary['integration_time'] = np.ones(time_params['Ntimes'], dtype=np.float) * time_params['integration_time']
    return_dictionary['time_array'] = time_arr

    return return_dictionary


def run_simulation(param_file, Nprocs=1, sjob_id=None, add_to_history=''):
    """
    Parse input parameter file, construct UVData and SkyModel objects, and run simulation.

    (Moved code from wrapper to here)
    """
    # parse parameter dictionary
    if isinstance(param_file, (str, np.str)):
        with open(param_file, 'r') as yfile:
            param_dict = yaml.safe_load(yfile)
    else:
        param_dict = param_file

    print("Making uvdata object")
    sys.stdout.flush()
    tele_dict = parse_telescope_params(param_dict['telescope'].copy())
    freq_dict = parse_freq_params(param_dict['freq'].copy())
    time_dict = parse_time_params(param_dict['time'].copy())
    filing_params = param_dict['filing']

    # ---------------------------
    # Extra parameters required for healvis
    # ---------------------------
    fov = param_dict['fov']  # Deg
    skyparam = param_dict['skyparam'].copy()
    skyparam['freqs'] = freq_dict['freq_array']
    Nskies = 1 if 'Nskies' not in param_dict else int(param_dict['Nskies'])
    print("Nprocs: ", Nprocs)
    sys.stdout.flush()

    # ---------------------------
    # Observatory
    # ---------------------------
    lat, lon, alt = uvutils.LatLonAlt_from_XYZ(tele_dict['telescope_location'])
    antpos = tele_dict['antenna_positions']
    enu = uvutils.ENU_from_ECEF(tele_dict['antenna_positions'] + tele_dict['telescope_location'], lat, lon, alt)
    anums = tele_dict['antenna_numbers']
    antnames = tele_dict['antenna_names']
    Nants = tele_dict['Nants_data']

    uv_obj = UVData()
    uv_obj.telescope_location = tele_dict['telescope_location']
    uv_obj.telescope_location_lat_lon_alt = (lat, lon, alt)
    uv_obj.telescope_location_lat_lon_alt_degrees = (np.degrees(lat), np.degrees(lon), alt)
    uv_obj.antenna_numbers = anums
    uv_obj.antenna_names = antnames
    uv_obj.antenna_positions = antpos
    uv_obj.Nants_telescope = Nants
    uv_obj.Ntimes = time_dict['Ntimes']
    Ntimes = time_dict['Ntimes']
    uv_obj.freq_array = freq_dict['freq_array']
    uv_obj.Nfreqs = freq_dict['Nfreqs']

    array = []
    bl_array = []
    bls = [(a1, a2) for a2 in anums for a1 in anums if a1 > a2]
    if 'select' in param_dict:
        sel = param_dict['select']
        if 'bls' in sel:
            bls = eval(sel['bls'])
        if 'antenna_nums' in sel:
            antnums = sel['antenna_nums']
            if isinstance(antnums, str):
                antnums = eval(sel['antenna_nums'])
            if isinstance(antnums, int):
                antnums = [antnums]
            bls = [(a1, a2) for (a1, a2) in bls if a1 in antnums or a2 in antnums]
            uv_obj.antenna_nums = antnums
        if 'redundancy' in sel:
            red_tol = sel['redundancy']
            reds, vec_bin_centers, lengths = uvutils.get_antenna_redundancies(anums, enu, tol=red_tol, include_autos=False)
            bls = []
            for rg in reds:
                for r in rg:
                    if r not in bls:
                        bls.append(r)
                        break
    #        bls = [r[0] for r in reds]
            bls = [uvutils.baseline_to_antnums(bl_ind, Nants) for bl_ind in bls]
    uv_obj.Nants_data = np.unique(bls).size
    for (a1, a2) in bls:
        i1, i2 = np.where(anums == a1), np.where(anums == a2)
        array.append(observatory.Baseline(enu[i1], enu[i2]))
        bl_array.append(uvutils.antnums_to_baseline(a1, a2, Nants))
    Nbls = len(bl_array)
    uv_obj.Nbls = Nbls
    uv_obj.Nblts = Nbls * Ntimes

    bl_array = np.array(bl_array)
    obs = observatory.Observatory(np.degrees(lat), np.degrees(lon), array=array, freqs=freq_dict['freq_array'][0])
    obs.set_fov(fov)
    print("Observatory built.")
    print("Nbls: ", Nbls)
    print("Ntimes: ", Ntimes)
    sys.stdout.flush()

    # ---------------------------
    # Pointings
    # ---------------------------
    time_arr = time_dict['time_array']
    obs.set_pointings(time_arr)
    print("Pointings set.")
    sys.stdout.flush()

    # ---------------------------
    # SkyModel
    # ---------------------------
    # construct sky model
    sky = sky_model.construct_skymodel(skyparam['sky_type'], freqs=obs.freqs, Nside=skyparam['Nside'],
                                       ref_chan=skyparam['ref_chan'], sigma=skyparam['sigma'])
    # If loading a healpix map from disk, use those frequencies instead of ones specified in obsparam
    if skyparam['sky_type'].lower() not in ['flat_spec', 'gsm']:
        obs.freqs = sky.freqs
        obs.Nfreqs = len(obs.freqs)
    else:
        # write to disk if requested
        if skyparam['savepath'] not in [None, 'None', 'none', '']:
            sky.write_hdf5(os.path.join(filing_params['outdir'], savepath))

    # ---------------------------
    # Primary Beam
    # ---------------------------
    beam_attr = param_dict['beam'].copy()
    beam_type = beam_attr.pop("beam_type")
    obs.set_beam(beam_type, **beam_attr)

    # if PowerBeam, interpolate to Observatory frequencies
    if isinstance(obs.beam, beam_model.PowerBeam):
        obs.beam.interp_freq(obs.freqs, inplace=True, kind='cubic')

    # ---------------------------
    # Run simulation
    # ---------------------------
    print("Running simulation")
    sys.stdout.flush()
    visibility = []
    beam_sq_int = {}
    for pol in param_dict['pols']:
        # calculate visibility
        visibs, time_array, baseline_inds = obs.make_visibilities(sky, Nprocs=Nprocs, beam_pol=pol)
        visibility.append(visibs)
        # Average Beam^2 integral across frequency
        beam_sq_int['bm_sq_{}'.format(pol)] = np.mean(obs.beam_sq_int(obs.freqs, sky.Nside, obs.pointing_centers[0], beam_pol=pol))

    visibility = np.moveaxis(visibility, 0, -1)

    # ---------------------------
    # Fill in the UVData object and write out.
    # ---------------------------
    uv_obj.freq_array = obs.freqs.reshape(1, -1)
    uv_obj.Nfreqs = uv_obj.freq_array.shape[1]
    uv_obj.time_array = time_array
    uv_obj.set_lsts_from_time_array()
    uv_obj.baseline_array = bl_array[baseline_inds]
    uv_obj.ant_1_array, uv_obj.ant_2_array = uv_obj.baseline_to_antnums(uv_obj.baseline_array)

    uv_obj.spw_array = np.array([0])
    uv_obj.Npols = len(param_dict['pols'])
    uv_obj.polarization_array = np.array([uvutils.polstr2num(pol) for pol in param_dict['pols']], np.int)
    uv_obj.Nspws = 1
    uv_obj.set_uvws_from_antenna_positions()
    uv_obj.channel_width = np.diff(obs.freqs)[0]
    uv_obj.integration_time = np.ones(uv_obj.Nblts) * np.diff(time_arr)[0] * 24 * 3600.  # Seconds
    param_history = "\nPARAMETER FILE:\nFILING\n{filing}\nSIMULATION\n{tel}\n{beam}\nfov: {fov}\n" \
                    "SKYPARAM\n{sky}\n".format(filing=param_dict['filing'], tel=param_dict['telescope'], beam=param_dict['beam'],
                                               fov=param_dict['fov'], sky=param_dict['skyparam'])
    uv_obj.history = version.history_string(notes=add_to_history + param_history)
    uv_obj.set_drift()
    uv_obj.telescope_name = 'healvis'
    uv_obj.instrument = 'simulator'
    uv_obj.object_name = 'zenith'
    uv_obj.vis_units = 'Jy'

    if sjob_id is None:
        sjob_id = ''

    uv_obj.extra_keywords = {'nside': sky.Nside, 'slurm_id': sjob_id}
    uv_obj.extra_keywords.update(beam_sq_int)
    if beam_type == 'gaussian':
        fwhm = beam_attr['sigma'] * 2.355
        uv_obj.extra_keywords['bm_fwhm'] = fwhm
    elif beam_type == 'airy':
        uv_obj.extra_keywords['bm_diam'] = beam_attr['diameter']

    if sky.pspec_amp is not None:
        uv_obj.extra_keywords['skysig'] = sky.pspec_amp   # Flat spectrum sources

    for si in range(Nskies):
        sky_i = slice(si, si + 1)
        data_arr = visibility[:, sky_i, :, :]  # (Nblts, Nspws, Nfreqs, Npols)
        uv_obj.data_array = data_arr

        uv_obj.flag_array = np.zeros(uv_obj.data_array.shape).astype(bool)
        uv_obj.nsample_array = np.ones(uv_obj.data_array.shape).astype(float)

        uv_obj.check()

        if 'format' in filing_params:
            out_format = filing_params['format']
        else:
            out_format = 'uvh5'

        if Nskies > 1:
            filing_params['outfile_suffix'] = '{}sky_uv'.format(sky_i)
        elif out_format == 'miriad':
            filing_params['outfile_suffix'] = 'uv'

        if 'outfile_name' not in filing_params:
            if 'outfile_prefix' not in filing_params:
                outfile_name = "healvis"
            else:
                outfile_name = filing_params['outfile_prefix']
            if beam_type == 'gaussian':
                outfile_name += '_fwhm{:.3f}'.format(beam_attr['gauss_width'])
            elif beam_type == 'airy':
                outfile_name += '_diam{:.2f}'.format(beam_attr['diameter'])

        else:
            outfile_name = filing_params['outfile_name']
        outfile_name = os.path.join(filing_params['outdir'], outfile_name + ".{}".format(out_format))

        # write base directory if is doesn't exist
        dirname = os.path.dirname(outfile_name)
        if dirname != '' and not os.path.exists(dirname):
            os.mkdir(dirname)

        print("...writing {}".format(outfile_name))
        if out_format == 'uvh5':
            uv_obj.write_uvh5(outfile_name, clobber=filing_params['clobber'])
        elif out_format == 'miriad':
            uv_obj.write_miriad(outfile_name, clobber=filing_params['clobber'])
        elif out_format == 'uvfits':
            uv_obj.write_uvfits(outfile_name)
