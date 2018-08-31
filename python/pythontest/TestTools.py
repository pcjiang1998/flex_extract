#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
#import unittest
import pytest

sys.path.append('../')
import _config
from tools import init128, to_param_id, my_error, read_ecenv


class TestTools():
    '''
    '''

    def setUp(self):
        pass

    def test_get_cmdline_arguments(self):
        assert True

    def test_init128(self):
        '''
        '''
        table128 = init128(_config.PATH_GRIBTABLE)
        expected = {'078': 'TCLW', '130': 'T', '034': 'SST'}
        # check a sample of parameters which must have been read in
        result = all((k in table128 and table128[k]==v) for k,v in expected.iteritems())
        assert result == True


    def test_to_param_id(self):
        '''
        '''
        table128 = init128(_config.PATH_GRIBTABLE)
        pars = to_param_id("T/SP/LSP/SSHF", table128)
        for par in pars:
            assert par in [130, 134, 142, 146]

    def test_error_notifcation(self):
        '''
        '''
        with pytest.raises(SystemExit) as pytest_wrapped_e:
            my_error(['${USER}', 'anne.philipp@univie.ac.at'], 'Failed!')
        assert pytest_wrapped_e.type == SystemExit
        assert pytest_wrapped_e.value.code == 1

    def test_read_ecenv(self):
        '''
        '''
        envs_ref = {'ECUID': 'km4a',
                    'ECGID': 'at',
                    'GATEWAY': 'srvx8.img.univie.ac.at',
                    'DESTINATION': 'annep@genericSftp'
                   }
        envs = read_ecenv(os.getcwd() + '/TestData/ECMWF_ENV')

        assert envs_ref == envs


    def test_clean_up(self):
        assert True

    def test_normal_exit(self):
        assert True

    def test_product(self):
        assert True

    def test_silent_remove(self):
        assert True


    def test_get_list_as_string(self):
        assert True

    def test_make_dir(self):
        assert True

    def test_put_file_to_ecserver(self):
        assert True

    def submit_job_to_ecserver(self):
        assert True

if __name__ == "__main__":
    unittest.main()
