"""
# Limit the number of attempts @ each tuning step
# Figure out when resets are required
# Record traces when tuning is done
Add offset to lock point  (not just the mean)
"""
from matplotlib import pyplot as plt
import numpy as np
from importlib import reload
import matplotlib.cm
from mpl_toolkits.axes_grid1 import make_axes_locatable

import sys

import Nowack_Lab.Utilities.save
reload(Nowack_Lab.Utilities.save)
from Nowack_Lab.Utilities.save import Measurement

from ..Procedures.daqspectrum import SQUIDSpectrum

import Nowack_Lab.Procedures.mutual_inductance
reload(Nowack_Lab.Procedures.mutual_inductance)
from Nowack_Lab.Procedures.mutual_inductance import MutualInductance2


class ArrayTune(Measurement):
    instrument_list = ["daq", "squidarray", "preamp"]
    _daq_inputs = ["saa", "test"]
    _daq_outputs = ["test"]

    def __init__(self,
                 instruments,
                 squid_bias,
                 squid_tol = 100e-3,
                 aflux_tol = 10e-3,
                 sflux_offset = 0.0,
                 aflux_offset = 0.0,
                 conversion=1/1.44,
                 debug=False):
        """Given a lock SAA, tune the input SQUID and lock it.
        Args:
        instruments (dict): Dictionary of instruments
        squid_bias (float): Bias point for SQUID lock
        squid_tol (float): Allowed DC offset for the locked SQUID
        offset (float): Tune the lockpoint up/down on the SQUID characaristic.
        conversion (float): in phi_0/V (1/1.44 ibm, 1/2.1 hypres) in MED sens
        """
        super(ArrayTune, self).__init__(instruments=instruments)

        self.instruments = instruments
        self.squid_bias = squid_bias
        #self.conversion = 5 # Conversion between mod current and voltage
        self.squid_tol = squid_tol
        self.aflux_tol = aflux_tol
        self.sflux_offset = sflux_offset
        self.aflux_offset = aflux_offset
        self.saaconversion = conversion # med
        self.debug = debug

    def acquire(self):
        """Ramp the modulation coil current and monitor the SAA response."""
        # Send TTL pulse on "test"
        data = {"test": 2*np.ones(2000)}
        # Record test
        ret = self.daq.send_receive(data, chan_in = ["saa", "test"],
                                    sample_rate=100000)
        # Zero the DAQ output
        self.daq.outputs["test"].V = 0
        return ret['t'], ret["test"], ret["saa"], 

    def tune_squid_setup(self):
        """Configure SAA for SQUID tuning."""
        self.squidarray.lock("Array")
        #self.squidarray.S_flux_lim = 100
        self.squidarray.S_flux = self.squidarray.S_flux_lim/2
        self.squidarray.testInput = "S_flux"
        self.squidarray.testSignal = "On"
        self.squidarray.S_bias = self.squid_bias
        self.squidarray.sensitivity = "High"
        self.squidarray.reset()

    @staticmethod
    def _midpoint(data):
        return (np.max(data) + np.min(data))/2

    def tune_squid(self, attempts=5):
        """Tune the SQUID and adjust the DC SAA flux."""
        self.tune_squid_setup()
        self.char = self.acquire()
        error = self._midpoint(self.char[-1]) - self.aflux_offset
        
        if self.debug:
            print('Tune_squid error:', error)
        if np.abs(error) < self.aflux_tol:
            return True
        elif attempts == 0:
            print("Cannot tune SQUID.  Cannot find good place on characteristic")
            return False
        else:
            self.adjust("A_flux", error)
            return self.tune_squid(attempts = attempts-1)

    def lock_squid(self, attempts=5):
        """Lock the SQUID and adjust the DC SQUID flux."""
        self.squidarray.lock("Squid")
        self.squidarray.testSignal = "Off"
        self.squidarray.reset()
        ret = self.daq.monitor(["saa"], 0.01, sample_rate = 100000)
        error = self._midpoint(ret["saa"]) - self.sflux_offset

        if self.debug:
            print('lock_squid error:', error)

        if np.abs(error) < self.squid_tol:
            print("locked with {} attempts".format(5-attempts))
            return True
        elif attempts == 0:
            print("Cannot lock SQUID. Cannot zero signal within squid_tol.")
            return False
        else:
            self.adjust("S_flux", error)
            return self.lock_squid(attempts - 1)

    def adjust(self, attr, error):
        """Adjust DC flux to center the trace @ 0 V.
        attr:   (string): parameter of squidarray to change
        error:  (float):  distance in V from desired point
        """
        value = getattr(self.squidarray, attr)

        conversion = -1/(self.calibrate_adjust(attr))  

        if self.debug:
            print('    adjusting {0}: error={1:3.3f}, {0}+={2:3.3f}'.format(
                        attr, error, error*conversion))

        if value + error * conversion < 0:
            # Force a jump by resetting
            setattr(self.squidarray, attr, value + 50)
        elif value + error * conversion > 150:
            setattr(self.squidarray, attr, 0)
        else:
            # Directly correct the offset
            setattr(self.squidarray, attr, value + conversion * error)
        
        self.squidarray.reset()

    def _getmean(self, monitortime):
        received = self.daq.monitor('saa', monitortime, sample_rate=256000)
        return np.mean(received['saa']), np.std(received['saa'])

    def calibrate_adjust(self, attr, monitortime=.25, step=10):
        """ create conversion factor for adjust in V/[attr]"""
        conversion = 0
        attr_state = getattr(self.squidarray,attr)  

        mean1,_ = self._getmean(monitortime)
        setattr(self.squidarray, attr, attr_state + step)
        mean2,_ = self._getmean(monitortime)

        conversion  = (mean2-mean1)/step
        conversion_ = np.sign(conversion) * np.minimum(
                            100, np.maximum(.001, np.abs(conversion)))
        if conversion != conversion_:
            print('Conversion (V/{0}) out of range: {1}'.format(
                attr, conversion))
            conversion = conversion_

        setattr(self.squidarray, attr, attr_state)

        return conversion

    def setup_plots(self):
        '''
        purposely left empty to prevent creating a figure if 
        squid fails to lock
        '''
        pass


    def plot(self):
        self.fig, self.ax = plt.subplots(1,3,figsize=(12,4))
        # Plot the charactaristic
        self.ax[0].plot(self.char[1], self.char[2])
        self.ax[0].set_xlabel("Test Signal (V)")
        self.ax[0].set_ylabel("SAA Signal (V)", size="medium")
        self.ax[0].set_title(" {0:2.2e} phi_0/V".format(self.spectrum.conversion))

        # Plot the spectrum
        self.ax[2].loglog(self.spectrum.f,
                     self.spectrum.psdAve * self.spectrum.conversion)
        self.ax[2].set_xlabel("Frequency (Hz)")
        self.ax[2].set_title("PSD ($\mathrm{%s/\sqrt{Hz}}$)" % self.spectrum.units,
                        size="medium")
        self.ax[2].annotate('Sbias = {0:2.2e} uA\nAflux = {1:2.2e} uA'.format(
                            self.squid_bias, self.aflux_offset), 
                            xy=(.02, .2), xycoords='axes fraction',
                            fontsize=8, ha='left', va='top', family='monospace')
        
        # Plot the sweep
        self.sweep.ax = self.ax[1]
        self.sweep.plot()
        self.ax[1].set_ylabel("")
        self.ax[1].set_title("DC SQUID Signal (V)",
                        size="medium")
    def run_spectrum(self, save_appendedpath=''):
        self.squidarray.sensitivity = "High" #Essential, for some reason
        self.preamp.gain = 1
        self.preamp.filter = (1, 100000)
        self.squidarray.reset()
        self.spectrum = SQUIDSpectrum(self.instruments, 
                                      preamp_dccouple_override=True)
        self.spectrum.conversion = self.saaconversion/10
        self.spectrum.saa_status = self.squidarray.__dict__
        if self.debug:
            print('squid sensitivity = ', self.squidarray.sensitivity)

        self.isOL = self.preamp.is_OL()
        if self.isOL:
            print('Overloaded Preamp!')
        self.spectrum.run(welch=True, save_appendedpath = save_appendedpath)

    def run_mi(self, save_appendedpath=''):
        self.squidarray.sensitivity = "Medium"
        self.squidarray.reset()
        self.preamp.filter = (1, 300)
        self.preamp.gain = 1
        self.squidarray.reset()
        self.sweep = MutualInductance2(self.instruments,
                                       np.linspace(-1e-3, 1e-3, 1000),
                                       Rbias=340,
                                       conversion = 1,
                                       units = 'V')
        self.sweep.saa_status = self.squidarray.__dict__
        self.sweep.run(save_appendedpath = save_appendedpath)

    def do(self):
        # TODO: Measure array V/phi_0 conversion
        # TODO: take array spectrum

        # Try to measure squid V/phi_0 conversion
        #self.squidarray.S_flux_lim = 100
        #[self.selfcal, 
        # self.saaconversion, 
        # self.conv_sflux]  = self.findconversion(stepsize=5, dur=.001)
        #print('Self calibrated? = {0}, phi_0/V = {1}'.format(
        #            self.selfcal, self.saaconversion))

        # Tune squid
        self.istuned = self.tune_squid()
        if self.istuned == False:
            print('Array Tune Failed, will not save array_tune')
            sys.stdout.flush()
            self._DO_NOT_SAVE = True
            return False

        self.islocked = self.lock_squid()
        if self.islocked == False:
            print('Array Tune Failed, will not save array_tune')
            sys.stdout.flush()
            self._DO_NOT_SAVE = True
            return False

        self.run_spectrum(self._save_appendedpath)
        plt.close()
        self.run_mi(self._save_appendedpath)
        plt.close()
        self.plot()
        plt.close()
        self.ax = list(self.ax.flatten())
        return True

    def save(self, filename=None, savefig=True, **kwargs):
        if hasattr(self, '_DO_NOT_SAVE') and self._DO_NOT_SAVE == True:
            return

        self._save(filename, savefig=True, **kwargs)

    def findconversion(self, dur=.1, stepsize=1):
        '''
        Returns false or 
        [the phi_0/V to make phi_0 jump at med,
         the flux bias point necessary to make the jump]
        '''
        istuned = self.tune_squid()
        if not istuned:
            return [False, self.saaconversion, -1]
        islocked = self.lock_squid()
        if not islocked:
            return [False, self.saaconversion, -1]
        sfluxlim = self.squidarray.S_flux_lim
        self.squidarray.sensitivity = 'Medium'
        return self._findconversion('S_flux', sfluxlim, stepsize, dur)

    def _findconversion(self, attrname, maxattrval, stepsize=1, dur=.1):
        '''
        To find the phi_0/v, one must have a locked device (squid or saa)
        and increment some parameter (s_flux, a_flux) until you see a 
        jump.

        returns false or 
        [phi_0/V at med, sflux to get the jump]
        '''


        self.squidarray.testSignal='Off'
        self.squidarray.sensitivity = 'Medium'
        setattr(self.squidarray, attrname, 0)
        self.squidarray.reset()

        for attrval in np.arange(0, maxattrval+1, stepsize):
            self.squidarray.sensitivity = 'Medium'
            setattr(self.squidarray, attrname, attrval)
            premean, prestd = self._getmean(dur)
            self.squidarray.reset()
            posmean, posstd = self._getmean(dur)
            if np.abs(premean - posmean) > 8*np.maximum(prestd, posstd):
                print(attrname, '=', attrval)
                return [True, 1/abs(posmean - premean), attrval]

        return [False, self.saaconversion, -1]




