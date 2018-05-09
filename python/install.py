#!/usr/bin/env python
# -*- coding: utf-8 -*-
#************************************************************************
# TODO AP
#AP
# - Functionality Provided is not correct for this file
# - localpythonpath should not be set in module load section!
# - create a class Installation and divide installation in 3 subdefs for
#   ecgate, local and cca seperatly
# - Change History ist nicht angepasst ans File! Original geben lassen
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
import calendar
import shutil
import datetime
import time
import os,sys,glob
import subprocess
import inspect
# add path to submit.py to pythonpath so that python finds its buddies
localpythonpath=os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
sys.path.append(localpythonpath)
from UIOFiles import UIOFiles
from string import strip
from argparse import ArgumentParser,ArgumentDefaultsHelpFormatter
from GribTools import GribTools
from Control import Control
from getMARSdata import getMARSdata
from prepareFLEXPART import prepareFLEXPART
from ECFlexpart import ECFlexpart

# ------------------------------------------------------------------------------
# FUNCTIONS
# ------------------------------------------------------------------------------
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


def main():
    '''
    '''
    os.chdir(localpythonpath)
    args, c = install_args_and_control()
    if args.install_target is not None:
        install_via_gateway(c, args.install_target)
    else:
        print('Please specify installation target (local|ecgate|cca)')
        print('use -h or --help for help')
    sys.exit()

def install_via_gateway(c, target):

    ecd = c.ecmwfdatadir
    template = ecd + 'python/compilejob.temp'
    job = ecd + 'python/compilejob.ksh'
    fo = open(job, 'w')
#AP could do with open(template) as f, open(job, 'w') as fo:
#AP or nested with statements
    with open(template) as f:
        fdata = f.read().split('\n')
        for data in fdata:
            if 'MAKEFILE=' in data:
                if c.makefile is not None:
                    data = 'export MAKEFILE=' + c.makefile
            if 'FLEXPART_ROOT_SCRIPTS=' in data:
                if c.flexpart_root_scripts != '../':
                    data = 'export FLEXPART_ROOT_SCRIPTS=' + \
                            c.flexpart_root_scripts
                else:
                    data='export FLEXPART_ROOT_SCRIPTS=$HOME'
            if target.lower() != 'local':
                if '--workdir' in data:
                    data = '#SBATCH --workdir=/scratch/ms/' + c.ecgid + \
                            '/' + c.ecuid
                if '##PBS -o' in data:
                    data = '##PBS -o /scratch/ms/' + c.ecgid + '/' + c.ecuid + \
                            'flex_ecmwf.$Jobname.$Job_ID.out'
                if 'FLEXPART_ROOT_SCRIPTS=' in data:
                    if c.ec_flexpart_root_scripts != '../':
                        data = 'export FLEXPART_ROOT_SCRIPTS=' + \
                                c.ec_flexpart_root_scripts
                    else:
                        data = 'export FLEXPART_ROOT_SCRIPTS=$HOME'
            fo.write(data + '\n')
    f.close()
    fo.close()

    if target.lower() != 'local':
        template = ecd + 'python/job.temp.o'
