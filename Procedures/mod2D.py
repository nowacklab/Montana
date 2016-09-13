""" Procedure to take an mod 2D plot of IV's for a SQUID. By default, assumes SQUID -40 uA to 40 uA sweep (0.5 uA step) and mod -100 uA to 100 uA sweep (4 uA step), both over a 2kOhm bias resistor. Can change these values when prompted. """

from IPython import display
import matplotlib.pyplot as plt
import numpy as np
import time, os
from datetime import datetime
from . import squidIV
from ..Utilities.plotting import plot_mpl
from ..Utilities.save import Measurement
from ..Utilities.plotting import plot_bokeh as pb

_home = os.path.expanduser("~")
DATA_FOLDER = os.path.join(_home, 'Dropbox (Nowack lab)', 'TeamData', 'Montana', 'squid_testing', 'mod2D')

class Mod2D(Measurement):
    image = None
    def __init__(self, instruments=None, squidout=None, squidin=None, modout=None, rate=900):
        '''
        Example: Mod2D({'daq': daq, 'preamp': preamp}, 'ao0','ai0','ao1', rate=900).
        To make an empty object, then just call Mod2D().
        You can do this if you want to plot previously collected data.
        '''

        self.filename = ''
        self.notes = ''

        self.IV = squidIV.SquidIV(instruments, squidout, squidin, modout, rate=rate)

        self.IV.Rbias = 2e3 # Ohm # 1k cold bias resistors on the SQUID testing PCB
        self.IV.Rbias_mod = 2e3 # Ohm # 1k cold bias resistors on the SQUID testing PCB
        self.IV.Irampspan = 120e-6 # A # Will sweep from -Irampspan/2 to +Irampspan/2
        self.IV.Irampstep = 0.5e-6 # A # Step size

        self.Imodspan = 200e-6
        self.Imodstep = 4e-6

        self.IV.calc_ramp()
        self.calc_ramp()

        display.clear_output()

    def __getstate__(self):
        super().__getstate__() # from Measurement superclass,
                               # need this in every getstate to get save_dict
        self.save_dict.update({"timestamp": self.timestamp,
                              "IV": self.IV,
                              "Imodspan": self.Imodspan,
                              "Imodstep": self.Imodstep,
                              "V": self.V,
                              "notes": self.notes,
                              "Imod": self.Imod
                          })
        return self.save_dict


    def calc_ramp(self):
        self.numpts = int(self.Imodspan/self.Imodstep)
        self.Imod = np.linspace(-self.Imodspan/2, self.Imodspan/2, self.numpts) # Squid current
        self.V = np.full((self.numpts, self.IV.numpts), np.nan)


    def do(self):
        super().make_timestamp_and_filename('mod2D')

        self.calc_ramp() #easy way to clear self.V
        self.IV.V = self.IV.V*0

        self.param_prompt() # Check parameters
        self.setup_plot()

        for i in range(len(self.Imod)):
            self.IV.Imod = self.Imod[i]
            self.IV.do_IV()
            self.IV.plot(show=False)
            self.V[:][i] = self.IV.V
            self.plot()
            self.fig.canvas.draw() #draws the plot; needed for %matplotlib notebook
        self.IV.daq.zero() # zero everything

        self.notes = input('Notes for this mod2D (q to quit without saving): ')
        if inp != 'q':
            self.save()

    def param_prompt(self):
        """ Check and confirm values of parameters """
        correct = False
        while not correct:
            for param in ['rate', 'Rbias', 'Rbias_mod', 'Irampspan', 'Irampstep']:
                print('IV', param, ':', getattr(self.IV, param))
            for parammod in ['Imodspan','Imodstep']:
                print(parammod, ':', getattr(self, parammod))
            for paramamp in ['gain','filter']:
                print('IV preamp', paramamp, ':', getattr(self.IV.preamp, paramamp))

            if self.IV.rate > self.IV.preamp.filter[1]:
                print("You're filtering out your signal... fix the preamp cutoff\n")
            if self.IV.Irampspan > 200e-6:
                print("You want the SQUID biased above 100 uA?... don't kill the SQUID!\n")
            if self.Imodspan > 300e-6:
                print("You want the SQUID mod biased above 150 uA?... don't kill the SQUID!\n")

            try:
                inp = input('Are these parameters correct? Enter a command to change parameters, or press enter to continue (e.g. IV.preamp.gain = 100): ')
                if inp == '':
                    correct = True
                else:
                    exec('self.'+inp)
                    self.IV.calc_ramp()
                    self.calc_ramp() # recalculate daq output
                    display.clear_output()
            except:
                display.clear_output()
                print('Invalid command\n')

    def plot(self):
        '''
        Plot the 2D mod image
        '''
        if not hasattr(self, 'fig'):
            self.setup_plot()

        self.image = pb.image(self.fig, self.IV.I*1e6, self.Imod*1e6, self.V, z_title = 'V_squid (V)', im_handle = self.image)

    def save(self, savefig=True):
        '''
        Saves the planefit object to json in .../TeamData/Montana/Planes/
        Also saves the figure as a pdf, if wanted.
        '''

        self.tojson(DATA_FOLDER, self.filename)

        if savefig:
            self.fig.savefig(self.filename+'.pdf', bbox_inches='tight')


    def setup_plot(self):
        '''
        Set up the figure. 2D mod image and last IV trace.
        '''
        self.IV.plot(show=False)

        self.fig = pb.figure(
            title=self.filename + ' ' + self.notes,
            xlabel = 'I_bias = V_bias/R_bias (µA)',
            ylabel = 'I_mod = V_mod/R_mod (µA)',
            x_range = self.IV.fig.fig.x_range
        )
        self.fig.fig.plot_width = 1000
        self.fig.fig.plot_height = 1000
        self.fig.fig.min_border_right=50
        self.plot()


        self.grid = pb.plot_grid([[self.fig.fig, self.IV.fig.fig]])
        self.fig.fig.min_border_left = 100

        pb.show(self.grid)
