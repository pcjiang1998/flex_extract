#!/usr/bin/env python
# -*- coding: utf-8 -*-
#************************************************************************
# TODO AP
#AP
# - Functionality Description Provided is not correct for this file
# - localpythonpath should not be set in module load section!
# - Change History ist nicht angepasst ans File! Original geben lassen
# - def myerror muss angepasst werden da derzeit manuelle modifikation notwendig
# - the gaussian keyword in mars retrieval should be removed!!! but kept in
#   control file for the reason of calculation of eta dot from gaussian grid
# - call of convert in eigene Funktion auslagern

#************************************************************************
"""
@Author: Anne Fouilloux (University of Oslo)

@Date: October 2014

@ChangeHistory:
    November 2015 - Leopold Haimberger (University of Vienna):
        - using the WebAPI also for general MARS retrievals
        - job submission on ecgate and cca
        - job templates suitable for twice daily operational dissemination
        - dividing retrievals of longer periods into digestable chunks
        - retrieve also longer term forecasts, not only analyses and
          short term forecast data
        - conversion into GRIB2
        - conversion into .fp format for faster execution of FLEXPART

    February 2018 - Anne Philipp (University of Vienna):
        - applied PEP8 style guide
        - added documentation

@License:
    (C) Copyright 2014 UIO.

    This software is licensed under the terms of the Apache Licence Version 2.0
    which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.

@Requirements:
    - A standard python 2.6 or 2.7 installation
    - dateutils
    - matplotlib (optional, for debugging)
    - ECMWF specific packages, all available from https://software.ecmwf.int/
        ECMWF WebMARS, gribAPI with python enabled, emoslib and
        ecaccess web toolkit

@Description:
    Further documentation may be obtained from www.flexpart.eu.

    Functionality provided:
        Prepare input 3D-wind fields in hybrid coordinates +
        surface fields for FLEXPART runs
"""
# ------------------------------------------------------------------------------
# MODULES
# ------------------------------------------------------------------------------
import subprocess
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
import traceback
import shutil
import os
import errno
import sys
import inspect
import glob
import datetime
from string import atoi
from numpy import *
ecapi = True
try:
    import ecmwfapi
except ImportError:
    ecapi = False
from gribapi import *
from GribTools import GribTools

def interpret_args_and_control():
    '''
    @Description:
        Assigns the command line arguments and reads control file
        content. Apply default values for non mentioned arguments.

    @Input:
        <nothing>

    @Return:
        args: instance of ArgumentParser
            Contains the commandline arguments from script/program call.

        c: instance of class Control
            Contains all necessary information of a control file. The parameters
            are: DAY1, DAY2, DTIME, MAXSTEP, TYPE, TIME, STEP, CLASS, STREAM,
            NUMBER, EXPVER, GRID, LEFT, LOWER, UPPER, RIGHT, LEVEL, LEVELIST,
            RESOL, GAUSS, ACCURACY, OMEGA, OMEGADIFF, ETA, ETADIFF, DPDETA,
            SMOOTH, FORMAT, ADDPAR, WRF, CWC, PREFIX, ECSTORAGE, ECTRANS,
            ECFSDIR, MAILOPS, MAILFAIL, GRIB2FLEXPART, DEBUG, INPUTDIR,
            OUTPUTDIR, FLEXPART_ROOT_SCRIPTS
            For more information about format and content of the parameter see
            documentation.

    '''
    parser = ArgumentParser(description='Retrieve FLEXPART input from \
                            ECMWF MARS archive',
                            formatter_class=ArgumentDefaultsHelpFormatter)

    # the most important arguments
    parser.add_argument("--start_date", dest="start_date",
                        help="start date YYYYMMDD")
    parser.add_argument("--end_date", dest="end_date",
                        help="end_date YYYYMMDD")
    parser.add_argument("--date_chunk", dest="date_chunk", default=None,
                        help="# of days to be retrieved at once")

    # some arguments that override the default in the control file
    parser.add_argument("--basetime", dest="basetime",
                        help="base such as 00/12 (for half day retrievals)")
    parser.add_argument("--step", dest="step",
                        help="steps such as 00/to/48")
    parser.add_argument("--levelist", dest="levelist",
                        help="Vertical levels to be retrieved, e.g. 30/to/60")
    parser.add_argument("--area", dest="area",
                        help="area defined as north/west/south/east")

    # set the working directories
    parser.add_argument("--inputdir", dest="inputdir", default=None,
                        help="root directory for storing intermediate files")
    parser.add_argument("--outputdir", dest="outputdir", default=None,
                        help="root directory for storing output files")
    parser.add_argument("--flexpart_root_scripts", dest="flexpart_root_scripts",
                        help="FLEXPART root directory (to find grib2flexpart \
                        and COMMAND file)\n\ Normally ECMWFDATA resides in \
                        the scripts directory of the FLEXPART distribution")

    # this is only used by prepareFLEXPART.py to rerun a postprocessing step
    parser.add_argument("--ppid", dest="ppid",
                        help="Specify parent process id for \
                        rerun of prepareFLEXPART")

    # arguments for job submission to ECMWF, only needed by submit.py
    parser.add_argument("--job_template", dest='job_template',
                        default="job.temp",
                        help="job template file for submission to ECMWF")
    parser.add_argument("--queue", dest="queue",
                        help="queue for submission to ECMWF \
                        (e.g. ecgate or cca )")
    parser.add_argument("--controlfile", dest="controlfile",
                        default='CONTROL.temp',
                        help="file with control parameters")
    parser.add_argument("--debug", dest="debug", default=0,
                        help="Debug mode - leave temporary files intact")

    args = parser.parse_args()

    # create instance of Control for specified controlfile
    # and assign the parameters (and default values if necessary)
    try:
        c = Control(args.controlfile)
    except IOError:
        try:
            c = Control(localpythonpath + args.controlfile)
        except:
            print('Could not read control file "' + args.controlfile + '"')
            print('Either it does not exist or its syntax is wrong.')
            print('Try "' + sys.argv[0].split('/')[-1] +
                  ' -h" to print usage information')
            exit(1)

    # check for having at least a starting date
    if  args.start_date is None and getattr(c, 'start_date') is None:
        print('start_date specified neither in command line nor \
               in control file ' + args.controlfile)
        print('Try "' + sys.argv[0].split('/')[-1] +
              ' -h" to print usage information')
        exit(1)

    # save all existing command line parameter to the Control instance
    # if parameter is not specified through the command line or CONTROL file
    # set default values
    if args.start_date is not None:
        c.start_date = args.start_date
    if args.end_date is not None:
        c.end_date = args.end_date
    if c.end_date is None:
        c.end_date = c.start_date
    if args.date_chunk is not None:
        c.date_chunk = args.date_chunk

    if not hasattr(c, 'debug'):
        c.debug = args.debug

    if args.inputdir is None and args.outputdir is None:
        c.inputdir = '../work'
        c.outputdir = '../work'
    else:
        if args.inputdir is not None:
            c.inputdir = args.inputdir
        if args.outputdir is None:
            c.outputdir = args.inputdir
        if args.outputdir is not None:
            c.outputdir = args.outputdir
        if args.inputdir is None:
            c.inputdir = args.outputdir

    if hasattr(c, 'outputdir') is False and args.outputdir is None:
        c.outputdir = c.inputdir
    else:
        if args.outputdir is not None:
            c.outputdir = args.outputdir

    if args.area is not None:
        afloat = '.' in args.area
        l = args.area.split('/')
        if afloat:
            for i in range(len(l)):
                l[i] = str(int(float(l[i]) * 1000))
        c.upper, c.left, c.lower, c.right = l

    # NOTE: basetime activates the ''operational mode''
    if args.basetime is not None:
        c.basetime = args.basetime

    if args.step is not None:
        l = args.step.split('/')
        if 'to' in args.step.lower():
            if 'by' in args.step.lower():
                ilist = arange(int(l[0]), int(l[2]) + 1, int(l[4]))
                c.step = ['{:0>3}'.format(i) for i in ilist]
            else:
                myerror(None, args.step + ':\n' +
                        'please use "by" as well if "to" is used')
        else:
            c.step = l

    if args.levelist is not None:
        c.levelist = args.levelist
        if 'to' in c.levelist:
            c.level = c.levelist.split('/')[2]
        else:
            c.level = c.levelist.split('/')[-1]

    if args.flexpart_root_scripts is not None:
        c.flexpart_root_scripts = args.flexpart_root_scripts

    return args, c


