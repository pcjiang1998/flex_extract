#!/bin/bash
#
# @Author: Anne Philipp
#
# @Date: September, 10 2018
#
# @Description: 
#    This file defines the flex_extract's available installation
#    parameters and puts them together for the call of the actual 
#    python installation script. 
#    It also does some checks to guarantees necessary parameters 
#    were set.
#
# -----------------------------------------------------------------
# AVAILABLE COMMANDLINE ARGUMENTS TO SET
#
# THE USER HAS TO SPECIFY THESE PARAMETERS
#
TARGET='ecgate'
MAKEFILE='Makefile.gfortran'
ECUID='km4a'
ECGID='at'
GATEWAY='srvx8.img.univie.ac.at'
DESTINATION='annep@genericSftp'
INSTALLDIR=None
JOB_TEMPLATE=''
CONTROLFILE='CONTROL_EA5'
# -----------------------------------------------------------------
#
# AFTER THIS LINE THE USER DOES NOT HAVE TO CHANGE ANYTHING !!!
#
# -----------------------------------------------------------------

# PATH TO INSTALLATION SCRIPT
script="source/python/install.py"

# INITIALIZE EMPTY PARAMETERLIST
parameterlist=""

# DEFAULT PARAMETERLIST
if [ -n "$TARGET" ]; then
  parameterlist=" --target=$TARGET"
else
  echo "ERROR: No installation target specified."
  echo "EXIT WITH ERROR"
  exit
fi

# CHECK FOR MORE PARAMETER 
if [ "$TARGET" == "ecgate" ] || [ "$TARGET" == "cca" ]; then
  # check if necessary Parameters are set
  if [ -z "$ECUID" ] || [ -z "$ECGID" ] || [ -z "$GATEWAY" ] || [ -z "$DESTINATION" ]; then
    echo "ERROR: At least one of the following parameters are not set: ECUID, ECGID, GATEWAY, DESTINATION!"
    echo "EXIT WITH ERROR"
    exit
  else
    parameterlist+=" --ecuid=$ECUID --ecgid=$ECGID --gateway=$GATEWAY --destination=$DESTINATION"
  fi
fi
if [ -n "$MAKEFILE" ]; then
  parameterlist+=" --makefile=$MAKEFILE"
fi
if [ -n "$FLEXPARTDIR" ]; then # not empty
  parameterlist+=" --flexpartdir=$FLEXPARTDIR"
fi
if [ -n "$JOB_TEMPLATE" ]; then
  parameterlist+=" --job_template=$JOB_TEMPLATE"
fi
if [ -n "$CONTROLFILE" ]; then
  parameterlist+=" --controlfile=$CONTROLFILE"
fi

# -----------------------------------------------------------------
# CALL INSTALLATION SCRIPT WITH DETERMINED COMMANDLINE ARGUMENTS

$script $parameterlist

