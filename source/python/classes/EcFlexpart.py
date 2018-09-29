#!/usr/bin/env python
# -*- coding: utf-8 -*-
#*******************************************************************************
# @Author: Anne Fouilloux (University of Oslo)
#
# @Date: October 2014
#
# @Change History:
#
#    November 2015 - Leopold Haimberger (University of Vienna):
#        - extended with class Control
#        - removed functions mkdir_p, daterange, years_between, months_between
#        - added functions darain, dapoly, to_param_id, init128, normal_exit,
#          my_error, clean_up, install_args_and_control,
#          interpret_args_and_control,
#        - removed function __del__ in class EIFLexpart
#        - added the following functions in EIFlexpart:
#            - create_namelist
#            - process_output
#            - deacc_fluxes
#        - modified existing EIFlexpart - functions for the use in
#          flex_extract
#        - retrieve also longer term forecasts, not only analyses and
#          short term forecast data
#        - added conversion into GRIB2
#        - added conversion into .fp format for faster execution of FLEXPART
#          (see https://www.flexpart.eu/wiki/FpCtbtoWo4FpFormat)
#
#    February 2018 - Anne Philipp (University of Vienna):
#        - applied PEP8 style guide
#        - added documentation
#        - removed function getFlexpartTime in class EcFlexpart
#        - outsourced class ControlFile
#        - outsourced class MarsRetrieval
#        - changed class name from EIFlexpart to EcFlexpart
#        - applied minor code changes (style)
#        - removed "dead code" , e.g. retrieval of Q since it is not needed
#        - removed "times" parameter from retrieve-method since it is not used
#
# @License:
#    (C) Copyright 2014-2018.
#
#    This software is licensed under the terms of the Apache Licence Version 2.0
#    which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.
#
# @Class Description:
#    FLEXPART needs grib files in a specifc format. All necessary data fields
#    for one time step are stored in a single file. The class represents an
#    instance with all the parameter and settings necessary for retrieving
#    MARS data and modifing them so they are fitting FLEXPART need. The class
#    is able to disaggregate the fluxes and convert grid types to the one needed
#    by FLEXPART, therefore using the FORTRAN program.
#
# @Class Content:
#    - __init__
#    - write_namelist
#    - retrieve
#    - process_output
#    - create
#    - deacc_fluxes
#
# @Class Attributes:
#
#  TODO
#
#*******************************************************************************
#pylint: disable=unsupported-assignment-operation
# this is disabled because for this specific case its an error in pylint
#pylint: disable=consider-using-enumerate
# this is not useful in this case
# ------------------------------------------------------------------------------
# MODULES
# ------------------------------------------------------------------------------
import subprocess
import shutil
import os
import glob
from datetime import datetime, timedelta
import numpy as np
from gribapi import grib_set, grib_index_select, grib_new_from_index, grib_get,\
                    grib_write, grib_get_values, grib_set_values, grib_release,\
                    grib_index_release, grib_index_get

# software specific classes and modules from flex_extract
import _config
from GribTools import GribTools
from mods.tools import init128, to_param_id, silent_remove, product, my_error
from MarsRetrieval import MarsRetrieval
import mods.disaggregation

