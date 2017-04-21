import numpy as np
from numpy.linalg import lstsq
import time, os
from datetime import datetime
from scipy.interpolate import interp1d
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
from IPython import display
from numpy import ma
from ..Utilities.plotting import plot_mpl
from ..Instruments import piezos, montana, squidarray
from ..Utilities.save import Measurement, get_todays_data_dir
from ..Utilities import conversions
from ..Utilities.utilities import AttrDict

class Scanplane(Measurement):
    _chan_labels = ['dc','cap','acx','acy'] # DAQ channel labels expected by this class. You may add chan labels but don't change these!
    _conversions = AttrDict({
        'dc': conversions.Vsquid_to_phi0,
        'cap': conversions.V_to_C,
        'acx': conversions.Vsquid_to_phi0,
        'acy': conversions.Vsquid_to_phi0,
        'x': conversions.Vx_to_um,
        'y': conversions.Vy_to_um
    })
    _units = AttrDict({  ### Do conversions and units cleanly in the future within the DAQ class!!
        'dc': 'phi0',
        'cap': 'C',
        'acx': 'phi0',
        'acy': 'phi0',
        'x': '~um',
        'y': '~um',
    })
    instrument_list = ['piezos',
                       'montana',
                       'squidarray',
                       'preamp',
                       'lockin_squid',
                       'lockin_cap',
                       'atto',
                       'daq']
    ## Put things here necessary to have when reloading object

    def __init__(self, instruments={}, plane=None, span=[800,800],
                        center=[0,0], numpts=[20,20],
                        scanheight=15, scan_rate=120, raster=False):

        super().__init__()

        self._load_instruments(instruments)

        self.scan_rate = scan_rate
        self.raster = raster
        self.span = span
        self.center = center
        self.numpts = numpts
        self.plane = plane

        self.V = AttrDict({
           chan: np.nan for chan in self._chan_labels + ['piezo']
        })
        self.Vfull = AttrDict({
           chan: np.nan for chan in self._chan_labels + ['piezo']
        })
        self.Vinterp = AttrDict({
           chan: np.nan for chan in self._chan_labels + ['piezo']
        })

        self.scanheight = scanheight

        x = np.linspace(center[0]-span[0]/2, center[0]+span[0]/2, numpts[0])
        y = np.linspace(center[1]-span[1]/2, center[1]+span[1]/2, numpts[1])

        self.X, self.Y = np.meshgrid(x, y)
        try:
            self.Z = self.plane.plane(self.X, self.Y) - self.scanheight
        except:
            print('plane not loaded... no idea where the surface is without a plane!')

        for chan in self._chan_labels:
            self.V[chan] = np.full(self.X.shape, np.nan) #initialize arrays
            if chan not in self._conversions.keys(): # if no conversion factor given
                self._conversions[chan] = 1
            if chan not in self._units.keys():
                self._units[chan] = 'V'

        self.fast_axis = 'x' # default; modified as a kwarg in self.do()

    def do(self, fast_axis = 'x', surface=False): # surface False = sweep in lines, True sweep over plane surface
        self.fast_axis = fast_axis
        ## Start time and temperature
        tstart = time.time()
        #temporarily commented out so we can scan witout internet on montana
        #computer
        #self.temp_start = self.montana.temperature['platform']

        self.setup_plots()

        ## make sure all points are not out of range of piezos before starting anything
        for i in range(self.X.shape[0]):
            self.piezos.x.check_lim(self.X[i,:])
            self.piezos.y.check_lim(self.Y[i,:])
            self.piezos.z.check_lim(self.Z[i,:])

        ## Loop over Y values if fast_axis is x, X values if fast_axis is y
        if fast_axis == 'x':
            num_lines = int(self.X.shape[0]) # loop over Y
        elif fast_axis == 'y':
            num_lines = int(self.X.shape[1]) # loop over X
        else:
            raise Exception('Specify x or y as fast axis!')

        ## Measure capacitance offset
        Vcap_offset = []
        for i in range(5):
            time.sleep(0.5)
            Vcap_offset.append(self.lockin_cap.convert_output(self.daq.inputs['cap'].V))
        Vcap_offset = np.mean(Vcap_offset)

        for i in range(num_lines): # loop over every line
            k = 0
            if self.raster:
                if i%2 == 0: # if even
                    k = 0 # k is used to determine Vstart/Vend. For forward, will sweep from the 0th element to the -(k+1) = -1st = last element
                else: # if odd
                    k = -1 # k is used to determine Vstart/Vend. For forward, will sweep from the -1st = last element to the -(k+1) = 0th = first element
            # if not rastering, k=0, meaning always forward sweeps

            ## Starting and ending piezo voltages for the line
            if fast_axis == 'x':
                Vstart = {'x': self.X[i,k], 'y': self.Y[i,k], 'z': self.Z[i,k]} # for forward, starts at 0,i; backward: -1, i
                Vend = {'x': self.X[i,-(k+1)], 'y': self.Y[i,-(k+1)], 'z': self.Z[i,-(k+1)]} # for forward, ends at -1,i; backward: 0, i
            elif fast_axis == 'y':
                Vstart = {'x': self.X[k,i], 'y': self.Y[k,i], 'z': self.Z[k,i]} # for forward, starts at i,0; backward: i,-1
                Vend = {'x': self.X[-(k+1),i], 'y': self.Y[-(k+1),i], 'z': self.Z[-(k+1),i]} # for forward, ends at i,-1; backward: i,0

            ## Explicitly go to first point of scan
            self.piezos.sweep(self.piezos.V, Vstart)
            self.squidarray.reset()
            time.sleep(3)

            ## Do the sweep
            if not surface:
                output_data, received = self.piezos.sweep(Vstart, Vend,
                                            chan_in = self._chan_labels,
                                            sweep_rate=self.scan_rate
                                        ) # sweep over X
            else:
                x = np.linspace(Vstart['x'], Vend['x']) # 50 points should be good for giving this to piezos.sweep_surface
                y = np.linspace(Vstart['y'], Vend['y'])
                if fast_axis == 'x':
                    Z = self.plane.surface(x,y)[:,i]
                else:
                    Z = self.plane.surface(x,y)[i,:]
                output_data = {'x': x, 'y':y, 'z': Z}
                output_data, received = self.piezos.sweep_surface(output_data,
                                                        chan_in = self._chan_labels,
                                                        sweep_rate = self.scan_rate
                                                    )

            ## Flip the backwards sweeps
            if k == -1: # flip only the backwards sweeps
                for d in output_data, received:
                    for key, value in d.items():
                        d[key] = value[::-1] # flip the 1D array

            ## Return to zero for a couple of seconds:
            self.piezos.V = 0
            time.sleep(2)

            ## Interpolate to the number of lines
            self.Vfull['piezo'] = output_data[fast_axis] # actual voltages swept in x or y direction
            if fast_axis == 'x':
                self.Vinterp['piezo'] = self.X[i,:]
            elif fast_axis == 'y':
                self.Vinterp['piezo'] = self.Y[:,i]


            # Store this line's signals for Vdc, Vac x/y, and Cap
            # Convert from DAQ volts to lockin volts where applicable
            for chan in self._chan_labels:
                self.Vfull[chan] = received[chan]

            for chan in ['acx', 'acy']:
                self.Vfull[chan] = self.lockin_squid.convert_output(self.Vfull[chan])
            self.Vfull['cap'] = self.lockin_cap.convert_output(self.Vfull['cap']) - Vcap_offset

            # Interpolate the data and store in the 2D arrays
            for chan in self._chan_labels:
                if fast_axis == 'x':
                    self.Vinterp[chan] = interp1d(self.Vfull['piezo'], self.Vfull[chan])(self.Vinterp['piezo'])
                    self.V[chan][i,:] = self.Vinterp[chan]
                else:
                    self.Vinterp[chan] = interp1d(self.Vfull['piezo'], self.Vfull[chan])(self.Vinterp['piezo'])
                    self.V[chan][:,i] = self.Vinterp[chan]
            self.save_line(i, Vstart)

            self.plot()


        self.piezos.V = 0
        self.save()

        tend = time.time()
        print('Scan took %f minutes' %((tend-tstart)/60))
        return

    def plot(self):
        '''
        Update all plots.
        '''
        super().plot()

        self.plot_line()

        # TODO fix voltage conversions
        for chan in self._chan_labels:
            data_nan = np.array(self.V[chan], dtype=np.float)
            data_masked = np.ma.masked_where(np.isnan(data_nan), data_nan)

            # Set a new image for the plot
            self.im[chan].set_array(data_masked)
            # Adjust colorbar limits for new data
            self.cbars[chan].set_clim([data_masked.min(),
                                       data_masked.max()])
            self.cbars[chan].draw_all()

        self.fig.canvas.draw()
        self.fig.canvas.flush_events()

    def setup_plots(self):
        '''
        Set up all plots.
        '''
        self.fig, self.axes = plt.subplots(2, 2, figsize=(8,8))
        self.fig_cuts, self.axes_cuts = plt.subplots(4, 1, figsize=(6,8))
        chans = ['dc',
                'cap',
                'acx',
                'acy']
        cmaps = ['RdBu',
                 'afmhot',
                 'magma',
                 'magma']
        clabels = ['DC Flux ($\Phi_o$)',
                   "Capacitance (F)",
                   'AC X ($\Phi_o$)',
                   'AC Y ($\Phi_o$)']

        self.im = AttrDict()
        self.cbars = AttrDict()
        self.lines_full = AttrDict()
        self.lines_interp = AttrDict()

        # Plot the DC signal, capactitance and AC signal on 2D colorplots
        for ax, chan, cmap, clabel in zip(self.axes.flatten(), chans, cmaps, clabels):
            # Convert None in data to NaN
            nan_data = np.array(self.V[chan])
            # Create masked array where data is NaN
            masked_data = np.ma.masked_where(np.isnan(nan_data), nan_data)

            # Plot masked data on the appropriate axis with imshow
            image = ax.imshow(masked_data, cmap=cmap, origin="lower",
                              extent = [self.X.min(), self.X.max(),
                                        self.Y.min(), self.Y.max()])
            # Create a colorbar that matches the image height
            d = make_axes_locatable(ax)
            cax = d.append_axes("right", size=0.1, pad=0.1)
            cbar = plt.colorbar(image, cax=cax)
            cbar.set_label(clabel, rotation=270, labelpad=12)
            cbar.formatter.set_powerlimits((-2,2))
            self.im[chan] = image
            self.cbars[chan] = cbar

        # Plot the last linecut for DC, AC and capacitance signals
        #for ax, chan, clabel in zip(self.axes_cuts, chans, clabels):
        for ax, chan, clabel in zip (self.axes_cuts, chans, clabels):
            self.lines_full[chan] = ax.plot(self.Vfull[piezo],
                                            self.Vfull[chan])
            self.lines_interp[chan] = ax.plot(self.Vinterp[piezo],
                                              self.Vinterp[chan], 'o')


        '''
        ## "Last full scan" plot
        self.ax['line'] = self.fig.add_subplot(313)
        self.ax['line'].set_title(self.filename, fontsize=8)
        self.line_full = self.ax['line'].plot(self.Vfull['piezo'], self.Vfull['dc'], '-.k') # commas only take first element of array? Anyway, it works.

        self.line_interp = self.ax['line'].plot(self.Vinterp['piezo'], self.Vinterp['acx'], '.r', markersize=12)

        self.ax['line'].set_xlabel('Vpiezo %s (V)' %self.fast_axis, fontsize=8)
        self.ax['line'].set_ylabel('Last V AC x line (V)', fontsize=8)

        self.line_full = self.line_full[0] # it is given as an array
        self.line_interp = self.line_interp[0]
        '''

    def plot_line(self):
        # Iterate over the channels (DC, ACX, ACY and Cap) and plot the last
        # linecut for each channel
        for ax, chan, clabel in zip(self.axes_cuts, chans, clabels):
            self.lines_full[chan].set_xdata(self.Vfull['piezo'] *
                                            self._conversions[self.fast_axis])
            self.lines_full[chan].set_ydata(self.Vfull[chan] *
                                            self._conversions[chan])
            self.lines_interp[chan].set_xdata(self.Vfull['piezo'] *
                                            self._conversions[self.fast_axis])
            self.lines_interp[chan].set_ydata(self.Vfull[chan] *
                                            self._conversions[chan])


        self.line_full.set_xdata(self.Vfull['piezo']*self._conversions[self.fast_axis])
        self.line_full.set_ydata(self.Vfull[chan]*self._conversions[chan])
        self.line_interp.set_xdata(self.Vinterp['piezo']*self._conversions[self.fast_axis])
        self.line_interp.set_ydata(self.Vinterp[chan]*self._conversions[chan])

        self.ax['line'].relim()
        self.ax['line'].autoscale_view()

        plot_mpl.aspect(self.ax['line'], .3)


    def save_line(self, i, Vstart):
        '''
        Saves each line individually to JSON.
        '''
        line = Line()
        line.scan_filename = self.filename
        line.idx = i
        line.Vstart = Vstart
        line.Vfull = AttrDict()
        line.Vfull['dc'] = self.Vfull['dc']
        line.Vfull['piezo'] = self.Vfull['piezo']
        line.save()


class Line(Measurement):
    def __init__(self):
        super().__init__()

    def save(self):
        self._save(os.path.join('extras', self.filename))