def install_args_and_control():
    '''
    @Description:
        Assigns the command line arguments for installation and reads
        control file content. Apply default values for non mentioned arguments.

    @Input:
        <nothing>

    @Return:
        args: instance of ArgumentParser
            Contains the commandline arguments from script/program call.

        c: instance of class Control
            Contains all necessary information of a control file. The parameters
            are: DAY1, DAY2, DTIME, MAXSTEP, TYPE, TIME, STEP, CLASS, STREAM,
            NUMBER, EXPVER, GRID, LEFT, LOWER, UPPER, RIGHT, LEVEL, LEVELIST,
            RESOL, GAUSS, ACCURACY, OMEGA, OMEGADIFF, ETA, ETADIFF, DPDETA,
            SMOOTH, FORMAT, ADDPAR, WRF, CWC, PREFIX, ECSTORAGE, ECTRANS,
            ECFSDIR, MAILOPS, MAILFAIL, GRIB2FLEXPART, FLEXPARTDIR
            For more information about format and content of the parameter see
            documentation.
    '''
    parser = ArgumentParser(description='Install ECMWFDATA software locally or \
                            on ECMWF machines',
                            formatter_class=ArgumentDefaultsHelpFormatter)

    parser.add_argument('--target', dest='install_target',
                        help="Valid targets: local | ecgate | cca , \
                        the latter two are at ECMWF")
    parser.add_argument("--makefile", dest="makefile",
                        help='Name of Makefile to use for compiling CONVERT2')
    parser.add_argument("--ecuid", dest="ecuid",
                        help='user id at ECMWF')
    parser.add_argument("--ecgid", dest="ecgid",
                        help='group id at ECMWF')
    parser.add_argument("--gateway", dest="gateway",
                        help='name of local gateway server')
    parser.add_argument("--destination", dest="destination",
                        help='ecaccess destination, e.g. leo@genericSftp')

    parser.add_argument("--flexpart_root_scripts", dest="flexpart_root_scripts",
                        help="FLEXPART root directory on ECMWF servers \
                        (to find grib2flexpart and COMMAND file)\n\
                        Normally ECMWFDATA resides in the scripts directory \
                        of the FLEXPART distribution, thus the:")

# arguments for job submission to ECMWF, only needed by submit.py
    parser.add_argument("--job_template", dest='job_template',
                        default="job.temp.o",
                        help="job template file for submission to ECMWF")

    parser.add_argument("--controlfile", dest="controlfile",
                        default='CONTROL.temp',
                        help="file with control parameters")

    args = parser.parse_args()

    try:
        c = Control(args.controlfile)
    except:
        print('Could not read control file "' + args.controlfile + '"')
        print('Either it does not exist or its syntax is wrong.')
        print('Try "' + sys.argv[0].split('/')[-1] +
              ' -h" to print usage information')
        exit(1)

    if args.install_target != 'local':
        if (args.ecgid is None or args.ecuid is None or args.gateway is None
            or args.destination is None):
            print('Please enter your ECMWF user id and group id as well as \
                   the \nname of the local gateway and the ectrans \
                   destination ')
            print('with command line options --ecuid --ecgid \
                   --gateway --destination')
            print('Try "' + sys.argv[0].split('/')[-1] +
                  ' -h" to print usage information')
            print('Please consult ecaccess documentation or ECMWF user support \
                   for further details')
            sys.exit(1)
        else:
            c.ecuid = args.ecuid
            c.ecgid = args.ecgid
            c.gateway = args.gateway
            c.destination = args.destination

    try:
        c.makefile = args.makefile
    except:
        pass

    if args.install_target == 'local':
        if args.flexpart_root_scripts is None:
            c.flexpart_root_scripts = '../'
        else:
            c.flexpart_root_scripts = args.flexpart_root_scripts

    if args.install_target != 'local':
        if args.flexpart_root_scripts is None:
            c.ec_flexpart_root_scripts = '${HOME}'
        else:
            c.ec_flexpart_root_scripts = args.flexpart_root_scripts

    return args, c