# ------------------------------------------------------------------------------
# CLASS
# ------------------------------------------------------------------------------
class EcFlexpart(object):
    '''
    Class to retrieve FLEXPART specific ECMWF data.
    '''
    # --------------------------------------------------------------------------
    # CLASS FUNCTIONS
    # --------------------------------------------------------------------------
    def __init__(self, c, fluxes=False):
        '''
        @Description:
            Creates an object/instance of EcFlexpart with the
            associated settings of its attributes for the retrieval.

        @Input:
            self: instance of EcFlexpart
                The current object of the class.

            c: instance of class ControlFile
                Contains all the parameters of CONTROL file, which are e.g.:
                DAY1(start_date), DAY2(end_date), DTIME, MAXSTEP, TYPE, TIME,
                STEP, CLASS(marsclass), STREAM, NUMBER, EXPVER, GRID, LEFT,
                LOWER, UPPER, RIGHT, LEVEL, LEVELIST, RESOL, GAUSS, ACCURACY,
                OMEGA, OMEGADIFF, ETA, ETADIFF, DPDETA, SMOOTH, FORMAT,
                ADDPAR, WRF, CWC, PREFIX, ECSTORAGE, ECTRANS, ECFSDIR,
                MAILOPS, MAILFAIL, GRIB2FLEXPART, FLEXPARTDIR, BASETIME
                DATE_CHUNK, DEBUG, INPUTDIR, OUTPUTDIR, FLEXPART_ROOT_SCRIPTS

                For more information about format and content of the parameter
                see documentation.

            fluxes: boolean, optional
                Decides if the flux parameter settings are stored or
                the rest of the parameter list.
                Default value is False.

        @Return:
            <nothing>
        '''
        # set a counter for the number of mars requests generated
        self.mreq_count = 0

        # different mars types for retrieving data for flexpart
        self.types = dict()

        if c.maxstep > len(c.type):    # Pure forecast mode
            c.type = [c.type[1]]
            c.step = ['{:0>3}'.format(int(c.step[0]))]
            c.time = [c.time[0]]
            for i in range(1, c.maxstep + 1):
                c.type.append(c.type[0])
                c.step.append('{:0>3}'.format(i))
                c.time.append(c.time[0])

        self.inputdir = c.inputdir
        self.basetime = c.basetime
        self.dtime = c.dtime
        i = 0
        if fluxes and c.maxstep <= 24:
            # no forecast beyond one day is needed!
            # Thus, prepare flux data manually as usual
            # with only forecast fields with start times at 00/12
            # (but without 00/12 fields since these are
            # the initialisation times of the flux fields
            # and therefore are zero all the time)
            self.types[c.type[1]] = {'times': '00/12', 'steps':
                                     '{}/to/12/by/{}'.format(c.dtime, c.dtime)}
        else:
            for ty, st, ti in zip(c.type, c.step, c.time):
                btlist = range(24)
                if c.basetime == '12':
                    btlist = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
                if c.basetime == '00':
                    btlist = [13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 0]

                if i % int(c.dtime) == 0 and (i in btlist or c.maxstep > 24):

                    if ty not in self.types.keys():
                        self.types[ty] = {'times': '', 'steps': ''}

                    if ti not in self.types[ty]['times']:
                        if self.types[ty]['times']:
                            self.types[ty]['times'] += '/'
                        self.types[ty]['times'] += ti

                    if st not in self.types[ty]['steps']:
                        if self.types[ty]['steps']:
                            self.types[ty]['steps'] += '/'
                        self.types[ty]['steps'] += st
                i += 1

        self.marsclass = c.marsclass
        self.stream = c.stream
        self.number = c.number
        self.resol = c.resol
        self.accuracy = c.accuracy
        self.level = c.level
        self.expver = c.expver
        self.levelist = c.levelist
        # for gaussian grid retrieval
        self.glevelist = '1/to/' + c.level

        if hasattr(c, 'gaussian') and c.gaussian:
            self.gaussian = c.gaussian
        else:
            self.gaussian = ''

        if 'N' in c.grid:  # Gaussian output grid
            self.grid = c.grid
            self.area = 'G'
        else:
            self.grid = '{}/{}'.format(int(c.grid) / 1000., int(c.grid) / 1000.)
            self.area = '{}/{}/{}/{}'.format(int(c.upper) / 1000.,
                                             int(c.left) / 1000.,
                                             int(c.lower) / 1000.,
                                             int(c.right) / 1000.)

        self.outputfilelist = []


        # Now comes the nasty part that deals with the different
        # scenarios we have:
        # 1) Calculation of etadot on
        #    a) Gaussian grid
        #    b) Output grid
        #    c) Output grid using parameter 77 retrieved from MARS
        # 3) Calculation/Retrieval of omega
        # 4) Download also data for WRF

        # Different grids need different retrievals
        # SH = Spherical Harmonics, GG = Gaussian Grid,
        # OG = Output Grid, ML = MultiLevel, SL = SingleLevel
        self.params = {'SH__ML': '', 'SH__SL': '',
                       'GG__ML': '', 'GG__SL': '',
                       'OG__ML': '', 'OG__SL': '',
                       'OG_OROLSM_SL': '', 'OG_acc_SL': ''}
        # the self.params dictionary stores a list of
        # [param, levtype, levelist, grid] per key

        if fluxes is False:
            self.params['SH__SL'] = ['LNSP', 'ML', '1', 'OFF']
            #                        "SD/MSL/TCC/10U/10V/2T/2D/129/172"
            self.params['OG__SL'] = ["141/151/164/165/166/167/168/129/172", \
                                     'SFC', '1', self.grid]
            if c.addpar:
                if c.addpar[0] == '/':
                    c.addpar = c.addpar[1:]
                self.params['OG__SL'][0] += '/' + '/'.join(c.addpar)

            self.params['OG_OROLSM__SL'] = ["160/27/28/173", \
                                            'SFC', '1', self.grid]

            self.params['OG__ML'] = ['T/Q', 'ML', self.levelist, self.grid]

            #if c.gauss == '0' and c.eta == '1':
            if not c.gauss and c.eta:
                # the simplest case
                self.params['OG__ML'][0] += '/U/V/77'
            #elif c.gauss == '0' and c.eta == '0':
            elif not c.gauss and not c.eta:
            # this is not recommended (inaccurate)
                self.params['OG__ML'][0] += '/U/V'
            #elif c.gauss == '1' and c.eta == '0':
            elif c.gauss and not c.eta:
                # this is needed for data before 2008, or for reanalysis data
                self.params['GG__SL'] = ['Q', 'ML', '1', \
                                         '{}'.format((int(self.resol) + 1) / 2)]
                self.params['SH__ML'] = ['U/V/D', 'ML', self.glevelist, 'OFF']
            else:
                print('Warning: This is a very costly parameter combination, \
                      use only for debugging!')
                self.params['GG__SL'] = ['Q', 'ML', '1', \
                                         '{}'.format((int(self.resol) + 1) / 2)]
                self.params['GG__ML'] = ['U/V/D/77', 'ML', self.glevelist, \
                                         '{}'.format((int(self.resol) + 1) / 2)]

            if c.omega:
                self.params['OG__ML'][0] += '/W'

            # add cloud water content if necessary
            if c.cwc:
                self.params['OG__ML'][0] += '/CLWC/CIWC'

            # add vorticity and geopotential height for WRF if necessary
            if c.wrf:
                self.params['OG__ML'][0] += '/Z/VO'
                if '/D' not in self.params['OG__ML'][0]:
                    self.params['OG__ML'][0] += '/D'
                #wrf_sfc = 'sp/msl/skt/2t/10u/10v/2d/z/lsm/sst/ci/sd/stl1/ /
                #           stl2/stl3/stl4/swvl1/swvl2/swvl3/swvl4'.upper()
                wrf_sfc = '134/235/167/165/166/168/129/172/34/31/141/ \
                           139/170/183/236/39/40/41/42'
                lwrt_sfc = wrf_sfc.split('/')
                for par in lwrt_sfc:
                    if par not in self.params['OG__SL'][0]:
                        self.params['OG__SL'][0] += '/' + par

        else:
            self.params['OG_acc_SL'] = ["LSP/CP/SSHF/EWSS/NSSS/SSR", \
                                        'SFC', '1', self.grid]

        # if needed, add additional WRF specific parameters here

        return


    def _start_retrievement(self, request, par_dict):
        '''
        @Description:
            Creates the Mars Retrieval and prints or submits the request
            depending on the status of the request variable.

        @Input:
            self: instance of EcFlexpart
                The current object of the class.

            request: integer
                Selects the mode of retrieval.
                0: Retrieves the data from ECMWF.
                1: Prints the mars requests to an output file.
                2: Retrieves the data and prints the mars request.

            par_dict: dictionary
                Contains all parameter which have to be set for creating the
                Mars Retrievals. The parameter are:
                marsclass, stream, type, levtype, levelist, resol, gaussian,
                accuracy, grid, target, area, date, time, number, step, expver,
                param

        @Return:
            <nothing>
        '''
        # increase number of mars requests
        self.mreq_count += 1

        MR = MarsRetrieval(self.server,
                           marsclass=par_dict['marsclass'],
                           stream=par_dict['stream'],
                           type=par_dict['type'],
                           levtype=par_dict['levtype'],
                           levelist=par_dict['levelist'],
                           resol=par_dict['resol'],
                           gaussian=par_dict['gaussian'],
                           accuracy=par_dict['accuracy'],
                           grid=par_dict['grid'],
                           target=par_dict['target'],
                           area=par_dict['area'],
                           date=par_dict['date'],
                           time=par_dict['time'],
                           number=par_dict['number'],
                           step=par_dict['step'],
                           expver=par_dict['expver'],
                           param=par_dict['param'])

        if request == 0:
            MR.display_info()
            MR.data_retrieve()
        elif request == 1:
            MR.print_infodata_csv(self.inputdir, self.mreq_count)
        elif request == 2:
            MR.print_infodata_csv(self.inputdir, self.mreq_count)
            MR.display_info()
            MR.data_retrieve()
        else:
            print('Failure')

        return


    def _mk_targetname(self, ftype, param, date):
        '''
        @Description:
            Creates the filename for the requested grib data to be stored in.
            This name is passed as the "target" parameter in the request.

        @Input:
            ftype: string
                Shortcut name of the type of the field. E.g. AN, FC, PF, ...

            param: string
                Shortcut of the grid type. E.g. SH__ML, SH__SL, GG__ML,
                GG__SL, OG__ML, OG__SL, OG_OROLSM_SL, OG_acc_SL

            date: string
                The date period of the grib data to be stored in this file.

        @Return:
            targetname: string
                The target filename for the grib data.
        '''
        targetname = (self.inputdir + '/' + ftype + param + '.' + date + '.' +
                      str(os.getppid()) + '.' + str(os.getpid()) + '.grb')

        return targetname

    def write_namelist(self, c, filename):
        '''
        @Description:
            Creates a namelist file in the temporary directory and writes
            the following values to it: maxl, maxb, mlevel,
            mlevelist, mnauf, metapar, rlo0, rlo1, rla0, rla1,
            momega, momegadiff, mgauss, msmooth, meta, metadiff, mdpdeta

        @Input:
            self: instance of EcFlexpart
                The current object of the class.

            c: instance of class ControlFile
                Contains all the parameters of CONTROL files, which are e.g.:
                DAY1(start_date), DAY2(end_date), DTIME, MAXSTEP, TYPE, TIME,
                STEP, CLASS(marsclass), STREAM, NUMBER, EXPVER, GRID, LEFT,
                LOWER, UPPER, RIGHT, LEVEL, LEVELIST, RESOL, GAUSS, ACCURACY,
                OMEGA, OMEGADIFF, ETA, ETADIFF, DPDETA, SMOOTH, FORMAT,
                ADDPAR, WRF, CWC, PREFIX, ECSTORAGE, ECTRANS, ECFSDIR,
                MAILOPS, MAILFAIL, GRIB2FLEXPART, FLEXPARTDIR, BASETIME
                DATE_CHUNK, DEBUG, INPUTDIR, OUTPUTDIR, FLEXPART_ROOT_SCRIPTS

                For more information about format and content of the parameter
                see documentation.

            filename: string
                Name of the namelist file.

        @Return:
            <nothing>
        '''

        self.inputdir = c.inputdir
        area = np.asarray(self.area.split('/')).astype(float)
        grid = np.asarray(self.grid.split('/')).astype(float)

        if area[1] > area[3]:
            area[1] -= 360
        maxl = int((area[3] - area[1]) / grid[1]) + 1
        maxb = int((area[0] - area[2]) / grid[0]) + 1

        with open(self.inputdir + '/' + filename, 'w') as f:
            f.write('&NAMGEN\n')
            f.write(',\n  '.join(['maxl = ' + str(maxl), 'maxb = ' + str(maxb),
                                  'mlevel = ' + str(self.level),
                                  'mlevelist = ' + '"' + str(self.levelist)
                                                 + '"',
                                  'mnauf = ' + str(self.resol),
                                  'metapar = ' + '77',
                                  'rlo0 = ' + str(area[1]),
                                  'rlo1 = ' + str(area[3]),
                                  'rla0 = ' + str(area[2]),
                                  'rla1 = ' + str(area[0]),
                                  'momega = ' + str(c.omega),
                                  'momegadiff = ' + str(c.omegadiff),
                                  'mgauss = ' + str(c.gauss),
                                  'msmooth = ' + str(c.smooth),
                                  'meta = ' + str(c.eta),
                                  'metadiff = ' + str(c.etadiff),
                                  'mdpdeta = ' + str(c.dpdeta)]))

            f.write('\n/\n')

        return

    def retrieve(self, server, dates, request, inputdir='.'):
        '''
        @Description:
            Finalizing the retrieval information by setting final details
            depending on grid type.
            Prepares MARS retrievals per grid type and submits them.

        @Input:
            self: instance of EcFlexpart
                The current object of the class.

            server: instance of ECMWFService or ECMWFDataServer
                The connection to the ECMWF server. This is different
                for member state users which have full access and non
                member state users which have only access to the public
                data sets. The decision is made from command line argument
                "public"; for public access its True (ECMWFDataServer)
                for member state users its False (ECMWFService)

            dates: string
                Contains start and end date of the retrieval in the format
                "YYYYMMDD/to/YYYYMMDD"

            request: integer
                Selects the mode of retrieval.
                0: Retrieves the data from ECMWF.
                1: Prints the mars requests to an output file.
                2: Retrieves the data and prints the mars request.

            inputdir: string, optional
                Path to the directory where the retrieved data is about
                to be stored. The default is the current directory ('.').

        @Return:
            <nothing>
        '''
        self.dates = dates
        self.server = server
        self.inputdir = inputdir
        oro = False

        # define times
        t12h = timedelta(hours=12)
        t24h = timedelta(hours=24)

        # dictionary which contains all parameter for the mars request
        # Entries with a "None" will change for different requests and therefore
        # will be set in each request seperately
        retr_param_dict = {'marsclass':self.marsclass,
                           'stream':None,
                           'type':None,
                           'levtype':None,
                           'levelist':None,
                           'resol':self.resol,
                           'gaussian':None,
                           'accuracy':self.accuracy,
                           'grid':None,
                           'target':None,
                           'area':None,
                           'date':None,
                           'time':None,
                           'number':self.number,
                           'step':None,
                           'expver':self.expver,
                           'param':None}

        for ftype in self.types:
            # fk contains fields types such as
            #     [AN, FC, PF, CV]
            # fv contains all of the items of the belonging key
            #     [times, steps]
            for pk, pv in self.params.iteritems():
                # pk contains one of these keys of params
                #     [SH__ML, SH__SL, GG__ML, GG__SL, OG__ML, OG__SL,
                #      OG_OROLSM_SL, OG_acc_SL]
                # pv contains all of the items of the belonging key
                #     [param, levtype, levelist, grid]
                if isinstance(pv, str):
                    continue
                retr_param_dict['type'] = '' + ftype
                retr_param_dict['time'] = self.types[ftype]['times']
                retr_param_dict['step'] = self.types[ftype]['steps']
                retr_param_dict['date'] = self.dates
                retr_param_dict['stream'] = self.stream
                retr_param_dict['target'] = self.inputdir + "/" + ftype + \
                        pk + '.' + self.dates.split('/')[0] + '.' + \
                        str(os.getppid()) + '.' + str(os.getpid()) + ".grb"
                retr_param_dict['param'] = pv[0]
                retr_param_dict['levtype'] = pv[1]
                retr_param_dict['levelist'] = pv[2]
                retr_param_dict['grid'] = pv[3]
                retr_param_dict['area'] = self.area
                retr_param_dict['gaussian'] = self.gaussian

                if pk == 'OG__SL':
                    pass
                if pk == 'OG_OROLSM__SL' and not oro:
                    oro = True
                    retr_param_dict['stream'] = 'OPER'
                    retr_param_dict['type'] = 'AN'
                    retr_param_dict['time'] = '00'
                    retr_param_dict['step'] = '000'
                    retr_param_dict['date'] = self.dates.split('/')[0]
                    retr_param_dict['target'] = self._mk_targetname('',
                                            pk, retr_param_dict['date'])
                elif pk == 'OG_OROLSM__SL' and oro:
                    continue
                if pk == 'GG__SL' and pv[0] == 'Q':
                    retr_param_dict['area'] = ""
                    retr_param_dict['gaussian'] = 'reduced'

    # ------  on demand path  --------------------------------------------------
                if not self.basetime:
                    self._start_retrievement(request, retr_param_dict)
    # ------  operational path  ------------------------------------------------
                else:
                    # check if mars job requests fields beyond basetime.
                    # If yes eliminate those fields since they may not
                    # be accessible with user's credentials
                    if 'by' in retr_param_dict['step']:
                        sm1 = 2
                    else:
                        sm1 = -1

                    if 'by' in retr_param_dict['time']:
                        tm1 = 2
                    else:
                        tm1 = -1

                    maxdate = datetime.strptime(retr_param_dict['date'].split('/')[-1] +
                                                retr_param_dict['time'].split('/')[tm1],
                                                '%Y%m%d%H')
                    maxtime = maxdate + \
                        timedelta(hours=int(retr_param_dict['step'].split('/')[sm1]))

                    elimit = datetime.strptime(retr_param_dict['date'].split('/')[-1] +
                                               self.basetime, '%Y%m%d%H')

                    if self.basetime == '12':
                        # --------------  flux data ----------------------------
                        if 'acc' in pk:

                        # Strategy:
                        # if maxtime-elimit >= 24h reduce date by 1,
                        # if 12h <= maxtime-elimit<12h reduce time for last date
                        # if maxtime-elimit<12h reduce step for last time
                        # A split of the MARS job into 2 is likely necessary.


                            startdate = retr_param_dict['date'].split('/')[0]
                            enddate = datetime.strftime(elimit - t24h,'%Y%m%d')
                            retr_param_dict['date'] = '/'.join([startdate, 'to', enddate])

                            self._start_retrievement(request, retr_param_dict)

                            retr_param_dict['date'] = \
                                datetime.strftime(elimit - t12h, '%Y%m%d')
                            retr_param_dict['time'] = '00'
                            retr_param_dict['target'] = \
                                self._mk_targetname(ftype, pk,
                                                    retr_param_dict['date'])

                            self._start_retrievement(request, retr_param_dict)

                        # --------------  non flux data ------------------------
                        else:
                            self._start_retrievement(request, retr_param_dict)

                    else: # basetime = 0
                        retr_param_dict['date'] = \
                            datetime.strftime(elimit - t24h, '%Y%m%d')

                        timesave = ''.join(retr_param_dict['time'])

                        if '/' in retr_param_dict['time']:
                            times = retr_param_dict['time'].split('/')
                            steps = retr_param_dict['step'].split('/')
                            while (pk != 'OG_OROLSM__SL' and
                                   'acc' not in pk and
                                   (int(times[0]) + int(steps[0])) <= 12):
                                times = times[1:]

                            if len(times) > 1:
                                retr_param_dict['time'] = '/'.join(times)
                            else:
                                retr_param_dict['time'] = times[0]

                        self._start_retrievement(request, retr_param_dict)

                        if (pk != 'OG_OROLSM__SL' and
                            int(retr_param_dict['step'].split('/')[0]) == 0 and
                            int(timesave.split('/')[0]) == 0):

                            retr_param_dict['date'] = \
                                datetime.strftime(elimit, '%Y%m%d')
                            retr_param_dict['time'] = '00'
                            retr_param_dict['step'] = '000'
                            retr_param_dict['target'] = \
                                self._mk_targetname(ftype, pk,
                                                    retr_param_dict['date'])

                            self._start_retrievement(request, retr_param_dict)

        if request == 0 or request == 2:
            print('MARS retrieve done ... ')
        elif request == 1:
            print('MARS request printed ...')

        return


    def process_output(self, c):
        '''
        @Description:
            The grib files are postprocessed depending on the selection in
            CONTROL file. The resulting files are moved to the output
            directory if its not equla to the input directory.
            The following modifications might be done if
            properly switched in CONTROL file:
            GRIB2 - Conversion to GRIB2
            ECTRANS - Transfer of files to gateway server
            ECSTORAGE - Storage at ECMWF server
            GRIB2FLEXPART - Conversion of GRIB files to FLEXPART binary format

        @Input:
            self: instance of EcFlexpart
                The current object of the class.

            c: instance of class ControlFile
                Contains all the parameters of CONTROL file, which are e.g.:
                DAY1(start_date), DAY2(end_date), DTIME, MAXSTEP, TYPE, TIME,
                STEP, CLASS(marsclass), STREAM, NUMBER, EXPVER, GRID, LEFT,
                LOWER, UPPER, RIGHT, LEVEL, LEVELIST, RESOL, GAUSS, ACCURACY,
                OMEGA, OMEGADIFF, ETA, ETADIFF, DPDETA, SMOOTH, FORMAT,
                ADDPAR, WRF, CWC, PREFIX, ECSTORAGE, ECTRANS, ECFSDIR,
                MAILOPS, MAILFAIL, GRIB2FLEXPART, FLEXPARTDIR, BASETIME
                DATE_CHUNK, DEBUG, INPUTDIR, OUTPUTDIR, FLEXPART_ROOT_SCRIPTS

                For more information about format and content of the parameter
                see documentation.

        @Return:
            <nothing>

        '''

        print('\n\nPostprocessing:\n Format: {}\n'.format(c.format))

        if not c.ecapi:
            print('ecstorage: {}\n ecfsdir: {}\n'.
                  format(c.ecstorage, c.ecfsdir))
            #if not hasattr(c, 'gateway'):
            #    c.gateway = os.getenv('GATEWAY')
            #if not hasattr(c, 'destination'):
            #    c.destination = os.getenv('DESTINATION')
            print('ectrans: {}\n gateway: {}\n destination: {}\n '
                  .format(c.ectrans, c.gateway, c.destination))

        print('Output filelist: \n')
        print(self.outputfilelist)

        if c.format.lower() == 'grib2':
            for ofile in self.outputfilelist:
                p = subprocess.check_call(['grib_set', '-s', 'edition=2, \
                                           productDefinitionTemplateNumber=8',
                                           ofile, ofile + '_2'])
                p = subprocess.check_call(['mv', ofile + '_2', ofile])

        if c.ectrans and not c.ecapi:
            for ofile in self.outputfilelist:
                p = subprocess.check_call(['ectrans', '-overwrite', '-gateway',
                                           c.gateway, '-remote', c.destination,
                                           '-source', ofile])
                #print('ectrans:', p)

        if c.ecstorage and not c.ecapi:
            for ofile in self.outputfilelist:
                p = subprocess.check_call(['ecp', '-o', ofile,
                                           os.path.expandvars(c.ecfsdir)])

        if c.outputdir != c.inputdir:
            for ofile in self.outputfilelist:
                p = subprocess.check_call(['mv', ofile, c.outputdir])

        # prepare environment for the grib2flexpart run
        # to convert grib to flexpart binary
        if c.grib2flexpart:

            # generate AVAILABLE file
            # Example of AVAILABLE file data:
            # 20131107 000000      EN13110700              ON DISC
            clist = []
            for ofile in self.outputfilelist:
                fname = ofile.split('/')
                if '.' in fname[-1]:
                    l = fname[-1].split('.')
                    timestamp = datetime.strptime(l[0][-6:] + l[1],
                                                  '%y%m%d%H')
                    timestamp += timedelta(hours=int(l[2]))
                    cdate = datetime.strftime(timestamp, '%Y%m%d')
                    chms = datetime.strftime(timestamp, '%H%M%S')
                else:
                    cdate = '20' + fname[-1][-8:-2]
                    chms = fname[-1][-2:] + '0000'
                clist.append(cdate + ' ' + chms + ' '*6 +
                             fname[-1] + ' '*14 + 'ON DISC')
            clist.sort()
            with open(c.outputdir + '/' + 'AVAILABLE', 'w') as f:
                f.write('\n'.join(clist) + '\n')

            # generate pathnames file
            pwd = os.path.abspath(c.outputdir)
            with open(pwd + '/pathnames', 'w') as f:
                f.write(pwd + '/Options/\n')
                f.write(pwd + '/\n')
                f.write(pwd + '/\n')
                f.write(pwd + '/AVAILABLE\n')
                f.write(' = == = == = == = == = == ==  = \n')

            # create Options dir if necessary
            if not os.path.exists(pwd + '/Options'):
                os.makedirs(pwd+'/Options')

            # read template COMMAND file
            with open(os.path.expandvars(os.path.expanduser(
                c.flexpart_root_scripts)) + '/../Options/COMMAND', 'r') as f:
                lflist = f.read().split('\n')

            # find index of list where to put in the
            # date and time information
            # usually after the LDIRECT parameter
            i = 0
            for l in lflist:
                if 'LDIRECT' in l.upper():
                    break
                i += 1

            # insert the date and time information of run start and end
            # into the list of lines of COMMAND file
            lflist = lflist[:i+1] + \
                     [clist[0][:16], clist[-1][:16]] + \
                     lflist[i+3:]

            # write the new COMMAND file
            with open(pwd + '/Options/COMMAND', 'w') as g:
                g.write('\n'.join(lflist) + '\n')

            # change to outputdir and start the grib2flexpart run
            # afterwards switch back to the working dir
            os.chdir(c.outputdir)
            p = subprocess.check_call([
                os.path.expandvars(os.path.expanduser(c.flexpart_root_scripts))
                + '/../FLEXPART_PROGRAM/grib2flexpart', 'useAvailable', '.'])
            os.chdir(pwd)

        return

    def create(self, inputfiles, c):
        '''
        @Description:
            This method is based on the ECMWF example index.py
            https://software.ecmwf.int/wiki/display/GRIB/index.py

            An index file will be created which depends on the combination
            of "date", "time" and "stepRange" values. This is used to iterate
            over all messages in each grib file which were passed through the
            parameter "inputfiles" to seperate specific parameters into fort.*
            files. Afterwards the FORTRAN program is called to convert
            the data fields all to the same grid and put them in one file
            per unique time step (combination of "date", "time" and
            "stepRange").

        @Input:
            self: instance of EcFlexpart
                The current object of the class.

            inputfiles: instance of UioFiles
                Contains a list of files.

            c: instance of class ControlFile
                Contains all the parameters of CONTROL files, which are e.g.:
                DAY1(start_date), DAY2(end_date), DTIME, MAXSTEP, TYPE, TIME,
                STEP, CLASS(marsclass), STREAM, NUMBER, EXPVER, GRID, LEFT,
                LOWER, UPPER, RIGHT, LEVEL, LEVELIST, RESOL, GAUSS, ACCURACY,
                OMEGA, OMEGADIFF, ETA, ETADIFF, DPDETA, SMOOTH, FORMAT,
                ADDPAR, WRF, CWC, PREFIX, ECSTORAGE, ECTRANS, ECFSDIR,
                MAILOPS, MAILFAIL, GRIB2FLEXPART, FLEXPARTDIR, BASETIME
                DATE_CHUNK, DEBUG, INPUTDIR, OUTPUTDIR, FLEXPART_ROOT_SCRIPTS

                For more information about format and content of the parameter
                see documentation.

        @Return:
            <nothing>
        '''

        table128 = init128(_config.PATH_GRIBTABLE)
        wrfpars = to_param_id('sp/mslp/skt/2t/10u/10v/2d/z/lsm/sst/ci/sd/\
                            stl1/stl2/stl3/stl4/swvl1/swvl2/swvl3/swvl4',
                            table128)

        index_keys = ["date", "time", "step"]
        indexfile = os.path.join(c.inputdir, _config.FILE_GRIB_INDEX)
        silent_remove(indexfile)
        grib = GribTools(inputfiles.files)
        # creates new index file
        iid = grib.index(index_keys=index_keys, index_file=indexfile)

        # read values of index keys
        index_vals = []
        for key in index_keys:
            index_vals.append(grib_index_get(iid, key))
            print(index_vals[-1])
            # index_vals looks for example like:
            # index_vals[0]: ('20171106', '20171107', '20171108') ; date
            # index_vals[1]: ('0', '1200', '1800', '600') ; time
            # index_vals[2]: ('0', '12', '3', '6', '9') ; stepRange

        fdict = {'10':None, '11':None, '12':None, '13':None, '16':None,
                 '17':None, '19':None, '21':None, '22':None, '20':None}

        for prod in product(*index_vals):
            # e.g. prod = ('20170505', '0', '12')
            #             (  date    ,time, step)
            # per date e.g. time = 0, 1200
            # per time e.g. step = 3, 6, 9, 12
            # flag for Fortran program and file merging
            convertFlag = False
            print('current prod: ', prod)
            # e.g. prod = ('20170505', '0', '12')
            #             (  date    ,time, step)
            # per date e.g. time = 0, 600, 1200, 1800
            # per time e.g. step = 0, 3, 6, 9, 12
            for i in range(len(index_keys)):
                grib_index_select(iid, index_keys[i], prod[i])

            # get first id from current product
            gid = grib_new_from_index(iid)

            # if there is data for this product combination
            # prepare some date and time parameter before reading the data
            if gid is not None:
                # Combine all temporary data files into final grib file if
                # gid is at least one time not None. Therefore set convertFlag
                # to save information. The Fortran program is also
                # only executed if convertFlag is True
                convertFlag = True
                # remove old fort.* files and open new ones
                # they are just valid for a single product
                for k, f in fdict.iteritems():
                    fortfile = os.path.join(c.inputdir, 'fort.' + k)
                    silent_remove(fortfile)
                    fdict[k] = open(fortfile, 'w')

                cdate = str(grib_get(gid, 'date'))
                time = grib_get(gid, 'time')
                step = grib_get(gid, 'step')
                # create correct timestamp from the three time informations
                # date, time, step
                timestamp = datetime.strptime(cdate + '{:0>2}'.format(time/100),
                                              '%Y%m%d%H')
                timestamp += timedelta(hours=int(step))
                cdateH = datetime.strftime(timestamp, '%Y%m%d%H')

                if c.basetime:
                    slimit = datetime.strptime(c.start_date + '00', '%Y%m%d%H')
                    bt = '23'
                    if c.basetime == '00':
                        bt = '00'
                        slimit = datetime.strptime(c.end_date + bt, '%Y%m%d%H')\
                            - timedelta(hours=12-int(c.dtime))
                    if c.basetime == '12':
                        bt = '12'
                        slimit = datetime.strptime(c.end_date + bt, '%Y%m%d%H')\
                            - timedelta(hours=12-int(c.dtime))

                    elimit = datetime.strptime(c.end_date + bt, '%Y%m%d%H')

                    if timestamp < slimit or timestamp > elimit:
                        continue
            else:
                pass

            try:
                if c.wrf:
                    if 'olddate' not in locals() or cdate != olddate:
                        fwrf = open(os.path.join(c.outputdir,
                                    'WRF' + cdate + '.{:0>2}'.format(time) +
                                    '.000.grb2'), 'w')
                        olddate = cdate[:]
            except AttributeError:
                pass

            # helper variable to remember which fields were already used.
            savedfields = []
            while 1:
                if gid is None:
                    break
                paramId = grib_get(gid, 'paramId')
                gridtype = grib_get(gid, 'gridType')
                levtype = grib_get(gid, 'typeOfLevel')
                if paramId == 133 and gridtype == 'reduced_gg':
                # Specific humidity (Q.grb) is used as a template only
                # so we need the first we "meet"
                    with open(os.path.join(c.inputdir, 'fort.18'), 'w') as fout:
                        grib_write(gid, fout)
                elif paramId == 131 or paramId == 132:
                    grib_write(gid, fdict['10'])
                elif paramId == 130:
                    grib_write(gid, fdict['11'])
                elif paramId == 133 and gridtype != 'reduced_gg':
                    grib_write(gid, fdict['17'])
                elif paramId == 152:
                    grib_write(gid, fdict['12'])
                elif paramId == 155 and gridtype == 'sh':
                    grib_write(gid, fdict['13'])
                elif  paramId in [129, 138, 155] and levtype == 'hybrid' \
                        and c.wrf:
                    pass
                elif paramId == 246 or paramId == 247:
                    # cloud liquid water and ice
                    if paramId == 246:
                        clwc = grib_get_values(gid)
                    else:
                        clwc += grib_get_values(gid)
                        grib_set_values(gid, clwc)
                        grib_set(gid, 'paramId', 201031)
                        grib_write(gid, fdict['22'])
                elif paramId == 135:
                    grib_write(gid, fdict['19'])
                elif paramId == 77:
                    grib_write(gid, fdict['21'])
                else:
                    if paramId not in savedfields:
                        grib_write(gid, fdict['16'])
                        savedfields.append(paramId)
                    else:
                        print('duplicate ' + str(paramId) + ' not written')

                try:
                    if c.wrf:
                        # model layer
                        if levtype == 'hybrid' and \
                           paramId in [129, 130, 131, 132, 133, 138, 155]:
                            grib_write(gid, fwrf)
                        # sfc layer
                        elif paramId in wrfpars:
                            grib_write(gid, fwrf)
                except AttributeError:
                    pass

                grib_release(gid)
                gid = grib_new_from_index(iid)

            for f in fdict.values():
                f.close()

            # call for Fortran program if flag is True
            if convertFlag:
                pwd = os.getcwd()
                os.chdir(c.inputdir)
                if os.stat('fort.21').st_size == 0 and c.eta:
                    print('Parameter 77 (etadot) is missing, most likely it is \
                           not available for this type or date/time\n')
                    print('Check parameters CLASS, TYPE, STREAM, START_DATE\n')
                    my_error(c.mailfail, 'fort.21 is empty while parameter eta \
                             is set to 1 in CONTROL file')

                # create the corresponding output file fort.15
                # (generated by Fortran program) + fort.16 (paramId 167 and 168)
                p = subprocess.check_call([os.path.join(
                    c.exedir, _config.FORTRAN_EXECUTABLE)], shell=True)
                os.chdir(pwd)

                # create final output filename, e.g. EN13040500 (ENYYMMDDHH)
                fnout = os.path.join(c.inputdir, c.prefix)
                if c.maxstep > 12:
                    suffix = cdate[2:8] + '.{:0>2}'.format(time/100) + \
                             '.{:0>3}'.format(step)
                else:
                    suffix = cdateH[2:10]
                fnout += suffix
                print("outputfile = " + fnout)
                self.outputfilelist.append(fnout) # needed for final processing

                # create outputfile and copy all data from intermediate files
                # to the outputfile (final GRIB files)
                orolsm = os.path.basename(glob.glob(
                    c.inputdir + '/OG_OROLSM__SL.*.' + c.ppid + '*')[0])
                fluxfile = 'flux' + cdate[0:2] + suffix
                if not c.cwc:
                    flist = ['fort.15', fluxfile, 'fort.16', orolsm]
                else:
                    flist = ['fort.15', 'fort.22', fluxfile, 'fort.16', orolsm]

                with open(fnout, 'wb') as fout:
                    for f in flist:
                        shutil.copyfileobj(open(os.path.join(c.inputdir, f),
                                                'rb'), fout)

                if c.omega:
                    with open(os.path.join(c.outputdir, 'OMEGA'), 'wb') as fout:
                        shutil.copyfileobj(
                            open(os.path.join(c.inputdir, 'fort.25'),
                                 'rb'), fout)
            else:
                pass

        if c.wrf:
            fwrf.close()

        grib_index_release(iid)

        return

    def deacc_fluxes(self, inputfiles, c):
        '''
        @Description:
            Goes through all flux fields in ordered time and de-accumulate
            the fields. Afterwards the fields are disaggregated in time.
            Different versions of disaggregation is provided for rainfall
            data (darain, modified linear) and the surface fluxes and
            stress data (dapoly, cubic polynomial).

        @Input:
            self: instance of EcFlexpart
                The current object of the class.

            inputfiles: instance of UioFiles
                Contains a list of files.

            c: instance of class ControlFile
                Contains all the parameters of CONTROL file, which are e.g.:
                DAY1(start_date), DAY2(end_date), DTIME, MAXSTEP, TYPE, TIME,
                STEP, CLASS(marsclass), STREAM, NUMBER, EXPVER, GRID, LEFT,
                LOWER, UPPER, RIGHT, LEVEL, LEVELIST, RESOL, GAUSS, ACCURACY,
                OMEGA, OMEGADIFF, ETA, ETADIFF, DPDETA, SMOOTH, FORMAT,
                ADDPAR, WRF, CWC, PREFIX, ECSTORAGE, ECTRANS, ECFSDIR,
                MAILOPS, MAILFAIL, GRIB2FLEXPART, FLEXPARTDIR, BASETIME
                DATE_CHUNK, DEBUG, INPUTDIR, OUTPUTDIR, FLEXPART_ROOT_SCRIPTS

                For more information about format and content of the parameter
                see documentation.

        @Return:
            <nothing>
        '''

        table128 = init128(_config.PATH_GRIBTABLE)
        pars = to_param_id(self.params['OG_acc_SL'][0], table128)
        index_keys = ["date", "time", "step"]
        indexfile = os.path.join(c.inputdir, _config.FILE_GRIB_INDEX)
        silent_remove(indexfile)
        grib = GribTools(inputfiles.files)
        # creates new index file
        iid = grib.index(index_keys=index_keys, index_file=indexfile)

        # read values of index keys
        index_vals = []
        for key in index_keys:
            key_vals = grib_index_get(iid, key)
            print(key_vals)
            # have to sort the steps for disaggregation,
            # therefore convert to int first
            if key == 'step':
                key_vals = [int(k) for k in key_vals]
                key_vals.sort()
                key_vals = [str(k) for k in key_vals]
            index_vals.append(key_vals)
            # index_vals looks for example like:
            # index_vals[0]: ('20171106', '20171107', '20171108') ; date
            # index_vals[1]: ('0', '1200') ; time
            # index_vals[2]: (3', '6', '9', '12') ; stepRange

        valsdict = {}
        svalsdict = {}
        stepsdict = {}
        for p in pars:
            valsdict[str(p)] = []
            svalsdict[str(p)] = []
            stepsdict[str(p)] = []

        print('maxstep: ', c.maxstep)

        for prod in product(*index_vals):
            # e.g. prod = ('20170505', '0', '12')
            #             (  date    ,time, step)
            # per date e.g. time = 0, 1200
            # per time e.g. step = 3, 6, 9, 12
            print('current prod: ', prod)
            for i in range(len(index_keys)):
                grib_index_select(iid, index_keys[i], prod[i])

            # get first id from current product
            gid = grib_new_from_index(iid)

            # if there is data for this product combination
            # prepare some date and time parameter before reading the data
            if gid is not None:
                cdate = grib_get(gid, 'date')
                time = grib_get(gid, 'time')
                step = grib_get(gid, 'step')
                # date+time+step-2*dtime
                # (since interpolated value valid for step-2*dtime)
                sdate = datetime(year=cdate/10000,
                                 month=(cdate % 10000)/100,
                                 day=(cdate % 100),
                                 hour=time/100)
                fdate = sdate + timedelta(hours=step-2*int(c.dtime))
                sdates = sdate + timedelta(hours=step)
                elimit = None
            else:
                break

            if c.maxstep > 12:
                fnout = os.path.join(c.inputdir, 'flux' +
                                     sdate.strftime('%Y%m%d') +
                                     '.{:0>2}'.format(time/100) +
                                     '.{:0>3}'.format(step-2*int(c.dtime)))
                gnout = os.path.join(c.inputdir, 'flux' +
                                     sdate.strftime('%Y%m%d') +
                                     '.{:0>2}'.format(time/100) +
                                     '.{:0>3}'.format(step-int(c.dtime)))
                hnout = os.path.join(c.inputdir, 'flux' +
                                     sdate.strftime('%Y%m%d') +
                                     '.{:0>2}'.format(time/100) +
                                     '.{:0>3}'.format(step))
            else:
                fnout = os.path.join(c.inputdir, 'flux' +
                                     fdate.strftime('%Y%m%d%H'))
                gnout = os.path.join(c.inputdir, 'flux' +
                                     (fdate + timedelta(hours=int(c.dtime))).
                                     strftime('%Y%m%d%H'))
                hnout = os.path.join(c.inputdir, 'flux' +
                                     sdates.strftime('%Y%m%d%H'))

            print("outputfile = " + fnout)
            f_handle = open(fnout, 'w')
            g_handle = open(gnout, 'w')
            h_handle = open(hnout, 'w')

            # read message for message and store relevant data fields
            # data keywords are stored in pars
            while 1:
                if gid is None:
                    break
                cparamId = str(grib_get(gid, 'paramId'))
                step = grib_get(gid, 'step')
                atime = grib_get(gid, 'time')
                ni = grib_get(gid, 'Ni')
                nj = grib_get(gid, 'Nj')
                if cparamId in valsdict.keys():
                    values = grib_get_values(gid)
                    vdp = valsdict[cparamId]
                    svdp = svalsdict[cparamId]
                    sd = stepsdict[cparamId]

                    if cparamId == '142' or cparamId == '143':
                        fak = 1. / 1000.
                    else:
                        fak = 3600.

                    values = (np.reshape(values, (nj, ni))).flatten() / fak
                    vdp.append(values[:])  # save the accumulated values
                    if step <= int(c.dtime):
                        svdp.append(values[:] / int(c.dtime))
                    else:  # deaccumulate values
                        svdp.append((vdp[-1] - vdp[-2]) / int(c.dtime))

                    print(cparamId, atime, step, len(values),
                          values[0], np.std(values))
                    # save the 1/3-hourly or specific values
                    # svdp.append(values[:])
                    sd.append(step)
                    # len(svdp) correspond to the time
                    if len(svdp) >= 3:
                        if len(svdp) > 3:
                            if cparamId == '142' or cparamId == '143':
                                values = disaggregation.darain(svdp)
                            else:
                                values = disaggregation.dapoly(svdp)

                            if not (step == c.maxstep and c.maxstep > 12 \
                                    or sdates == elimit):
                                vdp.pop(0)
                                svdp.pop(0)
                        else:
                            if c.maxstep > 12:
                                values = svdp[1]
                            else:
                                values = svdp[0]

                        grib_set_values(gid, values)
                        if c.maxstep > 12:
                            grib_set(gid, 'step', max(0, step-2*int(c.dtime)))
                        else:
                            grib_set(gid, 'step', 0)
                            grib_set(gid, 'time', fdate.hour*100)
                            grib_set(gid, 'date', fdate.year*10000 +
                                     fdate.month*100+fdate.day)
                        grib_write(gid, f_handle)

                        if c.basetime:
                            elimit = datetime.strptime(c.end_date +
                                                       c.basetime, '%Y%m%d%H')
                        else:
                            elimit = sdate + timedelta(2*int(c.dtime))

                        # squeeze out information of last two steps contained
                        # in svdp
                        # if step+int(c.dtime) == c.maxstep and c.maxstep>12
                        # or sdates+timedelta(hours = int(c.dtime))
                        # >= elimit:
                        # Note that svdp[0] has not been popped in this case

                        if step == c.maxstep and c.maxstep > 12 or \
                           sdates == elimit:

                            values = svdp[3]
                            grib_set_values(gid, values)
                            grib_set(gid, 'step', 0)
                            truedatetime = fdate + timedelta(hours=
                                                             2*int(c.dtime))
                            grib_set(gid, 'time', truedatetime.hour * 100)
                            grib_set(gid, 'date', truedatetime.year * 10000 +
                                     truedatetime.month * 100 +
                                     truedatetime.day)
                            grib_write(gid, h_handle)

                            #values = (svdp[1]+svdp[2])/2.
                            if cparamId == '142' or cparamId == '143':
                                values = disaggregation.darain(list(reversed(svdp)))
                            else:
                                values = disaggregation.dapoly(list(reversed(svdp)))

                            grib_set(gid, 'step', 0)
                            truedatetime = fdate + timedelta(hours=int(c.dtime))
                            grib_set(gid, 'time', truedatetime.hour * 100)
                            grib_set(gid, 'date', truedatetime.year * 10000 +
                                     truedatetime.month * 100 +
                                     truedatetime.day)
                            grib_set_values(gid, values)
                            grib_write(gid, g_handle)

                    grib_release(gid)

                    gid = grib_new_from_index(iid)

            f_handle.close()
            g_handle.close()
            h_handle.close()

        grib_index_release(iid)

        return



