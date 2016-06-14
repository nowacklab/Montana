""" Procedure to take an mod 2D plot of IV's for a SQUID. By default, assumes SQUID -40 uA to 40 uA sweep (0.5 uA step) and mod -100 uA to 100 uA sweep (4 uA step), both over a 2kOhm bias resistor. Can change these values when prompted. """

from IPython import display
import matplotlib.pyplot as plt
import numpy as np
import time
from . import squidIV

class Mod2D():
    def __init__(self, instruments, squidout, squidin, modout, rate=900):   
        """ Example: Mod2D({'daq': daq, 'preamp': preamp}, 'ao0','ai0','ao1', rate=900) """
    
        self.filename = time.strftime('%Y%m%d_%H%M%S') + '_mod2D'
        self.notes = ''

        self.IV = squidIV.SquidIV(instruments, squidout, squidin, modout, rate=rate)

        self.IV.preamp.gain = 500 
        self.IV.preamp.filter = (0, rate) # Hz  
        
        self.IV.Rbias = 2e3 # Ohm # 1k cold bias resistors on the SQUID testing PCB
        self.IV.Rbias_mod = 2e3 # Ohm # 1k cold bias resistors on the SQUID testing PCB
        self.IV.Irampspan = 80e-6 # A # Will sweep from -Irampspan/2 to +Irampspan/2
        self.IV.Irampstep = 0.5e-6 # A # Step size

        self.Imodspan = 200e-6
        self.Imodstep = 4e-6
        
        self.IV.calc_ramp()
        self.calc_ramp()
       
        self.setup_plot()
        display.clear_output()
        
    def calc_ramp(self):
        self.numpts = int(self.Imodspan/self.Imodstep)        
        self.Imod = np.linspace(-self.Imodspan/2, self.Imodspan/2, self.numpts) # Squid current
        self.V = np.array([[float('nan')]*self.IV.numpts]*self.numpts) # num points in IV by num points in mod sweep
        
    def do(self):
        self.param_prompt() # Check parameters

        for i in range(len(self.Imod)):
            self.IV.Imod = self.Imod[i]
            self.IV.do_IV()
            self.IV.plot(self.axIV)
            self.V[:][i] = self.IV.V
            self.plot()
            
        inp = input('Press enter to save data, type anything else to quit. ')
        if inp == '':
            self.save()
        self.daq.zero() # zero everything
        
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

        self.notes = input('Notes for this mod2D: ')
        self.IV.notes = self.notes # or else it will complain when plotting :(
         
    def plot(self):

        Vm = np.ma.masked_where(np.isnan(self.V),self.V) #hides data not yet collected
        self.im = self.ax2D.pcolor(self.IV.I*1e6, self.Imod*1e6, Vm, cmap='RdBu')
        
        display.display(self.fig)
        display.clear_output(wait=True)

        
    def save(self):
        data_folder = 'C:\\Users\\Hemlock\\Dropbox (Nowack lab)\\TeamData\\Montana\\squid_testing\\mod2D\\'

        filename = data_folder + self.filename
        with open(filename+'.txt', 'w') as f:
            f.write(self.notes+'\n')
            f.write('Montana info: \n'+self.IV.montana.log()+'\n')
            for param in ['rate', 'Rbias', 'Rbias_mod', 'Irampspan', 'Irampstep']:
                f.write('IV' + param + ': ' + str(getattr(self.IV, param)) + '\n')
            for parammod in ['Imodspan','Imodstep']:
                f.write(parammod + ': ' + str(getattr(self, parammod)) + '\n')
            for paramamp in ['gain','filter']:
                f.write('IV preamp ' + paramamp + ': ' + str(getattr(self.IV.preamp, paramamp)) + '\n') 
           
            f.write('Isquid (V)\tImod (V)\tVsquid (V)\n')
            for i in range(self.numpts): 
                for j in range(self.IV.numpts):
                    if self.V[i][j] != None:
                        f.write('%f' %self.IV.I[j] + '\t' + '%f' %self.Imod[i] + '\t' + '%f' %self.V[i][j] + '\n')
        
        plt.figure(self.fig.number)
        plt.savefig(filename+'.pdf', bbox_inches='tight')
        
    def setup_plot(self):
        self.fig, (self.axIV, self.ax2D) = plt.subplots(1,2,figsize=(10,5))
        
        self.ax2D.set_aspect(0.5)
        self.plot()
        self.ax2D.set_title(self.filename+'\n'+self.notes) # NEED DESCRIPTIVE TITLE
        self.ax2D.set_xlabel(r'$I_{\rm{bias}} = V_{\rm{bias}}/R_{\rm{bias}}$ ($\mu \rm A$)', fontsize=20)
        self.ax2D.set_ylabel(r'$I_{\rm{mod}} = V_{\rm{mod}}/R_{\rm{mod}}$ ($\mu \rm A$)', fontsize=20)
        cb = self.fig.colorbar(self.im, ax = self.ax2D)
        cb.set_label(label = r'$V_{\rm{squid}}$ (V)', fontsize=20)