class ArrayTuneBatch(Measurement):
    def __init__(self, 
                 instruments,
                 sbias = [0], 
                 aflux = [0], 
                 sflux = [0],
                 squid_tol = 100e-3, 
                 aflux_tol = 10e-3, 
                 sbias_ex = 100,
                 aflux_ex = 0,
                 save_appendedpath = '',
                 conversion=1/1.44,
                 debug=False):
        '''
        Test a squid automatically with a SAA 

        Work in progress

        live plotting only plots the first element of sflux, all of 
        sbias and aflux
        '''
        
        super(ArrayTuneBatch, self).__init__(instruments=instruments)

        self.instruments = instruments
        self.sbias = np.array(sbias) 
        self.aflux = np.array(aflux)
        self.sflux = np.array(sflux)
        self.squid_tol = squid_tol
        self.aflux_tol = aflux_tol
        self.save_appendedpath = save_appendedpath
        self.sbias_ex = sbias_ex
        self.aflux_ex = aflux_ex
        self.conversion = conversion

        self.cmap = matplotlib.cm.viridis
        self.cmap.set_bad('white', 1.)
        self.arraytunefilenames = []
        self.leastlineari = -1 
        self.leastlinearval = 1e9
        self.debug = debug

    def findconversion(self, stepsize=5, dur=.001):
        self.caltrue       = np.zeros((len(self.sbias), len(self.aflux)))
        self.saaconversion = np.full((len(self.sbias), len(self.aflux)), np.nan)
        self.conv_sflux    = np.full((len(self.sbias), len(self.aflux)), np.nan)
        ix = -1 
        iy = -1 
        for sb in self.sbias:
            print('Sbias = ', sb)
            ix += 1
            iy = -1 
            for af in self.aflux:
                iy += 1
                at = ArrayTune(self.instruments, squid_bias=sb, 
                       squid_tol = self.squid_tol,
                       aflux_tol = self.aflux_tol,
                       sflux_offset = 0,
                       aflux_offset = af,
                       conversion=self.conversion, debug=self.debug)
                [caltrue, 
                 saaconversion, 
                 conv_sflux
                ] = at.findconversion( stepsize=stepsize, dur=dur)
                if caltrue:
                    self.caltrue[ix][iy] = caltrue 
                    self.saaconversion[ix][iy] = saaconversion
                    self.conv_sflux[ix][iy]  = conv_sflux

    def plotconversion(self):
        fig, axs = plt.subplots(1,2)
        for data,cbarlabel,ax,cmap in zip(
                [self.saaconversion, self.conv_sflux], 
                ['V/phi_0', 'S_flux V'],
                axs, 
                ['viridis', 'magma']):
            masked_data = np.ma.array(data, mask=np.isnan(data))
            image = ax.imshow(masked_data, self.cmap, origin='lower',
                              extent=[self.aflux.min(), self.aflux.max(),
                                      self.sbias.min()*1e-3,
                                      self.sbias.max()*1e-3])
            d = make_axes_locatable(ax)
            cax = d.append_axes('right', size=.1, pad=.1)
            cbar = plt.colorbar(image, cax=cax)
            cbar.set_label(cbarlabel, rotation=270, labelpad=12)

                

    def do(self, liveplot = True):

        # Take 1 arraytune scan
        # use that to create the entire structure
        # That way, if it fails, it will fail at the beginning

        # things to save:
        # spectrum:
        #   1 copy of f (Hz)
        #   n copies of psdave * conversion (phi_0)
        # mutalinductance2:
        #   n copies of Vsrc / Rbias (Amps)
        #   n copies of Vmeas * conversion (phi_0)
        # array_tune:
        #   n copies of char[1] (test signal, V)
        #   n copies of char[2] (saa signal,  V)
        # n copies of sbias, aflux, sflux


        # name of nparrays to be saved in this object
        # order follows all the "n copies" of stuff in the above
        # comment
        self.savenames = ['spectrum_psd', 'sweep_fcIsrc', 'sweep_sresp',
                           'char_testsig', 'char_saasig']
        first = True
        maxlen = len(self.sbias)*len(self.aflux)*len(self.sflux)
        self.spectrum_f = np.array([])
        self.lockparams = np.zeros( (maxlen, 3))
        self.success    = np.array(np.zeros(maxlen),dtype=bool) # zero = false

        sbindex = 0

        # try out a point that you know will work to tell the code 
        # how large stuff should be
        print('Test run')
        [_, first] = self._tunesave(0, self.sbias_ex, self.aflux_ex, 0, 
                                    first, save=False)
        print('')

        index = 0

        for sb in self.sbias:
            plottingindex = [] # for live plotting
            for af in self.aflux:
                plottingindex.append(index)
                for sf in self.sflux:
                    [index, first] = self._tunesave(index,sb,af,sf,first)
            print('End of Afluxes')
            print(plottingindex)

            sys.stdout.flush()

            if liveplot:
                [noise_z, lin_z] = self.plot_makeline(plottingindex)
                self.plotting_z[0][sbindex, :] = noise_z
                self.plotting_z[1][sbindex, :] = lin_z
                self.plot_live()

            sbindex += 1 

        print('Least linear: {0:2.2e} (index={1})'.format(
                self.leastlinearval,
                self.leastlineari))
        print(self.currminstostr())
        

    def _tunesave(self, index, sb, af, sf, first, save=True):
        '''
        Create arraytune, run it, and save it if it is good
        '''

        self.lockparams[index] = np.array([sb, af, sf])

        at = ArrayTune(self.instruments, squid_bias=sb, 
                       squid_tol = self.squid_tol,
                       aflux_tol = self.aflux_tol,
                       sflux_offset = sf,
                       aflux_offset = af,
                       conversion=self.conversion, debug=self.debug)
        locked = at.run(save_appendedpath=self.save_appendedpath)

        if save:
            self.arraytunefilenames.append(at.filename)


        if not locked: # Squid is not locked, do not save
            index += 1
            return [index, first]

        if not first:  # first scan populates arrays, it doesn't count
            self.success[index] = True #index was incremented

        # what to save
        tosave = [np.array(at.spectrum.psdAve * at.spectrum.conversion),
                  np.array(at.sweep.Vsrc / at.sweep.Rbias),
                  np.array(at.sweep.Vmeas * at.sweep.conversion),
                  np.array(at.char[1]), 
                  np.array(at.char[2])
                 ]

        if first: # do not know size until you try
            maxlen = len(self.sbias)*len(self.aflux)*len(self.sflux)
            ArrayTuneBatch._makestruct(self, tosave, self.savenames, maxlen)
            self.spectrum_f = np.array(at.spectrum.f)
            first = False

        if save:
            ArrayTuneBatch._savetostruct(self, tosave, self.savenames, index)

        index += 1


        return [index, first]


    def plot_makeline(self, indexes):
        '''
        make lines for liveplot
        '''
        n_l_z = np.full(len(self.aflux), np.nan)
        l_l_z = np.full(len(self.aflux), np.nan)

        index_fstart = np.argmin(abs(self.spectrum_f - 100))
        index_fstop  = np.argmin(abs(self.spectrum_f - 1000))

        for j,i in zip(range(len(n_l_z)), indexes):
            print(i)
            sys.stdout.flush()

            if not self.success[i]:
                continue

            n_l_z[j] = np.sqrt(np.mean(np.square(
                    (self.spectrum_psd[i])[index_fstart:index_fstop])))
            
            fcIsrchasnan = np.any(np.isnan(self.sweep_fcIsrc[i]))
            sresphasnan  = np.any(np.isnan(self.sweep_sresp[i]))

            if fcIsrchasnan or sresphasnan:  
                print('Nans! THIS SHOULD NEVER HAPPEN')
                sys.stdout.flush()
                continue

            [p,v] = np.polyfit(self.sweep_fcIsrc[i], self.sweep_sresp[i],1,
                             cov=True)
            l_l_z[j] = v[0][0]
            
            if l_l_z[j] < self.leastlinearval:
                self.leastlinearval = l_l_z[j]
                self.leastlineari = i
        return [n_l_z, l_l_z]

    def setup_plots(self):
        # 2D live plot:
        #   squid bias vs array flux vs noise
        #   squid bias vs array flux vs measure of linearity
        # 1D plot:
        #   waterfall (offset by array flux) of squid characteristic

        self.fig, self.axes = plt.subplots(1,2, figsize=(16,4))
        self.axes = list(self.axes.flatten())

        self.plotting_z = [
                np.full((len(self.sbias), len(self.aflux)), np.nan),
                np.full((len(self.sbias), len(self.aflux)), np.nan)
                          ]
        self.plotting_z_names = ['Noise', 'Linearity']
        self.images = []
        self.cbars  = []
        for ax, data, cbarlabel in zip(
                [self.axes[0], self.axes[1]], 
                self.plotting_z,
                [r'rms noise ($\phi_0/\sqrt{Hz}$)', 
                 r'linearity (covar of fit)']
                ):
            masked_data = np.ma.array(data, mask=np.isnan(data))
            image = ax.imshow(masked_data, self.cmap, origin='lower',
                              extent=[self.aflux.min(), self.aflux.max(),
                                      self.sbias.min()*1e-3,
                                      self.sbias.max()*1e-3])

            d = make_axes_locatable(ax)
            cax = d.append_axes('right', size=.1, pad=.1)
            cbar = plt.colorbar(image, cax=cax)
            cbar.set_label(cbarlabel, rotation=270, labelpad=12)
            cbar.formatter.set_powerlimits( (-2,2))

            ax.set_ylabel('S bias (mA)')
            ax.set_xlabel('A flux offset (V)')

            self.cbars.append(cbar)
            self.images.append(image)

            self.fig.tight_layout()
            self.fig.canvas.draw()
            plt.pause(.001)


    def plot_live(self):
        for image,cbar,data in zip(self.images,self.cbars,self.plotting_z):
            masked_data = np.ma.array(data, mask=np.isnan(data))
            image.set_data(masked_data)
            cbar.set_clim([masked_data.min(), masked_data.max()])
            cbar.draw_all()
        self.fig.canvas.draw()
        plt.pause(.001)


    def plot_characteristic(self):
        fig,ax = plt.subplots(1,2)

        # max/min
        charmaxmin = np.array( [c.max - c.min() for c in self.char_saasig])
        charmaxmin.reshape( self.plotting_z[0].shape)
        masked_maxmin = np.ma.array(charmaxmin, mask=charmaxmin==0)

        ax[0].imshow(masked_maxmin, self.cmap, origin='lower',
                              extent=[self.aflux.min(), self.aflux.max(),
                                      self.sbias.min()*1e-3,
                                      self.sbias.max()*1e-3])
        d = make_axes_locatable(ax[0])
        cax = d.append_axes('right', size=.1, pad=.1)
        cbar = plt.colorbar(image, cax=cax)
        cbar.set_label('Vpp of characteristic (V)', 
                        rotation=270, labelpad=12)
        cbar.formatter.set_powerlimits( (-2,2))

        ax[0].set_ylabel('S bias (mA)')
        ax[0].set_xlabel('A flux offset (V)')

        # slope
        # work in progress
        # argsort, sort the testsignal, return indicies
        # order char by those indicies
        # argmin(abs(char)), find sufficiently large gap in V around
        # that point, that is the gradient

    @staticmethod
    def findmin(plotting_z, plotting_z_names):
        mins = []
        for data,name in zip(plotting_z, plotting_z_names):
            minval = np.nanmin(data)
            minind = np.nanargmin(data)
            (miny,minx)  = np.unravel_index(minind, data.shape)
            mins.append([name, minval, minind, miny, minx])
        return mins

    @staticmethod
    def minstostr(mins, sbias_y, aflux_x, filenames):
        st = ''
        for m in mins:
            st +="{0}: {1:3.3e} <- sbias={2:2.2f}, aflux={3:2.2f}: {4}".format(
                    m[0], m[1], sbias_y[m[3]], aflux_x[m[4]], filenames[m[2]])
            st += '\n'
        return st

    @staticmethod
    def sorter(master, *args):
        ks = np.argsort(master.flatten())
        arrs = [master, *args]
        for i in range(len(arrs)):
            arrs[i] = arrs[i][ks]
        return arrs

    def currsort(self):
        return self.sorter(self.plotting_z[0].flatten(), self.plotting_z[1].flatten(), 
                      np.array(self.arraytunefilenames))

    def printsort(self, num=10):
        n, l, f = self.currsort()
        print('Noise     Linearity  Filename')
        for i in range(num):
            print('{0:2.2e}  {1:2.2e}   {2}'.format(n[i], l[i], f[i]))
            
        
    def currminstostr(self):
        return self.minstostr(
                    self.findmin(self.plotting_z, self.plotting_z_names),
                    self.sbias, self.aflux, self.arraytunefilenames)










    def plot(self):
        pass


    @staticmethod
    def _makestruct(obj, tosave, savenames, maxlen):
        for name, item in zip(savenames, tosave):
            setattr(obj, name, np.full( (maxlen, len(item)), np.nan))

    @staticmethod
    def _savetostruct(obj, tosave, savenames, index):
        for name, item in zip(savenames, tosave):
            try:
                getattr(obj, name)[index] = item
            except:
                print('Cannot set {0} of len {1}'.format(item, len(item)),
                       ' to {2} expecting len {3}'.format(name, 
                           len(getattr(obj, name)[index]))
                      )

                    
                                   

