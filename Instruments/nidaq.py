import sys, os

home = os.path.expanduser("~")
sys.path.append(os.path.join(home,'Documents','GitHub','Instrumental'))

from instrumental.drivers.daq import ni
from instrumental import u
import numpy as np
try:
    import PyDAQmx as mx
except:
    print('PyDAQmx not imported!')
import time
from copy import copy
from ..Utilities.logging import log

class NIDAQ():
    '''
    For remote operation of the NI DAQ-6363.
    Slightly simplified version of Guen's squidpy driver;
    does not import/inherit anything from squidpy.
    Uses package Instrumental from Mabuchi lab at Stanford
    '''
    inputs = {}

    def __init__(self, zero=False, dev_name='Dev1', input_range=10, output_range=10):
        self._daq  = ni.NIDAQ(dev_name, input_range, output_range)
        self._dev_name = dev_name
        self._input_range = input_range
        self._output_range = output_range

        ## Set properties for reading input channels
        ## Read from these by daq.ao# (#=0-31)
        for chan in self._daq.get_AI_channels():
            setattr(NIDAQ,chan,property(fget=eval('lambda self: self.get_chan(\'%s\')' %chan)))

        ## Set properties for reading and writing output channels
        for chan in self._daq.get_AO_channels():
            setattr(self, '_%s' %chan, None)# privately store value
            setattr(NIDAQ,chan,property(fset=eval('lambda self, value: self.set_chan(\'%s\',value)' %chan), fget=eval('lambda self: self.get_chan(\'%s\')' %chan)))

        if zero:
            self.zero()


    def __getstate__(self):
        self.save_dict = {}
        for chan in self._daq.get_AI_channels():
            self.save_dict[chan] = getattr(self, chan)
        for chan in self._daq.get_AO_channels():
            self.save_dict[chan] = getattr(self, chan)
        self.save_dict.update({
            'device name': self._dev_name,
            'input range': self._input_range,
            'output range': self._output_range
        })

        return self.save_dict


    def __setstate__(self, state):
        self._daq = ni.NIDAQ(state['device name'], state['input range'], state['output range'])


    def accel_function(self, start,end, numpts):
        """ Does an x**2-like ramp. Code looks weird but test it if you want! ^_^ """
        '''
        NO THIS IS ACTUALLY CRAP DON'T USE THIS
        '''
        if start == end:
            return [start]*numpts*2 # just return array of the same value
        part1arg = np.linspace(start, (end-start)/2+start, numpts)
        part2arg = np.linspace((end-start)/2+start, end, numpts)
        part1 = start+ (part1arg-start)**2/((end-start)/2)**2*(end-start)/2
        part2 = end-(part2arg-end)**2/((end-start)/2)**2*(end-start)/2
        return list(part1)+list(part2[1:])


    def all(self):
        '''
        Returns a dictionary of all channel voltages.
        '''
        voltages = {}
        for chan in self._daq.get_AO_channels() + self._daq.get_AI_channels():
            voltages[chan] =  getattr(self, chan)
        return voltages


    def get_chan(self, chan):
        '''
        Read the current value of an input or output channel.
        Normally you don't have to use this; __init__ sets up properties for
        daq.ai# and daq.ao# so you can read them like that.
        '''
        return getattr(self._daq,chan).read().magnitude


    def set_chan(self, chan, data):
        '''
        Set an output channel voltage. Normally you don't have to use this;
        __init__ sets up properties for daq.ao# so you can do (e.g.):
        daq.ao# = 3
        '''
        setattr(self, '_%s' %chan, data)
        if np.isscalar(data):
            getattr(self._daq,chan).write(
                '%sV' %data
            ) #Dunno why the V is there, maybe because of units in Instrumental?


    def monitor(self, chan_in, duration, sample_rate=100):
        '''
        Monitor any number of channels for a given duration, sampling at sample_rate.
        Default 100 Hz sample rate.
        '''
        if np.isscalar(chan_in):
            chan_in = [chan_in]

        ## Prepare "data" for the Task. We'll just send the current value of ao0
        ## and tell the DAQ to output that value of ao0 for every data point.
        numsteps = int(duration*sample_rate)
        current_ao0 = self.ao0
        data = {'ao0': np.array([current_ao0]*numsteps)}

        received = self.send_receive(data, chan_in=chan_in, sample_rate=sample_rate)

        return received


    def send_receive(self, data, chan_in=None, sample_rate=100):
        '''
        Send data to daq outputs and receive data on input channels.
        Data should be a dictionary with keys
        "ao#", and values can be float, list, or np.ndarray.
        Arrays should be equally sized for all output channels.
        chan_in is a list of all input channels you wish to monitor.
        '''
        ## Make everything a numpy array
        data = data.copy() # so we don't modify original data
        for key, value in data.items():
            value = value.copy() # so we don't modify original data
            if np.isscalar(value):
                value = np.array([value])
            elif type(value) is list:
                value = np.array(value)

            ## Make sure daq does not go out of range
            absmax = abs(value).max()
            if absmax > self._output_range:
                raise Exception('%s is out of range for DAQ with output range %s!' %(absmax,self._output_range))

            ## Repeat the last data point.
            ## The DAQ for some reason gives data points late by 1. (see later)
            value = np.append(value, value[-1])

            ## Add units for Instrumental
            value = value * u.V

            data[key] = value


        ## Make sure there's at least one input channel (or DAQmx complains)
        if chan_in is None:
            chan_in = ['ai23']
        elif np.isscalar(chan_in):
            chan_in = [chan_in]

        ## prepare a NIDAQ Task
        taskargs = tuple([getattr(self._daq, ch) for ch in list(data.keys())+chan_in])
        task = ni.Task(*taskargs)
        some_data = next(iter(data.values())) # All data must be equal length, so just choose one.
        task.set_timing(n_samples = len(some_data), fsamp='%fHz' %sample_rate)

        ## run the task and remove units
        received = task.run(data)
        for key, value in received.items():
            received[key] = value.magnitude

        ## Undo added data point
        ## The daq gives data late by one.
        ## This only happens on the lowest numbered input channel.
        ## the nowacklab branch of Instrumental is modified so that channels
        ## are ordered, and in this case it's the lowest numbered channel.
        # First we find the input channel numbers as ints, then find the min.
        ch_nums = [int(''.join(x for x in y if x.isdigit())) for y in chan_in]
        min_chan = 'ai%i' %min(ch_nums)

        for chan, value in received.items():
            if chan == min_chan:
                received[chan] = np.delete(value, 0) #removes first data point, which is wrong
            else:
                received[chan] = np.delete(value,-1) #removes last data point, a duplicate

        return received


    def sweep(self, Vstart, Vend, chan_in=None, sample_rate=100, numsteps=1000):
        '''
        Sweeps between voltages specified in Vstart and Vend, dictionaries with
        output channels as keys. (e.g. Vstart={'ao1':3, 'ao2':4})
        Specify the input channels you want to monitor.
        Returns (output voltage dictionary, input voltage dictionary)
        '''

        output_data = {}
        for k in Vstart.keys():
            output_data[k] = np.linspace(Vstart[k], Vend[k], numsteps)

        received = self.send_receive(output_data, chan_in, sample_rate=sample_rate)

        return output_data, received


    def zero(self):
        for chan in self._daq.get_AO_channels():
            self.sweep({chan: getattr(self, chan)}, {chan: 0}, sample_rate=100000, numsteps=100000)
        print('Zeroed DAQ outputs.')
        log('Zeroed DAQ outputs.')


if __name__ == '__main__':
    nidaq = NIDAQ()

    out_data = []
    in_data = []
    num = 100
    vmax = 5
    for i in range(num):
        nidaq.ao3 = vmax*i/num
        out_data.append(nidaq.ao3)
        in_data.append(nidaq.ai3)
    for i in range(num):
        nidaq.ao3 = vmax-vmax*i/num
        out_data.append(nidaq.ao3)
        in_data.append(nidaq.ai3)
    import matplotlib.pyplot as plt
    plt.plot(in_data)
    plt.show()