def cleanup(c):
    '''
    @Description:
        Remove all files from intermediate directory
        (inputdir from control file).

    @Input:
        c: instance of class Control
            Contains all the parameters of control files, which are e.g.:
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

    print("cleanup")

    cleanlist = glob.glob(c.inputdir + "/*")
    for cl in cleanlist:
        if c.prefix not in cl:
            silentremove(cl)
        if c.ecapi is False and (c.ectrans == '1' or c.ecstorage == '1'):
            silentremove(cl)

    print("Done")

    return


def myerror(c, message='ERROR'):
    '''
    @Description:
        Prints a specified error message which can be passed to the function
        before exiting the program.

    @Input:
        c: instance of class Control
            Contains all the parameters of control files, which are e.g.:
            DAY1(start_date), DAY2(end_date), DTIME, MAXSTEP, TYPE, TIME,
            STEP, CLASS(marsclass), STREAM, NUMBER, EXPVER, GRID, LEFT,
            LOWER, UPPER, RIGHT, LEVEL, LEVELIST, RESOL, GAUSS, ACCURACY,
            OMEGA, OMEGADIFF, ETA, ETADIFF, DPDETA, SMOOTH, FORMAT,
            ADDPAR, WRF, CWC, PREFIX, ECSTORAGE, ECTRANS, ECFSDIR,
            MAILOPS, MAILFAIL, GRIB2FLEXPART, FLEXPARTDIR, BASETIME
            DATE_CHUNK, DEBUG, INPUTDIR, OUTPUTDIR, FLEXPART_ROOT_SCRIPTS

            For more information about format and content of the parameter
            see documentation.

        message: string, optional
            Error message. Default value is "ERROR".

    @Return:
        <nothing>
    '''
    # uncomment if user wants email notification directly from python
    #try:
        #target = c.mailfail
    #except AttributeError:
        #target = os.getenv('USER')

    #if(type(target) is not list):
        #target = [target]

    print(message)

    # uncomment if user wants email notification directly from python
    #for t in target:
    #p = subprocess.Popen(['mail','-s ECMWFDATA v7.0 ERROR', os.path.expandvars(t)],
    #                     stdin = subprocess.PIPE, stdout = subprocess.PIPE,
    #                     stderr = subprocess.PIPE, bufsize = 1)
    #tr = '\n'.join(traceback.format_stack())
    #pout = p.communicate(input = message+'\n\n'+tr)[0]
    #print 'Email sent to '+os.path.expandvars(t) # +' '+pout.decode()

    exit(1)

    return


def normalexit(c, message='Done!'):
    '''
    @Description:
        Prints a specific exit message which can be passed to the function.

    @Input:
        c: instance of class Control
            Contains all the parameters of control files, which are e.g.:
            DAY1(start_date), DAY2(end_date), DTIME, MAXSTEP, TYPE, TIME,
            STEP, CLASS(marsclass), STREAM, NUMBER, EXPVER, GRID, LEFT,
            LOWER, UPPER, RIGHT, LEVEL, LEVELIST, RESOL, GAUSS, ACCURACY,
            OMEGA, OMEGADIFF, ETA, ETADIFF, DPDETA, SMOOTH, FORMAT,
            ADDPAR, WRF, CWC, PREFIX, ECSTORAGE, ECTRANS, ECFSDIR,
            MAILOPS, MAILFAIL, GRIB2FLEXPART, FLEXPARTDIR, BASETIME
            DATE_CHUNK, DEBUG, INPUTDIR, OUTPUTDIR, FLEXPART_ROOT_SCRIPTS

            For more information about format and content of the parameter
            see documentation.

        message: string, optional
            Message for exiting program. Default value is "Done!".

    @Return:
        <nothing>

    '''
    # Uncomment if user wants notification directly from python
    #try:
        #target = c.mailops
        #if(type(target) is not list):
            #target = [target]
        #for t in target:
            #p = subprocess.Popen(['mail','-s ECMWFDATA v7.0 normal exit',
            #                      os.path.expandvars(t)],
            #                      stdin = subprocess.PIPE,
            #                      stdout = subprocess.PIPE,
            #                      stderr = subprocess.PIPE, bufsize = 1)
            #pout = p.communicate(input = message+'\n\n')[0]
            #print pout.decode()
    #except:
        #pass

    print(message)

    return


def product(*args, **kwds):
    '''
    @Description:
        This method is taken from an example at the ECMWF wiki website.
        https://software.ecmwf.int/wiki/display/GRIB/index.py; 2018-03-16

        This method combines the single characters of the passed arguments
        with each other. So that each character of each argument value
        will be combined with each character of the other arguments as a tuple.

        Example:
        product('ABCD', 'xy') --> Ax Ay Bx By Cx Cy Dx Dy
        product(range(2), repeat = 3) --> 000 001 010 011 100 101 110 111

    @Input:
        *args: tuple
            Positional arguments (arbitrary number).

        **kwds: dictionary
            Contains all the keyword arguments from *args.

    @Return:
        prod: tuple
            Return will be done with "yield". A tuple of combined arguments.
            See example in description above.
    '''

    pools = map(tuple, args) * kwds.get('repeat', 1)
    result = [[]]
    for pool in pools:
        result = [x + [y] for x in result for y in pool]
    for prod in result:
        yield tuple(prod)

    return


def silentremove(filename):
    '''
    @Description:
        Removes the file which name is passed to the function if
        it exists. The function does not fail if the file does not
        exist.

    @Input:
        filename: string
            The name of the file to be removed without notification.

    @Return:
        <nothing>
    '''
    try:
        os.remove(filename)
    except OSError as e:
        # this would be "except OSError, e:" before Python 2.6
        if e.errno is not  errno.ENOENT:
            # errno.ENOENT  =  no such file or directory
            raise  # re-raise exception if a different error occured

    return


def init128(fn):
    '''
    @Description:
        Opens and reads the grib file with table 128 information.

    @Input:
        fn: string
            Path to file of ECMWF grib table number 128.

    @Return:
        table128: dictionary
            Contains the ECMWF grib table 128 information.
    '''
    table128 = dict()
    with open(fn) as f:
        fdata = f.read().split('\n')
    for data in fdata:
        if data[0] != '!':
            table128[data[0:3]] = data[59:64].strip()

    return table128


def toparamId(pars, table):
    '''
    @Description:
        Transform parameter names to parameter ids
        with ECMWF grib table 128.

    @Input:
        pars: string
            Addpar argument from control file in the format of
            parameter names instead of ids.

        table: dictionary
            Contains the ECMWF grib table 128 information.

    @Return:
        ipar: list of integer
            List of addpar parameters from control file transformed to
            parameter ids in the format of integer.
    '''
    cpar = pars.upper().split('/')
    ipar = []
    for par in cpar:
        found = False
        for k, v in table.iteritems():
            if par == k or par == v:
                ipar.append(int(k))
                found = True
                break
        if found is False:
            print('Warning: par ' + par + ' not found in table 128')

    return ipar


def dapoly(alist):
    '''
    @Description:
        Interpolation of deaccumulated fluxes of an ECMWF model FG field
        using a cubic polynomial solution which conserves the integrals
        of the fluxes within each timespan.
        Disaggregation is done for a list of 4 values to generate a new
        interpolated value which is output at the central point of the 4
        accumulation timespans.

    @Input:
        alist: list of size 4, float
            List of 4 flux values.

    @Return:
        nvalue: float
            New value for the second position of the disaggregated
            fluxes field.

    '''
    pya = (alist[3] - alist[0] + 3. * (alist[1] - alist[2])) / 6.
    pyb = (alist[2] + alist[0]) / 2. - alist[1] - 9. * pya / 2.
    pyc = alist[1] - alist[0] - 7. * pya / 2. - 2. * pyb
    pyd = alist[0] - pya / 4. - pyb / 3. - pyc / 2.
    nvalue = 8. * pya + 4. * pyb + 2. * pyc + pyd

    return nvalue


def darain(alist):
    '''
    @Description:
        Interpolation of deaccumulated precipitation fiels of the ECMWF fields
        using a modified linear solution.
        Disaggregate a list of 4 precipitation values to generate a new value
        for the second position of the 4 value list. The interpolated values
        are output at the central point of the 4 accumulation timespans
        This is used for precipitation fields.

    @Input:
        alist: list of size 4, float
            List of 4 precipitation values.

    @Return:
        nvalue: float
            New value for the second position of the disaggregated
            precipitation field.
    '''
    xa = alist[0]
    xb = alist[1]
    xc = alist[2]
    xd = alist[3]
    xa[xa < 0.] = 0.
    xb[xb < 0.] = 0.
    xc[xc < 0.] = 0.
    xd[xd < 0.] = 0.

    xac = 0.5 * xb
    mask = xa + xc > 0.
    xac[mask] = xb[mask] * xc[mask] / (xa[mask] + xc[mask])
    xbd = 0.5 * xc
    mask = xb + xd > 0.
    xbd[mask] = xb[mask] * xc[mask] / (xb[mask] + xd[mask])
    nvalue = xac + xbd

    return nvalue


class Control:
    '''
    Class containing the information of the ECMWFDATA control file.

    Contains all the parameters of control files, which are e.g.:
    DAY1(start_date), DAY2(end_date), DTIME, MAXSTEP, TYPE, TIME,
    STEP, CLASS(marsclass), STREAM, NUMBER, EXPVER, GRID, LEFT,
    LOWER, UPPER, RIGHT, LEVEL, LEVELIST, RESOL, GAUSS, ACCURACY,
    OMEGA, OMEGADIFF, ETA, ETADIFF, DPDETA, SMOOTH, FORMAT,
    ADDPAR, WRF, CWC, PREFIX, ECSTORAGE, ECTRANS, ECFSDIR,
    MAILOPS, MAILFAIL, GRIB2FLEXPART, FLEXPARTDIR,
    BASETIME, DATE_CHUNK, DEBUG, INPUTDIR, OUTPUTDIR, FLEXPART_ROOT_SCRIPTS

    For more information about format and content of the parameter
    see documentation.

    '''

    def __init__(self, filename):
        '''
        @Description:
            Initialises the instance of Control class and defines and
            assign all controlfile variables. Set default values if
            parameter was not in CONTROL file.

        @Input:
            self: instance of Control class
                Description see class documentation.

            filename: string
                Name of control file.

        @Return:
            <nothing>
        '''

        # read whole CONTROL file
        with open(filename) as f:
            fdata = f.read().split('\n')

        # go through every line and store parameter
        # as class variable
        for ldata in fdata:
            data = ldata.split()
            if len(data) > 1:
                if 'm_' in data[0].lower():
                    data[0] = data[0][2:]
                if data[0].lower() == 'class':
                    data[0] = 'marsclass'
                if data[0].lower() == 'day1':
                    data[0] = 'start_date'
                if data[0].lower() == 'day2':
                    data[0] = 'end_date'
                if data[0].lower() == 'addpar':
                    if '/' in data[1]:
                        # remove leading '/' sign from addpar content
                        if data[1][0] == '/':
                            data[1] = data[1][1:]
                        dd = data[1].split('/')
                        data = [data[0]]
                        for d in dd:
                            data.append(d)
                    pass
                if len(data) == 2:
                    if '$' in data[1]:
                        setattr(self, data[0].lower(), data[1])
                        while '$' in data[1]:
                            i = data[1].index('$')
                            j = data[1].find('{')
                            k = data[1].find('}')
                            var = os.getenv(data[1][j+1:k])
                            if var is not None:
                                data[1] = data[1][:i] + var + data[1][k+1:]
                            else:
                                myerror(None, 'Could not find variable ' +
                                        data[1][j+1:k] + ' while reading ' +
                                        filename)
                        setattr(self, data[0].lower()+'_expanded', data[1])
                    else:
                        if data[1].lower() != 'none':
                            setattr(self, data[0].lower(), data[1])
                        else:
                            setattr(self, data[0].lower(), None)
                elif len(data) > 2:
                    setattr(self, data[0].lower(), (data[1:]))
            else:
                pass

        # check a couple of necessary attributes if they contain values
        # otherwise set default values
        if not hasattr(self, 'start_date'):
            self.start_date = None
        if not hasattr(self, 'end_date'):
            self.end_date = self.start_date
        if not hasattr(self, 'accuracy'):
            self.accuracy = 24
        if not hasattr(self, 'omega'):
            self.omega = '0'
        if not hasattr(self, 'cwc'):
            self.cwc = '0'
        if not hasattr(self, 'omegadiff'):
            self.omegadiff = '0'
        if not hasattr(self, 'etadiff'):
            self.etadiff = '0'
        if not hasattr(self, 'levelist'):
            if not hasattr(self, 'level'):
                print(('Warning: neither levelist nor level \
                       specified in CONTROL file'))
            else:
                self.levelist = '1/to/' + self.level
        else:
            if 'to' in self.levelist:
                self.level = self.levelist.split('/')[2]
            else:
                self.level = self.levelist.split('/')[-1]

        if not hasattr(self, 'maxstep'):
            # find out maximum step
            self.maxstep = 0
            for s in self.step:
                if int(s) > self.maxstep:
                    self.maxstep = int(s)
        else:
            self.maxstep = int(self.maxstep)

        if not hasattr(self, 'prefix'):
            self.prefix = 'EN'
        if not hasattr(self, 'makefile'):
            self.makefile = None
        if not hasattr(self, 'basetime'):
            self.basetime = None
        if not hasattr(self, 'date_chunk'):
            self.date_chunk = '3'
        if not hasattr(self, 'grib2flexpart'):
            self.grib2flexpart = '0'

        # script directory
        self.ecmwfdatadir = os.path.dirname(os.path.abspath(
                                            inspect.getfile(
                                            inspect.currentframe()))) + '/../'
        # Fortran source directory
        self.exedir = self.ecmwfdatadir + 'src/'

        # FLEXPART directory
        if not hasattr(self, 'flexpart_root_scripts'):
            self.flexpart_root_scripts = self.ecmwfdatadir

        return


    def __str__(self):
        '''
        @Description:
            Prepares a single string with all the comma seperated Control
            class attributes including their values.

            Example:
            {'kids': 0, 'name': 'Dog', 'color': 'Spotted',
             'age': 10, 'legs': 2, 'smell': 'Alot'}

        @Input:
            self: instance of Control class
                Description see class documentation.

        @Return:
            string of Control class attributes with their values
        '''

        attrs = vars(self)

        return ', '.join("%s: %s" % item for item in attrs.items())

    def tolist(self):
        '''
        @Description:
            Just generates a list of strings containing the attributes and
            assigned values except the attributes "_expanded", "exedir",
            "ecmwfdatadir" and "flexpart_root_scripts".

        @Input:
            self: instance of Control class
                Description see class documentation.

        @Return:
            l: list
                A sorted list of the all Control class attributes with
                their values except the attributes "_expanded", "exedir",
                "ecmwfdatadir" and "flexpart_root_scripts".
        '''
        attrs = vars(self)
        l = list()
        for item in attrs.items():
            if '_expanded' in item[0]:
                pass
            elif 'exedir' in item[0]:
                pass
            elif 'flexpart_root_scripts' in item[0]:
                pass
            elif 'ecmwfdatadir' in item[0]:
                pass
            else:
                if type(item[1]) is list:
                    stot = ''
                    for s in item[1]:
                        stot += s + ' '

                    l.append("%s %s" % (item[0], stot))
                else:
#AP syntax error with doubled %s ???
                    l.append("%s %s" % item )
        return sorted(l)


class MARSretrieval:
    '''
    Class for submitting MARS retrievals.

    A description of MARS keywords/arguments and examples of their
    values can be found here:
    https://software.ecmwf.int/wiki/display/UDOC/\
                   Identification+keywords#Identificationkeywords-class

    '''

    def __init__(self, server, marsclass = "ei", type = "", levtype = "",
                 levelist = "", repres = "", date = "", resol = "", stream = "",
                 area = "", time = "", step = "", expver = "1", number = "",
                 accuracy = "", grid = "", gaussian = "", target = "",
                 param = ""):
        '''
        @Description:
            Initialises the instance of the MARSretrieval class and
            defines and assigns a set of the necessary retrieval parameters
            for the FLEXPART input data.
            A description of MARS keywords/arguments, their dependencies
            on each other and examples of their values can be found here:

            https://software.ecmwf.int/wiki/display/UDOC/MARS+keywords

        @Input:
            self: instance of MARSretrieval
                For description see class documentation.

            server: instance of ECMWFService (from ECMWF Web-API)
                This is the connection to the ECMWF data servers.
                It is needed for the pythonic access of ECMWF data.

            marsclass: string, optional
                Characterisation of dataset. E.g. EI (ERA-Interim),
                E4 (ERA40), OD (Operational archive), ea (ERA5).
                Default is the ERA-Interim dataset "ei".

            type: string, optional
                Determines the type of fields to be retrieved.
                Selects between observations, images or fields.
                Examples for fields: Analysis (an), Forecast (fc),
                Perturbed Forecast (pf), Control Forecast (cf) and so on.
                Default is an empty string.

            levtype: string, optional
                Denotes type of level. Has a direct implication on valid
                levelist values!
                E.g. model level (ml), pressure level (pl), surface (sfc),
                potential vorticity (pv), potential temperature (pt)
                and depth (dp).
                Default is an empty string.

            levelist: string, optional
                Specifies the required levels. It has to have a valid
                correspondence to the selected levtype.
                Examples: model level: 1/to/137, pressure levels: 500/to/1000
                Default is an empty string.

            repres: string, optional
                Selects the representation of the archived data.
                E.g. sh - spherical harmonics, gg - Gaussian grid,
                ll - latitude/longitude, ...
                Default is an empty string.

            date: string, optional
                Specifies the Analysis date, the Forecast base date or
                Observations date. Valid formats are:
                Absolute as YYYY-MM-DD or YYYYMMDD.
                Default is an empty string.

            resol: string, optional
                Specifies the desired triangular truncation of retrieved data,
                before carrying out any other selected post-processing.
                The default is automatic truncation (auto), by which the lowest
                resolution compatible with the value specified in grid is
                automatically selected for the retrieval.
                Users wanting to perform post-processing from full spectral
                resolution should specify Archived Value (av).
                The following are examples of existing resolutions found in
                the archive: 63, 106, 159, 213, 255, 319, 399, 511, 799 or 1279.
                This keyword has no meaning/effect if the archived data is
                not in spherical harmonics representation.
                The best selection can be found here:
                https://software.ecmwf.int/wiki/display/UDOC/\
                      Retrieve#Retrieve-Truncationbeforeinterpolation
                Default is an empty string.

            stream: string, optional
                Identifies the forecasting system used to generate the data.
                E.g. oper (Atmospheric model), enfo (Ensemble forecats), ...
                Default is an empty string.

            area: string, optional
                Specifies the desired sub-area of data to be extracted.
                Areas can be defined to wrap around the globe.

                Latitude values must be given as signed numbers, with:
                    north latitudes (i.e. north of the equator)
                        being positive (e.g: 40.5)
                    south latitutes (i.e. south of the equator)
                        being negative (e.g: -50.5)
                Longtitude values must be given as signed numbers, with:
                    east longitudes (i.e. east of the 0 degree meridian)
                        being positive (e.g: 35.0)
                    west longitudes (i.e. west of the 0 degree meridian)
                        being negative (e.g: -20.5)

                E.g.: North/West/South/East
                Default is an empty string.

            time: string, optional
                Specifies the time of the data in hours and minutes.
                Valid values depend on the type of data: Analysis time,
                Forecast base time or First guess verification time
                (all usually at synoptic hours: 00, 06, 12 and 18 ).
                Observation time (any combination in hours and minutes is valid,
                subject to data availability in the archive).
                The syntax is HHMM or HH:MM. If MM is omitted it defaults to 00.
                Default is an empty string.

            step: string, optional
                Specifies the forecast time step from forecast base time.
                Valid values are hours (HH) from forecast base time. It also
                specifies the length of the forecast which verifies at
                First Guess time.
                E.g. 1/3/6-hourly
                Default is an empty string.

            expver: string, optional
                The version of the dataset. Each experiment is assigned a
                unique code (version). Production data is assigned 1 or 2,
                and experimental data in Operations 11, 12 ,...
                Research or Member State's experiments have a four letter
                experiment identifier.
                Default is "1".

            number: string, optional
                Selects the member in ensemble forecast run. (Only then it
                is necessary.) It has a different meaning depending on
                the type of data.
                E.g. Perturbed Forecasts: specifies the Ensemble forecast member
                Default is an empty string.

            accuracy: string, optional
                Specifies the number of bits per value to be used in the
                generated GRIB coded fields.
                A positive integer may be given to specify the preferred number
                of bits per packed value. This must not be greater than the
                number of bits normally used for a Fortran integer on the
                processor handling the request (typically 32 or 64 bit).
                Within a compute request the accuracy of the original fields
                can be passed to the result field by specifying accuracy=av.
                Default is an empty string.

            grid: string, optional
                Specifies the output grid which can be either a Gaussian grid
                or a Latitude/Longitude grid. MARS requests specifying
                grid=av will return the archived model grid.

                Lat/Lon grid: The grid spacing needs to be an integer
                fraction of 90 degrees e.g. grid = 0.5/0.5

                Gaussian grid: specified by a letter denoting the type of
                Gaussian grid followed by an integer (the grid number)
                representing the number of lines between the Pole and Equator,
                e.g.
                grid = F160 - full (or regular) Gaussian grid with
                       160 latitude lines between the pole and equator
                grid = N320 - ECMWF original reduced Gaussian grid with
                       320 latitude lines between the pole and equator,
                       see Reduced Gaussian Grids for grid numbers used at ECMWF
                grid = O640 - ECMWF octahedral (reduced) Gaussian grid with
                       640 latitude lines between the pole and equator
                Default is an empty string.

            gaussian: string, optional
                This parameter is deprecated and should no longer be used.
                Specifies the desired type of Gaussian grid for the output.
                Valid Gaussian grids are quasi-regular (reduced) or regular.
                Keyword gaussian can only be specified together with
                keyword grid. Gaussian without grid has no effect.
                Default is an empty string.

            target: string, optional
                Specifies a file into which data is to be written after
                retrieval or manipulation. Path names should always be
                enclosed in double quotes. The MARS client supports automatic
                generation of multiple target files using MARS keywords
                enclosed in square brackets [ ].  If the environment variable
                MARS_MULTITARGET_STRICT_FORMAT is set to 1 before calling mars,
                the keyword values will be used in the filename as shown by
                the ecCodes GRIB tool grib_ls -m, e.g. with
                MARS_MULTITARGET_STRICT_FORMAT set to 1 the keywords time,
                expver and param will be formatted as 0600, 0001 and 129.128
                rather than 600, 1 and 129.
                Default is an empty string.

            param: string, optional
                Specifies the meteorological parameter.
                The list of meteorological parameters in MARS is extensive.
                Their availability is directly related to their meteorological
                meaning and, therefore, the rest of directives specified
                in the MARS request.
                Meteorological parameters can be specified by their
                GRIB code (param=130), their mnemonic (param=t) or
                full name (param=temperature).
                The list of parameter should be seperated by a "/"-sign.
                E.g. 130/131/133
                Default is an empty string.

        @Return:
            <nothing>
        '''

        self.server = server
        self.marsclass = marsclass
        self.type = type
        self.levtype = levtype
        self.levelist = levelist
        self.repres = repres
        self.date = date
        self.resol = resol
        self.stream = stream
        self.area = area
        self.time = time
        self.step = step
        self.expver = expver
        self.number = number
        self.accuracy = accuracy
        self.grid = grid
        self.gaussian = gaussian
        self.target = target
        self.param = param

        return


    def displayInfo(self):
        '''
        @Description:
            Prints all class attributes and their values.

        @Input:
            self: instance of MARSretrieval
                For description see class documentation.

        @Return:
            <nothing>
        '''
        # Get all class attributes and their values as a dictionary
        attrs = vars(self)

        # iterate through all attributes and print them
        # with their corresponding values
        for item in attrs.items():
            if item[0] in ('server'):
                pass
            else:
                print(item[0] + ': ' + str(item[1]))

        return

    def dataRetrieve(self):
        '''
        @Description:
            Submits a MARS retrieval. Depending on the existence of
            ECMWF Web-API it is submitted via Python or a
            subprocess in the Shell. The parameter for the mars retrieval
            are taken from the defined class attributes.

        @Input:
            self: instance of MARSretrieval
                For description see class documentation.

        @Return:
            <nothing>
        '''
        # Get all class attributes and their values as a dictionary
        attrs = vars(self)

        # convert the dictionary of attributes into a comma
        # seperated list of attributes with their values
        # needed for the retrieval call
        s = 'ret'
        for k, v in attrs.iteritems():
            if k in ('server'):
                continue
            if k == 'marsclass':
                k = 'class'
            if v == '':
                continue
            if k.lower() == 'target':
                target = v
            else:
                s = s + ',' + k + '=' + str(v)

        # MARS request via Python script
        if self.server is not False:
            try:
                self.server.execute(s, target)
            except:
                print('MARS Request failed, \
                    have you already registered at apps.ecmwf.int?')
                raise IOError
            if os.stat(target).st_size == 0:
                print('MARS Request returned no data - please check request')
                raise IOError
        # MARS request via extra process in shell
        else:
            s += ',target = "' + target + '"'
            p = subprocess.Popen(['mars'], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, bufsize=1)
            pout = p.communicate(input=s)[0]
            print(pout.decode())
            if 'Some errors reported' in pout.decode():
                print('MARS Request failed - please check request')
                raise IOError

            if os.stat(target).st_size == 0:
                print('MARS Request returned no data - please check request')
                raise IOError

        return




class ECFlexpart:
    '''
    Class to retrieve ECMWF data specific for running FLEXPART.
    '''
    def __init__(self, c, fluxes=False): #done/ verstehen
        '''
        @Description:
            Creates an object/instance of ECFlexpart with the
            associated settings of its attributes for the retrieval.

        @Input:
            self: instance of ECFlexpart
                The current object of the class.

            c: instance of class Control
                Contains all the parameters of control files, which are e.g.:
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
                Decides if a the flux parameter settings are stored or
                the rest of the parameter list.
                Default value is False.

        @Return:
            <nothing>
        '''

        # different mars types for retrieving reanalysis data for flexpart
        self.types = dict()
        try:
            if c.maxstep > len(c.type):    # Pure forecast mode
                c.type = [c.type[1]]
                c.step = ['{:0>3}'.format(int(c.step[0]))]
                c.time = [c.time[0]]
                for i in range(1, c.maxstep + 1):
                    c.type.append(c.type[0])
                    c.step.append('{:0>3}'.format(i))
                    c.time.append(c.time[0])
        except:
            pass

        self.inputdir = c.inputdir
        self.basetime = c.basetime
        self.dtime = c.dtime
        self.mars = {}
        i = 0
        j = 0
        if fluxes is True and c.maxstep < 24:
            # only FC with start times at 00/12 (without 00/12)
            self.types[c.type[1]] = {'times': '00/12',
                                     'steps': '{}/to/12/by/{}'.format(c.dtime,
                                                                      c.dtime)}
            i = 1
            for k in [0, 12]:
                for j in range(int(c.dtime), 13, int(c.dtime)):
                    self.mars['{:0>3}'.format(i * int(c.dtime))] = \
                           [c.type[1], '{:0>2}'.format(k), '{:0>3}'.format(j)]
                    i += 1
        else:
            for ty, st, ti in zip(c.type, c.step, c.time):
                btlist = range(24)
                if c.basetime == '12':
                    btlist = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
                if c.basetime == '00':
                    btlist = [13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 0]

                if mod(i, int(c.dtime)) == 0 and \
                    (i in btlist or c.maxstep > 24):

                    if ty not in self.types.keys():
                        self.types[ty] = {'times': '', 'steps': ''}

                    if ti not in self.types[ty]['times']:
                        if len(self.types[ty]['times']) > 0:
                            self.types[ty]['times'] += '/'
                        self.types[ty]['times'] += ti

                    if st not in self.types[ty]['steps']:
                        if len(self.types[ty]['steps']) > 0:
                            self.types[ty]['steps'] += '/'
                        self.types[ty]['steps'] += st

                    self.mars['{:0>3}'.format(j)] = [ty,
                                                     '{:0>2}'.format(int(ti)),
                                                     '{:0>3}'.format(int(st))]
                    j += int(c.dtime)

                i += 1

        # Different grids need different retrievals
        # SH = Spherical Harmonics, GG = Gaussian Grid,
        # OG = Output Grid, ML = MultiLevel, SL = SingleLevel
        self.params = {'SH__ML': '', 'SH__SL': '',
                       'GG__ML': '', 'GG__SL': '',
                       'OG__ML': '', 'OG__SL': '',
                       'OG_OROLSM_SL': '', 'OG_acc_SL': ''}
        self.marsclass = c.marsclass
        self.stream = c.stream
        self.number = c.number
        self.resol = c.resol
        if 'N' in c.grid:  # Gaussian output grid
            self.grid = c.grid
            self.area = 'G'
        else:
            self.grid = '{}/{}'.format(int(c.grid) / 1000., int(c.grid) / 1000.)
            self.area = '{}/{}/{}/{}'.format(int(c.upper) / 1000.,
                                             int(c.left) / 1000.,
                                             int(c.lower) / 1000.,
                                             int(c.right) / 1000.)

        self.accuracy = c.accuracy
        self.level = c.level
        try:
            self.levelist = c.levelist
        except:
            self.levelist = '1/to/' + c.level

        self.glevelist = '1/to/' + c.level

        try:
            self.gaussian = c.gaussian
        except:
            self.gaussian = ''

        try:
            self.dataset = c.dataset
        except:
            self.dataset = ''

        try:
            self.expver = c.expver
        except:
            self.expver = '1'

        try:
            self.number = c.number
        except:
            self.number = '0'

        self.outputfilelist = []


        # Now comes the nasty part that deals with the different
        # scenarios we have:
        # 1) Calculation of etadot on
        #    a) Gaussian grid
        #    b) Output grid
        #    c) Output grid using parameter 77 retrieved from MARS
        # 3) Calculation/Retrieval of omega
        # 4) Download also data for WRF

        if fluxes is False:
            self.params['SH__SL'] = ['LNSP', 'ML', '1', 'OFF']
    #        self.params['OG__SL'] = ["SD/MSL/TCC/10U/10V/2T/2D/129/172",
    #                                 'SFC','1',self.grid]
            self.params['OG__SL'] = ["141/151/164/165/166/167/168/129/172", \
                                     'SFC', '1', self.grid]
            self.params['OG_OROLSM__SL'] = ["160/27/28/173", \
                                            'SFC', '1', self.grid]

            if len(c.addpar) > 0:
                if c.addpar[0] == '/':
                    c.addpar = c.addpar[1:]
                self.params['OG__SL'][0] += '/' + '/'.join(c.addpar)
            self.params['OG__ML'] = ['T/Q', 'ML', self.levelist, self.grid]

            if c.gauss == '0' and c.eta == '1':
                # the simplest case
                self.params['OG__ML'][0] += '/U/V/77'
            elif c.gauss == '0' and c.eta == '0':
                # this is not recommended (inaccurate)
                self.params['OG__ML'][0] += '/U/V'
            elif c.gauss == '1' and c.eta == '0':
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

            if c.omega == '1':
                self.params['OG__ML'][0] += '/W'

            try:
                # add cloud water content if necessary
                if c.cwc == '1':
                    self.params['OG__ML'][0] += '/CLWC/CIWC'
            except:
                pass

            try:
                # add vorticity and geopotential height for WRF if necessary
                if c.wrf == '1':
                    self.params['OG__ML'][0] += '/Z/VO'
                    if '/D' not in self.params['OG__ML'][0]:
                        self.params['OG__ML'][0] += '/D'
                    #wrf_sfc = 'sp/msl/skt/2t/10u/10v/2d/z/lsm/sst/ci/sd/stl1/ /
                    #           stl2/stl3/stl4/swvl1/swvl2/swvl3/swvl4'.upper()
                    wrf_sfc = '134/235/167/165/166/168/129/172/34/31/141/ \
                               139/170/183/236/39/40/41/42'.upper()
                    lwrt_sfc = wrf_sfc.split('/')
                    for par in lwrt_sfc:
                        if par not in self.params['OG__SL'][0]:
                            self.params['OG__SL'][0] += '/' + par
            except:
                pass
        else:
            self.params['OG_acc_SL'] = ["LSP/CP/SSHF/EWSS/NSSS/SSR", \
                                        'SFC', '1', self.grid]

        # if needed, add additional WRF specific parameters here

        return


    def write_namelist(self, c, filename): #done
        '''
        @Description:
            Creates a namelist file in the temporary directory and writes
            the following values to it: maxl, maxb, mlevel,
            mlevelist, mnauf, metapar, rlo0, rlo1, rla0, rla1,
            momega, momegadiff, mgauss, msmooth, meta, metadiff, mdpdeta

        @Input:
            self: instance of ECFlexpart
                The current object of the class.

            c: instance of class Control
                Contains all the parameters of control files, which are e.g.:
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
        area = asarray(self.area.split('/')).astype(float)
        grid = asarray(self.grid.split('/')).astype(float)

        if area[1] > area[3]:
            area[1] -= 360
        zyk = abs((area[3] - area[1] - 360.) + grid[1]) < 1.e-6
        maxl = int((area[3] - area[1]) / grid[1]) + 1
        maxb = int((area[0] - area[2]) / grid[0]) + 1

        with open(self.inputdir + '/' + filename, 'w') as f:
            f.write('&NAMGEN\n')
            f.write(',\n  '.join(['maxl = ' + str(maxl), 'maxb = ' + str(maxb),
                    'mlevel = ' + self.level,
                    'mlevelist = ' + '"' + self.levelist + '"',
                    'mnauf = ' + self.resol, 'metapar = ' + '77',
                    'rlo0 = ' + str(area[1]), 'rlo1 = ' + str(area[3]),
                    'rla0 = ' + str(area[2]), 'rla1 = ' + str(area[0]),
                    'momega = ' + c.omega, 'momegadiff = ' + c.omegadiff,
                    'mgauss = ' + c.gauss, 'msmooth = ' + c.smooth,
                    'meta = ' + c.eta, 'metadiff = ' + c.etadiff,
                    'mdpdeta = ' + c.dpdeta]))

            f.write('\n/\n')

        return

    def retrieve(self, server, dates, times, inputdir=''):
        '''
        @Description:


        @Input:
            self: instance of ECFlexpart

            server: instance of ECMWFService

            dates:

            times:

            inputdir: string, optional
                Default string is empty ('').

        @Return:
            <nothing>
        '''
        self.dates = dates
        self.server = server

        if inputdir == "":
            self.inputdir = '.'
        else:
            self.inputdir = inputdir

        # Retrieve Q not for using Q but as a template for a reduced gaussian
        # grid one date and time is enough
        # Take analysis at 00
        qdate = self.dates
        idx = qdate.find("/")
        if (idx > 0):
            qdate = self.dates[:idx]

        #QG =  MARSretrieval(self.server, dataset = self.dataset, marsclass = self.marsclass, stream = self.stream, type = "an", levtype = "ML", levelist = "1",
                             #gaussian = "reduced",grid = '{}'.format((int(self.resol)+1)/2), resol = self.resol,accuracy = self.accuracy,target = self.inputdir+"/"+"QG.grb",
                             #date = qdate, time = "00",expver = self.expver, param = "133.128")
        #QG.displayInfo()
        #QG.dataRetrieve()

        oro = False
        for ftype in self.types:
            for pk, pv in self.params.iteritems():
                if isinstance(pv, str):     # or pk != 'GG__SL' :
                    continue
                mftype = ''+ftype
                mftime = self.types[ftype]['times']
                mfstep = self.types[ftype]['steps']
                mfdate = self.dates
                mfstream = self.stream
                mftarget = self.inputdir + "/" + ftype + pk + '.' + \
                           self.dates.split('/')[0] + '.' + str(os.getppid()) +\
                           '.' + str(os.getpid()) + ".grb"
                if pk == 'OG__SL':
                    pass
                if pk == 'OG_OROLSM__SL':
                    if oro is False:
                        mfstream = 'OPER'
                        mftype = 'AN'
                        mftime = '00'
                        mfstep = '000'
                        mfdate = self.dates.split('/')[0]
                        mftarget = self.inputdir + "/" + pk + '.' + mfdate + \
                                   '.' + str(os.getppid()) + '.' + \
                                   str(os.getpid()) + ".grb"
                        oro = True
                    else:
                        continue

                if pk == 'GG__SL' and pv[0] == 'Q':
                    area = ""
                    gaussian = 'reduced'
                else:
                    area = self.area
                    gaussian = self.gaussian

                if self.basetime is None:
                    MR =  MARSretrieval(self.server,
                            marsclass=self.marsclass, stream=mfstream,
                            type=mftype, levtype=pv[1], levelist=pv[2],
                            resol=self.resol, gaussian=gaussian,
                            accuracy=self.accuracy, grid=pv[3],
                            target=mftarget, area=area, date=mfdate,
                            time=mftime, number=self.number, step=mfstep,
                            expver=self.expver, param=pv[0])

                    MR.displayInfo()
                    MR.dataRetrieve()
    # The whole else section is only necessary for operational scripts.
    # It could be removed
                else:
                    # check if mars job requests fields beyond basetime.
                    # If yes eliminate those fields since they may not
                    # be accessible with user's credentials
                    sm1 = -1
                    if 'by' in mfstep:
                        sm1 = 2
                    tm1 = -1
                    if 'by' in mftime:
                        tm1 = 2
                    maxtime = datetime.datetime.strptime(
                                mfdate.split('/')[-1] + mftime.split('/')[tm1],
                                '%Y%m%d%H') + datetime.timedelta(
                                hours=int(mfstep.split('/')[sm1]))

                    elimit = datetime.datetime.strptime(
                                mfdate.split('/')[-1] +
                                self.basetime, '%Y%m%d%H')

                    if self.basetime == '12':
                        if 'acc' in pk:

                # Strategy: if maxtime-elimit> = 24h reduce date by 1,
                # if 12h< = maxtime-elimit<12h reduce time for last date
                # if maxtime-elimit<12h reduce step for last time
                # A split of the MARS job into 2 is likely necessary.
                            maxtime = elimit-datetime.timedelta(hours=24)
                            mfdate = '/'.join(('/'.join(mfdate.split('/')[:-1]),
                                                datetime.datetime.strftime(
                                                maxtime, '%Y%m%d')))

                            MR = MARSretrieval(self.server,
                                            marsclass=self.marsclass,
                                            stream=self.stream, type=mftype,
                                            levtype=pv[1], levelist=pv[2],
                                            resol=self.resol, gaussian=gaussian,
                                            accuracy=self.accuracy, grid=pv[3],
                                            target=mftarget, area=area,
                                            date=mfdate, time=mftime,
                                            number=self.number, step=mfstep,
                                            expver=self.expver, param=pv[0])

                            MR.displayInfo()
                            MR.dataRetrieve()

                            maxtime = elimit - datetime.timedelta(hours=12)
                            mfdate = datetime.datetime.strftime(maxtime,
                                                                '%Y%m%d')
                            mftime = '00'
                            mftarget = self.inputdir + "/" + ftype + pk + \
                                       '.' + mfdate + '.' + str(os.getppid()) +\
                                       '.' + str(os.getpid()) + ".grb"

                            MR = MARSretrieval(self.server,
                                            marsclass=self.marsclass,
                                            stream=self.stream, type=mftype,
                                            levtype=pv[1], levelist=pv[2],
                                            resol=self.resol, gaussian=gaussian,
                                            accuracy=self.accuracy, grid=pv[3],
                                            target=mftarget, area=area,
                                            date=mfdate, time=mftime,
                                            number=self.number, step=mfstep,
                                            expver=self.expver, param=pv[0])

                            MR.displayInfo()
                            MR.dataRetrieve()
                        else:
                            MR = MARSretrieval(self.server,
                                            marsclass=self.marsclass,
                                            stream=self.stream, type=mftype,
                                            levtype=pv[1], levelist=pv[2],
                                            resol=self.resol, gaussian=gaussian,
                                            accuracy=self.accuracy, grid=pv[3],
                                            target=mftarget, area=area,
                                            date=mfdate, time=mftime,
                                            number=self.number, step=mfstep,
                                            expver=self.expver, param=pv[0])

                            MR.displayInfo()
                            MR.dataRetrieve()
                    else:
                        maxtime = elimit - datetime.timedelta(hours=24)
                        mfdate = datetime.datetime.strftime(maxtime,'%Y%m%d')

                        mftimesave = ''.join(mftime)

                        if '/' in mftime:
                            times = mftime.split('/')
                            while ((int(times[0]) +
                                   int(mfstep.split('/')[0]) <= 12) and
                                  (pk != 'OG_OROLSM__SL') and 'acc' not in pk):
                                times = times[1:]
                            if len(times) > 1:
                                mftime = '/'.join(times)
                            else:
                                mftime = times[0]

                        MR = MARSretrieval(self.server,
                                        marsclass=self.marsclass,
                                        stream=self.stream, type=mftype,
                                        levtype=pv[1], levelist=pv[2],
                                        resol=self.resol, gaussian=gaussian,
                                        accuracy=self.accuracy, grid=pv[3],
                                        target=mftarget, area=area,
                                        date=mfdate, time=mftime,
                                        number=self.number, step=mfstep,
                                        expver=self.expver, param=pv[0])

                        MR.displayInfo()
                        MR.dataRetrieve()

                        if (int(mftimesave.split('/')[0]) == 0 and
                            int(mfstep.split('/')[0]) == 0 and
                            pk != 'OG_OROLSM__SL'):
                            mfdate = datetime.datetime.strftime(elimit,'%Y%m%d')
                            mftime = '00'
                            mfstep = '000'
                            mftarget = self.inputdir + "/" + ftype + pk + \
                                       '.' + mfdate + '.' + str(os.getppid()) +\
                                       '.' + str(os.getpid()) + ".grb"

                            MR = MARSretrieval(self.server,
                                        marsclass=self.marsclass,
                                        stream=self.stream, type=mftype,
                                        levtype=pv[1], levelist=pv[2],
                                        resol=self.resol, gaussian=gaussian,
                                        accuracy=self.accuracy, grid=pv[3],
                                        target=mftarget, area=area,
                                        date=mfdate, time=mftime,
                                        number=self.number, step=mfstep,
                                        expver=self.expver, param=pv[0])

                            MR.displayInfo()
                            MR.dataRetrieve()

            print("MARS retrieve done... ")

            return


    def process_output(self, c): #done
        '''
        @Description:
            The grib files are postprocessed depending on selection in
            control file. The following modifications might be done if
            properly switched in control file:
            GRIB2 - Conversion to GRIB2
            ECTRANS - Transfer of files to gateway server
            ECSTORAGE - Storage at ECMWF server
            GRIB2FLEXPART - Conversion of GRIB files to FLEXPART binary format

        @Input:
            self: instance of ECFlexpart
                The current object of the class.

            c: instance of class Control
                Contains all the parameters of control files, which are e.g.:
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

        print('Postprocessing:\n Format: {}\n'.format(c.format))

        if c.ecapi is False:
            print('ecstorage: {}\n ecfsdir: {}\n'.
                  format(c.ecstorage, c.ecfsdir))
            if not hasattr(c, 'gateway'):
                c.gateway = os.getenv('GATEWAY')
            if not hasattr(c, 'destination'):
                c.destination = os.getenv('DESTINATION')
            print('ectrans: {}\n gateway: {}\n destination: {}\n '
                    .format(c.ectrans, c.gateway, c.destination))

        print('Output filelist: \n', self.outputfilelist)

        if c.format.lower() == 'grib2':
            for ofile in self.outputfilelist:
                p = subprocess.check_call(['grib_set', '-s', 'edition=2, \
                                            productDefinitionTemplateNumber=8',
                                            ofile, ofile + '_2'])
                p = subprocess.check_call(['mv', ofile + '_2', ofile])

        if int(c.ectrans) == 1 and c.ecapi is False:
            for ofile in self.outputfilelist:
                p = subprocess.check_call(['ectrans', '-overwrite', '-gateway',
                                           c.gateway, '-remote', c.destination,
                                           '-source', ofile])
                print('ectrans:', p)

        if int(c.ecstorage) == 1 and c.ecapi is False:
            for ofile in self.outputfilelist:
                p = subprocess.check_call(['ecp', '-o', ofile,
                                           os.path.expandvars(c.ecfsdir)])

        if c.outputdir != c.inputdir:
            for ofile in self.outputfilelist:
                p = subprocess.check_call(['mv', ofile, c.outputdir])

        # prepare environment for the grib2flexpart run
        # to convert grib to flexpart binary
        if c.grib2flexpart == '1':

            # generate AVAILABLE file
            # Example of AVAILABLE file data
            # 20131107 000000      EN13110700              ON DISC
            clist = []
            for ofile in self.outputfilelist:
                fname = ofile.split('/')
                if '.' in fname[-1]:
                    l = fname[-1].split('.')
                    timestamp = datetime.datetime.strptime(l[0][-6:] + l[1],
                                                           '%y%m%d%H')
                    timestamp += datetime.timedelta(hours=int(l[2]))
                    cdate = datetime.datetime.strftime(timestamp, '%Y%m%d')
                    chms = datetime.datetime.strftime(timestamp, '%H%M%S')
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
            with open(pwd + '/pathnames','w') as f:
                f.write(pwd + '/Options/\n')
                f.write(pwd + '/\n')
                f.write(pwd + '/\n')
                f.write(pwd + '/AVAILABLE\n')
                f.write(' = == = == = == = == = == ==  = \n')

            # create Options dir if necessary
            if not os.path.exists(pwd + '/Options'):
                os.makedirs(pwd+'/Options')

            # read template COMMAND file
            with open(os.path.expandvars(
                     os.path.expanduser(c.flexpart_root_scripts)) +
                     '/../Options/COMMAND', 'r') as f:
                lflist = f.read().split('\n')

            # find index of list where to put in the
            # date and time information
            # usually after the LDIRECT parameter
            i = 0
            for l in lflist:
                if 'LDIRECT' in l.upper():
                    break
                i += 1

#            clist.sort()
            # insert the date and time information of run star and end
            # into the list of lines of COMMAND file
            lflist = lflist[:i+1] + \
                     [clist[0][:16], clist[-1][:16]] + \
                     lflist[i+3:]

            # write the new COMMAND file
            with open(pwd + '/Options/COMMAND', 'w') as g:
                g.write('\n'.join(lflist) + '\n')

            # change to outputdir and start the
            # grib2flexpart run
            # afterwards switch back to the working dir
            os.chdir(c.outputdir)
            p = subprocess.check_call([os.path.expandvars(
                        os.path.expanduser(c.flexpart_root_scripts)) +
                        '/../FLEXPART_PROGRAM/grib2flexpart',
                        'useAvailable', '.'])
            os.chdir(pwd)

        return

    def create(self, inputfiles, c): #done
        '''
        @Description:
            This method is based on the ECMWF example index.py
            https://software.ecmwf.int/wiki/display/GRIB/index.py

            An index file will be created which depends on the combination
            of "date", "time" and "stepRange" values. This is used to iterate
            over all messages in the grib files passed through the parameter
            "inputfiles" to seperate specific parameters into fort.* files.
            Afterwards the FORTRAN program Convert2 is called to convert
            the data fields all to the same grid and put them in one file
            per day.

        @Input:
            self: instance of ECFlexpart
                The current object of the class.

            inputfiles: instance of UIOFiles
                Contains a list of files.

            c: instance of class Control
                Contains all the parameters of control files, which are e.g.:
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

        table128 = init128(c.ecmwfdatadir +
                           '/grib_templates/ecmwf_grib1_table_128')
        wrfpars = toparamId('sp/mslp/skt/2t/10u/10v/2d/z/lsm/sst/ci/sd/\
                            stl1/stl2/stl3/stl4/swvl1/swvl2/swvl3/swvl4',
                            table128)

        index_keys = ["date", "time", "step"]
        indexfile = c.inputdir + "/date_time_stepRange.idx"
        silentremove(indexfile)
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


        for prod in product(*index_vals):
            # e.g. prod = ('20170505', '0', '12')
            #             (  date    ,time, step)
            # per date e.g. time = 0, 600, 1200, 1800
            # per time e.g. step = 0, 3, 6, 9, 12
            for i in range(len(index_keys)):
                grib_index_select(iid, index_keys[i], prod[i])

            gid = grib_new_from_index(iid)
            # do convert2 program if gid at this time is not None,
            # therefore save in hid
            hid = gid
            if gid is not None:
                cdate = str(grib_get(gid, 'date'))
                time = grib_get(gid, 'time')
                type = grib_get(gid, 'type')
                step = grib_get(gid, 'step')
                # create correct timestamp from the three time informations
                # date, time, step
                timestamp = datetime.datetime.strptime(
                                cdate + '{:0>2}'.format(time/100), '%Y%m%d%H')
                timestamp += datetime.timedelta(hours=int(step))

                cdateH = datetime.datetime.strftime(timestamp, '%Y%m%d%H')
                chms = datetime.datetime.strftime(timestamp, '%H%M%S')

                if c.basetime is not None:
                    slimit = datetime.datetime.strptime(
                                c.start_date + '00', '%Y%m%d%H')
                    bt = '23'
                    if c.basetime == '00':
                        bt = '00'
                        slimit = datetime.datetime.strptime(
                                    c.end_date + bt, '%Y%m%d%H') - \
                                    datetime.timedelta(hours=12-int(c.dtime))
                    if c.basetime == '12':
                        bt = '12'
                        slimit = datetime.datetime.strptime(
                                    c.end_date + bt, '%Y%m%d%H') - \
                                 datetime.timedelta(hours=12-int(c.dtime))

                    elimit = datetime.datetime.strptime(
                                c.end_date + bt, '%Y%m%d%H')

                    if timestamp < slimit or timestamp > elimit:
                        continue

            try:
                if c.wrf == '1':
                    if 'olddate' not in locals():
                        fwrf = open(c.outputdir + '/WRF' + cdate +
                                    '.{:0>2}'.format(time) + '.000.grb2', 'w')
                        olddate = cdate[:]
                    else:
                        if cdate != olddate:
                            fwrf = open(c.outputdir + '/WRF' + cdate +
                                        '.{:0>2}'.format(time) + '.000.grb2',
                                        'w')
                            olddate = cdate[:]
            except AttributeError:
                pass

            # delete old fort.* files and open them newly
            fdict = {'10':None, '11':None, '12':None, '13':None, '16':None,
                         '17':None, '19':None, '21':None, '22':None, '20':None}
            #for f in fdict.keys():
            #    silentremove(c.inputdir + "/fort." + f)
            for k, f in fdict.iteritems():
                silentremove(c.inputdir + "/fort." + k)
                fdict[k] = open(c.inputdir + '/fort.' + k, 'w')

            savedfields = []
            while 1:
                if gid is None:
                    break
                paramId = grib_get(gid, 'paramId')
                gridtype = grib_get(gid, 'gridType')
                datatype = grib_get(gid, 'dataType')
                levtype = grib_get(gid, 'typeOfLevel')
                if paramId == 133 and gridtype == 'reduced_gg':
                # Relative humidity (Q.grb) is used as a template only
                # so we need the first we "meet"
                    with open(c.inputdir + '/fort.18', 'w') as fout:
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
                elif paramId in [129, 138, 155] and levtype == 'hybrid' \
                                                and c.wrf == '1':
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
                    if c.wrf == '1':
