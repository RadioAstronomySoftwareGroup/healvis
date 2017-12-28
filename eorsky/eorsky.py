## Class to handle EoR simulation data
##	> Read in hdf5 files and binary files for cubes and shells
##	> Convert between rectilinear cubes and tiled healpix shells.
##	> Estimate 1D power spectrum from rectilinear cube.
##	> (eventually) Perform spherical Bessel transform to estimate pspec from healpix shell directly


#### TODO
##	> Add unittests
##	> Add the spherical bessel transform to pspec.py (as written in notebook).
##	> Add a defaults method.
##  > Enable pspec comparison against a text file
##  > Work on binary file reader
##	> Test the change in pspec with the unslicing loop. --> Does the loss of box coverage affect it?
##  > Enable different interpolation for the healpix slicing/unslicing
##  > Is it possible to encode Marcelo's method into here?
## 	> Update the update() method to work by groups -- which groups of parameters are interdependent? How to ensure compatibility when one is updated?
        ### More work is needed to decide the best way to implement this.


import numpy as np
from astropy.cosmology import WMAP9 as cosmo
import scipy.stats
from astropy import units
from astropy.constants import c
import healpy as hp
from numpy import pi
import h5py, sys
import warnings

freq_21 = 1420.

class eorsky(object):

    N = 256   # Npixels per side of rect_cube, default 256
    L = 500   # rect_cube side length in Mpc, default 500
    hpx_shell = None
    rect_cube = None
    nside = 256
    Npix = None
    pixsize = None    # Pixel size in steradians
    Nfreq = None
    freqs = None    # MHz
    Z = None
    updated = []      #Track which attributes are changed
    hpx_inds = None
    r_mpc = None         # Shell radii in Mpc
    ref_pk = None          ## Reference 1D power spectrum
    ref_ks = None

    def __init__(self, **kwargs):
        for key, value in kwargs.iteritems():
            print key, value
            if hasattr(self, key): setattr(self, key, value)
        self.update()

    def __setattr__(self,name,value):
        if self.updated is None: self.updated = []
        self.updated.append(name)
        super(eorsky, self).__setattr__(name, value)

    def make_gaussian_cube(self, N, L, mean=0.0, var=1.0):
        """ Make a gaussian cube with the given structure """
        self.N = N
        self.L = L
        self.rect_cube = np.random.normal(mean,var,((N,N,N)))

    def make_gaussian_shell(self, nside, freqs, mean=0.0, var=1.0):
        """ Make a gaussian shell with the given structure """
        Npix = hp.nside2npix(nside)
        try:
            Nfreq = freqs.size
        except:
            freqs = np.array(freqs); Nfreq = freqs.size
        self.Nfreq = Nfreq; self.Npix = Npix
        self.freqs = freqs
        self.hpx_shell = np.random.normal(mean,var,((Npix,Nfreq)))
        self.hpx_inds = np.arange(Npix)
        self.update()

    def consistency(self, param):
        hpx_params = ['nside','Npix','hpx_shell','hpx_inds']
        if param == 'nside':
            if self.hpx_inds is None:
                self.Npix = hp.nside2npix(self.nside)
                self.hpx_inds = np.arange(self.Npix)
            else:
                assert self.Npix == self.hpx_inds.size
        if param == 'Npix':
            if self.hpx_inds is None: self.hpx_inds = np.arange(self.Npix)
        if param in hpx_params:
            if not self.hpx_shell is None: assert self.hpx_shell.shape[0] == self.Npix

    def update(self):
        """ Make Z, freq, healpix params, and rectilinear params consistent. 
            Assume that whatever parameter was just changed has priority over others.
            If two parameters from the same group change at the same time, confirm that they're consistent.
            ### For now --- Just sets default values if freq or any healpix parameter is changed.
        """

        hpx_params = ['nside','Npix','hpx_shell','hpx_inds']
        z_params   = ['Z', 'freqs','Nfreq','r_mpc']
        r_params   = ['L','N','rect_cube']

        ud = np.unique(self.updated)
        for p in ud:
            print p
            if p == 'freqs':
                self.Z = 1420./self.freqs - 1.
                self.r_mpc = cosmo.comoving_distance(self.Z).to("Mpc").value
                self.Nfreq = self.freqs.size
            if p == 'nside':
                if self.Npix is None: self.Npix = hp.nside2npix(self.nside)
                if self.hpx_inds is None: self.hpx_inds = np.arange(self.Npix)
            if p == 'rect_cube':
                self.N = self.rect_cube.shape[0]
        self.updated = []

    def read_pspec(self,filename):
        """ Read in a text file of power spectrum values """
        ref_spectrum = np.genfromtxt(filename)
        self.ref_ks = ref_spectrum[:,0]
        self.ref_pk = ref_spectrum[:,1]


    def read_hdf5(self,filename,chan_range=None):
        print 'Reading: ', filename
        infile = h5py.File(filename)
        if not chan_range is None:
            c0,c1 = chan_range
            self.freqs = infile['spectral_info/freq'][c0:c1]/1e6  # Hz -> MHz
            self.hpx_shell = infile['spectral_info/spectrum'][:,c0:c1]
            self.Npix, self.Nfreq = self.hpx_shell.shape
        else:
            self.freqs = infile['spectral_info/freq'][()]/1e6  # Hz -> MHz
            self.hpx_shell = infile['spectral_info/spectrum'][()]
            self.Npix, self.Nfreq = infile['spectral_info/spectrum'].shape
        self.hpx_inds = np.arange(self.Npix)
        infile.close()
        self.update()

    def read_bin(self, filename, L=None, dtype=float):
        print 'Reading: ', filename
        self.rect_cube = np.fromfile(filename,dtype=dtype)
        if L is not None: self.L = L
        self.N = self.rect_cube.shape[0]

    def write_hdf5(self, filename):
        with h5py.File(filename, 'w') as fileobj:
            freqs_Hz = self.freqs * 1e6
            hdr_grp = fileobj.create_group('header')
            hdr_grp['units'] = "K"
            hdr_grp['is_healpix'] = 1
            spec_group = fileobj.create_group('spectral_info')
            freq_dset = spec_group.create_dataset('freq', data=freqs_Hz, compression='gzip', compression_opts=9)
            freq_dset.attrs['units'] = 'Hz'
            spectrum_dset = spec_group.create_dataset('spectrum', data=self.hpx_shell, compression='gzip', compression_opts=9)

    def cube_inds(self,which=0):
        """ Group healpix indices and radii by which box repetition they're in. """
        N, L = self.N, np.float(self.L)
        r_mpc = self.r_mpc
        Vx, Vy, Vz = hp.pix2vec(self.nside, self.hpx_inds)
        l = np.floor(np.outer(Vx, r_mpc)/L).astype(int)
        m = np.floor(np.outer(Vy, r_mpc)/L).astype(int)
        n = np.floor(np.outer(Vz, r_mpc)/L).astype(int)
        offset = (-1)*np.min([l,m,n]) + 1
        l += offset
        m += offset
        n += offset
        box_inds = l + m * offset + n * offset**2
        _, inv = np.unique(box_inds, return_inverse=True)
        inv = inv.reshape((self.Npix,self.Nfreq))
        print "Choosing cube ", which," of ", len(_)
        return np.where(inv == which)

    def slice(self,**kwargs):
        """ Take a rect_cube and slice it into a healpix shell """
        assert self.nside is not None
        assert self.N is not None
        assert self.L is not None
        if self.Npix is None: self.Npix = hp.nside2npix(self.nside)
        if self.hpx_inds is None: self.hpx_inds = np.arange(self.Npix)


        hpx_shell = np.zeros((self.Npix,self.Nfreq))

        Vx, Vy, Vz = hp.pix2vec(self.nside, self.hpx_inds)
        vecs = np.vstack([Vx,Vy,Vz])    #(3,npix)
        L = float(self.L)
        dx = L / float(self.N)

        cube = self.rect_cube
        for i in range(self.Nfreq):
            r = self.r_mpc[i]
            XYZmod = (vecs * r) % L
            l,m,n = (XYZmod / dx).astype(int)
            hpx_shell[:,i] += cube[l,m,n]
        self.hpx_shell = hpx_shell

    def unslice(self,**kwargs):
        params = ["N","L","nside","hpx_inds"]
        for key, value in kwargs.iteritems():
            if hasattr(self, key) and key in params: setattr(self, key, value)

        if 'freq_sel' in kwargs:
            f_min, f_max = kwargs['freq_sel']    #Select a range of frequencies. Passed in as a list [f_min, f_max]
            freq_arr = self.freqs
            i = np.argmin(np.abs(freq_arr - f_min))
            f = np.argmin(np.abs(freq_arr - f_max))
            freq_arr = freq_arr[i:f]
            freq_inds = np.arange(i,f,1)
        elif 'freq_ind_range' in kwargs:
            i,f = kwargs['freq_inds']
            freq_inds = np.arange(i,f,1)
            freq_arr = self.freqs[freq_inds]
        elif 'freq_inds' in kwargs:
            freq_inds = kwargs['freq_inds']
            freq_arr = self.freqs[freq_inds]
        else:
            freq_arr = self.freqs
            freq_inds = np.arange(self.Nfreq)
 
        N,L = self.N, np.float(self.L)
        dx = L/float(N)
        cube = np.zeros((N,N,N))
        Vx, Vy, Vz = hp.pix2vec(self.nside, self.hpx_inds)
        vecs = np.vstack([Vx,Vy,Vz]).T    #(npix, 3)

        cube_sel = -1
        if 'cube_sel' in kwargs:
            cube_sel = int(kwargs['cube_sel'])        #Select a particular cube repetition
            box = self.cube_inds(cube_sel)
        hpx_shell = self.hpx_shell
        ones_shell = np.ones_like(hpx_shell)
        weights = np.zeros_like(cube)
        for i in freq_inds:
            print i
            r = self.r_mpc[i]
            inds = np.floor((r*vecs)%(L)/dx).astype(int)   # (npix, 3)
            if 'cube_sel' in kwargs:
                finder = np.where(box[1] == i)
                hpi = box[0][finder]
                if len(hpi) == 0 : continue
                l,m,n = inds[hpi,:].T
                cart_inds = (l,m,n)
                np.add.at(cube,cart_inds,hpx_shell[hpi,i])
                np.add.at(weights,cart_inds,ones_shell[hpi,i])
            else:
                cart_inds = (inds[:,0],inds[:,1],inds[:,2])
                np.add.at(cube,cart_inds,hpx_shell[:,i])
                np.add.at(weights,cart_inds,ones_shell[:,i])
        zeros = np.where(weights == 0.0)
        weights = 1/weights
        weights[zeros] = 0.0
        self.rect_cube = cube*weights



if __name__ == '__main__':
    freqs = np.linspace(180,200,20)
    Nfreq = 20
    ek = eorsky(freqs=freqs,Nfreq=Nfreq,nside=256)
#    ek.read_hdf5('/users/alanman/data/alanman/BubbleCube/TiledHpxCubes/gaussian_cube.hdf5')
    from copy import deepcopy
#    ek = eorsky()
    ek.rect_cube = np.ones((256,256,256))
    old_cube = deepcopy(ek.rect_cube)
    ek.slice()
    ek.unslice()
#    ek.slice()
#    e.cube_inds()    ## Confirmed ---> The slicing/unslicing works correctly.

    import IPython; IPython.embed()