#AP hier eventuell Zeile für Zeile lesen und dann if Entscheidung
        with open(template) as f:
            fdata = f.read().split('\n')
        f.close()
        fo = open(template[:-2], 'w')
        for data in fdata:
            if '--workdir' in data:
                data = '#SBATCH --workdir=/scratch/ms/' + c.ecgid + \
                        '/' + c.ecuid
            if '##PBS -o' in data:
                data = '##PBS -o /scratch/ms/' + c.ecgid + '/' + \
                        c.ecuid + 'flex_ecmwf.$Jobname.$Job_ID.out'
            if  'export PATH=${PATH}:' in data:
                data += c.ec_flexpart_root_scripts + '/ECMWFDATA7.1/python'
            if 'cat>>' in data or 'cat >>' in data:
                i = data.index('>')
                fo.write(data[:i] + data[i+1:] + '\n')
                fo.write('GATEWAY ' + c.gateway + '\n')
                fo.write('DESTINATION ' + c.destination + '\n')
                fo.write('EOF\n')

            fo.write(data + '\n')
        fo.close()

        job = ecd + 'python/ECMWF_ENV'
        with open(job, 'w') as fo:
            fo.write('ECUID ' + c.ecuid + '\n')
            fo.write('ECGID ' + c.ecgid + '\n')
            fo.write('GATEWAY ' + c.gateway + '\n')
            fo.write('DESTINATION ' + c.destination + '\n')
        fo.close()



    if target.lower() == 'local':
        # compile CONVERT2
        if c.flexpart_root_scripts is None or c.flexpart_root_scripts == '../':
            print('Warning: FLEXPART_ROOT_SCRIPTS has not been specified')
            print('Only CONVERT2 will be compiled in ' + ecd + '/../src')
        else:
            c.flexpart_root_scripts = os.path.expandvars(os.path.expanduser(
                                        c.flexpart_root_scripts))
            if os.path.abspath(ecd) != os.path.abspath(c.flexpart_root_scripts):
                os.chdir('/')
                p = subprocess.check_call(['tar', '-cvf',
                                           ecd + '../ECMWFDATA7.1.tar',
                                           ecd + 'python',
                                           ecd + 'grib_templates',
                                           ecd + 'src'])
                try:
                    os.makedirs(c.flexpart_root_scripts + '/ECMWFDATA7.1')
                except:
                    pass
                os.chdir(c.flexpart_root_scripts + '/ECMWFDATA7.1')
                p = subprocess.check_call(['tar', '-xvf',
                                           ecd + '../ECMWFDATA7.1.tar'])
                os.chdir(c.flexpart_root_scripts + '/ECMWFDATA7.1/src')

        os.chdir('../src')
        print(('install ECMWFDATA7.1 software on ' + target + ' in directory '
               + os.getcwd()))
        if c.makefile is None:
            makefile = 'Makefile.local.ifort'
        else:
            makefile = c.makefile
        flist = glob.glob('*.mod') + glob.glob('*.o')
        if flist:
            p = subprocess.check_call(['rm'] + flist)
        try:
            print(('Using makefile: ' + makefile))
            p = subprocess.check_call(['make', '-f', makefile])
            p = subprocess.check_call(['ls', '-l','CONVERT2'])
        except:
            print('compile failed - please edit ' + makefile +
                  ' or try another Makefile in the src directory.')
            print('most likely GRIB_API_INCLUDE_DIR, GRIB_API_LIB '
                    'and EMOSLIB must be adapted.')
            print('Available Makefiles:')
            print(glob.glob('Makefile*'))

    elif target.lower() == 'ecgate':
        os.chdir('/')
        p = subprocess.check_call(['tar', '-cvf',
                                   ecd + '../ECMWFDATA7.1.tar',
                                   ecd + 'python',
                                   ecd + 'grib_templates',
                                   ecd + 'src'])
        try:
            p = subprocess.check_call(['ecaccess-file-put',
                                       ecd + '../ECMWFDATA7.1.tar',
                                       'ecgate:/home/ms/' + c.ecgid + '/' +
                                       c.ecuid + '/ECMWFDATA7.1.tar'])
        except:
            print('ecaccess-file-put failed! Probably the eccert key has expired.')
            exit(1)
        p = subprocess.check_call(['ecaccess-job-submit',
                                   '-queueName',
                                   target,
                                   ecd + 'python/compilejob.ksh'])
        print('compilejob.ksh has been submitted to ecgate for '
                'installation in ' + c.ec_flexpart_root_scripts +
                '/ECMWFDATA7.1')
        print('You should get an email with subject flexcompile within '
                'the next few minutes')

    elif target.lower() == 'cca':
        os.chdir('/')
        p = subprocess.check_call(['tar', '-cvf',
                                   ecd + '../ECMWFDATA7.1.tar',
                                   ecd + 'python',
                                   ecd + 'grib_templates',
                                   ecd + 'src'])
        try:
            p = subprocess.check_call(['ecaccess-file-put',
                                       ecd + '../ECMWFDATA7.1.tar',
                                       'cca:/home/ms/' + c.ecgid + '/' +
                                       c.ecuid + '/ECMWFDATA7.1.tar'])
        except:
            print('ecaccess-file-put failed! '
                    'Probably the eccert key has expired.')
            exit(1)

        p=subprocess.check_call(['ecaccess-job-submit',
                                '-queueName',
                                target,
                                ecd + 'python/compilejob.ksh'])
        print('compilejob.ksh has been submitted to cca for installation in ' +
              c.ec_flexpart_root_scripts + '/ECMWFDATA7.1')
        print('You should get an email with subject flexcompile '
                'within the next few minutes')

    else:
        print('ERROR: unknown installation target ', target)
        print('Valid targets: ecgate, cca, local')

    return


if __name__ == "__main__":
    main()