# die if abfrage scheint ueberfluessig da eh das gleihce ausgefuehrt wird
                        if levtype == 'hybrid':
                            if paramId in [129, 130, 131, 132, 133, 138, 155]:
                                grib_write(gid, fwrf)
                        else:
                            if paramId in wrfpars:
                                grib_write(gid, fwrf)
                except AttributeError:
                    pass

                grib_release(gid)
                gid = grib_new_from_index(iid)

        for f in fdict.values():
            f.close()

        # call for CONVERT2
# AUSLAGERN IN EIGENE FUNKTION

        if hid is not None:
            pwd = os.getcwd()
            os.chdir(c.inputdir)
            if os.stat('fort.21').st_size == 0 and int(c.eta) == 1:
                print('Parameter 77 (etadot) is missing, most likely it is \
                       not available for this type or date/time\n')
                print('Check parameters CLASS, TYPE, STREAM, START_DATE\n')
                myerror(c, 'fort.21 is empty while parameter eta is set \
                            to 1 in CONTROL file')

            p = subprocess.check_call([os.path.expandvars(
                    os.path.expanduser(c.exedir)) + '/CONVERT2'], shell=True)
            os.chdir(pwd)
            # create the corresponding output file fort.15
            # (generated by CONVERT2)
            # + fort.16 (paramId 167 and paramId 168)
            fnout = c.inputdir + '/' + c.prefix
            if c.maxstep > 12:
                suffix = cdate[2:8] + '.{:0>2}'.format(time/100) + \
                         '.{:0>3}'.format(step)
            else:
                suffix = cdateH[2:10]

            fnout += suffix
            print("outputfile = " + fnout)
            self.outputfilelist.append(fnout) # needed for final processing
            fout = open(fnout, 'wb')
            shutil.copyfileobj(open(c.inputdir + '/fort.15', 'rb'), fout)
            if c.cwc == '1':
                shutil.copyfileobj(open(c.inputdir + '/fort.22', 'rb'), fout)
            shutil.copyfileobj(open(c.inputdir + '/flux' + cdate[0:2] +
                                    suffix, 'rb'), fout)
            shutil.copyfileobj(open(c.inputdir + '/fort.16', 'rb'), fout)
            orolsm = glob.glob(c.inputdir +
                               '/OG_OROLSM__SL.*.' + c.ppid + '*')[0]
            shutil.copyfileobj(open(orolsm, 'rb'), fout)
            fout.close()
            if c.omega == '1':
                fnout = c.outputdir + '/OMEGA'
                fout  =  open(fnout, 'wb')
                shutil.copyfileobj(open(c.inputdir + '/fort.25', 'rb'), fout)

        try:
            if c.wrf == '1':
                fwrf.close()
        except:
            pass

        grib_index_release(iid)

        return


    def deacc_fluxes(self, inputfiles, c):
        '''
        @Description:


        @Input:
            self: instance of ECFlexpart
                The current object of the class.

            inputfiles: instance of UIOFiles
                Contains a list of files.

            c: instance of class Control
                Contains all the parameters of control files, which are e.g.:
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

        table128 = init128(c.ecmwfdatadir +
                           '/grib_templates/ecmwf_grib1_table_128')
        pars = toparamId(self.params['OG_acc_SL'][0], table128)

        index_keys = ["date", "time", "step"]
        indexfile = c.inputdir + "/date_time_stepRange.idx"
        silentremove(indexfile)
        grib = GribTools(inputfiles.files)
        # creates new index file
        iid = grib.index(index_keys=index_keys, index_file=indexfile)

        # read values of index keys
        index_vals = []
        for key in index_keys:
            key_vals = grib_index_get(iid,key)
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
            # index_vals[1]: ('0', '1200', '1800', '600') ; time
            # index_vals[2]: ('0', '12', '3', '6', '9') ; stepRange

        valsdict = {}
        svalsdict = {}
        stepsdict = {}
        for p in pars:
            valsdict[str(p)] = []
            svalsdict[str(p)] = []
            stepsdict[str(p)] = []
 # ab hier eien Einrückung zurück!!!!
            for prod in product(*index_vals):
                # e.g. prod = ('20170505', '0', '12')
                #             (  date    ,time, step)
                # per date e.g. time = 0, 600, 1200, 1800
                # per time e.g. step = 0, 3, 6, 9, 12
                for i in range(len(index_keys)):
                    grib_index_select(iid, index_keys[i], prod[i])

                gid = grib_new_from_index(iid)
                # do convert2 program if gid at this time is not None,
                # therefore save in hid
                hid = gid
                if gid is not None:
                    cdate = str(grib_get(gid, 'date'))
                    time = grib_get(gid, 'time')
                    type = grib_get(gid, 'type')
                    step = grib_get(gid, 'step')
                    # date+time+step-2*dtime
                    #(since interpolated value valid for step-2*dtime)
                    sdate = datetime.datetime(year=cdate / 10000,
                                              month=mod(cdate, 10000) / 100,
                                              day=mod(cdate, 100),
                                              hour=time / 100)
                    fdate = sdate + datetime.timedelta(
                                        hours=step - 2 * int(c.dtime))
                    sdates = sdate + datetime.timedelta(hours=step)
                else:
                    break

            if c.maxstep > 12:
                fnout = c.inputdir + '/flux' + \
                    sdate.strftime('%Y%m%d') + '.{:0>2}'.format(time/100) + \
                    '.{:0>3}'.format(step-2*int(c.dtime))
                gnout = c.inputdir + '/flux' + \
                    sdate.strftime('%Y%m%d')+'.{:0>2}'.format(time/100) + \
                    '.{:0>3}'.format(step-int(c.dtime))
                hnout = c.inputdir + '/flux' + \
                    sdate.strftime('%Y%m%d')+'.{:0>2}'.format(time/100) + \
                    '.{:0>3}'.format(step)
                g = open(gnout, 'w')
                h = open(hnout, 'w')
            else:
                fnout = c.inputdir + '/flux' + fdate.strftime('%Y%m%d%H')
                gnout = c.inputdir + '/flux' + (fdate+datetime.timedelta(
                    hours = int(c.dtime))).strftime('%Y%m%d%H')
                hnout = c.inputdir + '/flux' + sdates.strftime('%Y%m%d%H')
                g = open(gnout, 'w')
                h = open(hnout, 'w')
            print("outputfile = " + fnout)
            f = open(fnout, 'w')

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
                        fak = 1./1000.
                    else:
                        fak = 3600.

                    values = (reshape(values, (nj, ni))).flatten() / fak
                    vdp.append(values[:])  # save the accumulated values
                    if step <= int(c.dtime):
                        svdp.append(values[:] / int(c.dtime))
                    else: # deaccumulate values
                        svdp.append((vdp[-1] - vdp[-2]) / int(c.dtime))

                    print(cparamId, atime, step, len(values),
                          values[0], std(values))
                    # save the 1/3-hourly or specific values
                    # svdp.append(values[:])
                    sd.append(step)
                    # len(svdp) correspond to the time
                    if len(svdp) >= 3:
                        if len(svdp) > 3:
                            if cparamId == '142' or cparamId == '143':
                                values = darain(svdp)
                            else:
                                values = dapoly(svdp)

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
                        grib_write(gid, f)

                        if c.basetime is not None:
                            elimit = datetime.datetime.strptime(c.end_date +
                                                                c.basetime,
                                                                '%Y%m%d%H')
                        else:
                            elimit = sdate + datetime.timedelta(2*int(c.dtime))

                        # squeeze out information of last two steps contained
                        # in svdp
                        # if step+int(c.dtime) == c.maxstep and c.maxstep>12
                        # or sdates+datetime.timedelta(hours = int(c.dtime))
                        # >= elimit:
                        # Note that svdp[0] has not been popped in this case

                        if (step == c.maxstep and c.maxstep > 12
                            or sdates == elimit):
                            values = svdp[3]
                            grib_set_values(gid, values)
                            grib_set(gid, 'step', 0)
                            truedatetime = fdate + datetime.timedelta(
                                     hours=2*int(c.dtime))
                            grib_set(gid, 'time', truedatetime.hour * 100)
                            grib_set(gid, 'date', truedatetime.year * 10000 +
                                     truedatetime.month * 100 +
                                     truedatetime.day)
                            grib_write(gid, h)

                            #values = (svdp[1]+svdp[2])/2.
                            if cparamId == '142' or cparamId == '143':
                                values = darain(list(reversed(svdp)))
                            else:
                                values = dapoly(list(reversed(svdp)))

                            grib_set(gid, 'step',0)
                            truedatetime = fdate + datetime.timedelta(
                                     hours=int(c.dtime))
                            grib_set(gid, 'time', truedatetime.hour * 100)
                            grib_set(gid, 'date', truedatetime.year * 10000 +
                                     truedatetime.month * 100 +
                                     truedatetime.day)
                            grib_set_values(gid, values)
                            grib_write(gid, g)

                    grib_release(gid)

            gid = grib_new_from_index(iid)

            f.close()
            g.close()
            h.close()

            grib_index_release(iid)

        return

