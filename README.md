# healvis

[![Build Status](https://travis-ci.org/RadioAstronomySoftwareGroup/healvis.svg?branch=master)](https://travis-ci.org/RadioAstronomySoftwareGroup/healvis)

Radio interferometric visibility simulator based on HEALpix maps.

**Note** This is a tool developed for specific research uses, and is not yet at the development standards of other RASG projects. Use at your own risk.

## Dependencies
Python dependencies for `healvis` include

* numpy >= 1.14
* astropy >= 2.0
* scipy
* healpy >= 1.12.9
* h5py
* pyyaml
* numba
* multiprocessing
* [pyuvdata](https://github.com/HERA-Team/pyuvdata/)

Optional dependencies include

* [pygsm](https://github.com/telegraphic/PyGSM)
* [scikit-learn](https://scikit-learn.org/stable/)

## Installation
Clone this repo and run the installation script as
```python setup.py install```

## Getting Started
To get started running `healvis`, see our [tutorial notebooks](https://github.com/RadioAstronomySoftwareGroup/healvis/tree/master/notebooks).
