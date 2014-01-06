#!/usr/bin/env python

import ConfigParser
import os
import sys
import time


def dir_check(dir):
    """ Check for the existence of a given directory.  Return 1 if the
    directory does not exist. """
    status_item('Exists')
    if not os.path.exists(dir):
        status_result('FAIL', 3)
        return 1
    else:
        status_result('PASS', 1)

    status_item('Directory')
    if not os.path.isdir(dir):
        status_result('FAIL', 3)
        return 1
    else:
        status_result('PASS', 1)

def dir_check_make(dir):
    """ Check for the existence of a given directory, and if not found prompt
    the user to create it.  Return 1 if the directory does not exist or the
    user decides not to create it. """
    status_item('Exists')
    if not os.path.exists(dir):
        status_result('NO', 2)
        status_item('Create? (y/n)')
        confirm_create = raw_input()
        if confirm_create == 'y':
            status_item('mkdir ' + dir)
            os.makedirs(dir)
            if os.path.exists(dir):
                status_result('CREATED', 1)
            # no need to verify success here, we do it below
        else:
            return 1
    else:
        status_result('PASS', 1)

    status_item('Directory')
    if not os.path.isdir(dir):
        status_result('FAIL', 3)
        return 1
    else:
        status_result('PASS', 1)

def config_read(config_file):
    """ Read the configuration. """
    if not os.path.isfile(config_file):
        return

    config = ConfigParser.RawConfigParser()
    config.read(config_file)
    config.backup_dir = normalize_dir(config.get('ArchiveR3', 'backup_dir'))
    config.archives = normalize_dir(config.get('ArchiveR3', 'archives'))
    config.data_dir = normalize_dir(config.get('ArchiveR3', 'data_dir'))
    config.log_dir = normalize_dir(config.get('ArchiveR3', 'log_dir'))
    config.stale_age = config.getint('ArchiveR3', 'stale_age')
    config.password_base = config.get('ArchiveR3', 'password_base')
    return config

def config_validate(config):
    """ Make sure that all the configuration settings make sense.  Try to
    be helpful and intervene if there are issues, otherwise bail. """

    status_item('Backup location')
    status_result(config.backup_dir)
    rc = dir_check_make(config.backup_dir)
    if rc:
        return 1

    config.archive_list = config.archives.split()
    for i, s in enumerate(config.archive_list):
        status_item('Archive')
        config.archive_list[i] = normalize_dir(s)
        status_result(config.archive_list[i])
        rc = dir_check(config.archives[i])
        if rc:
            return 1

    status_item('Data location')
    status_result(config.data_dir)
    rc = dir_check_make(config.data_dir)
    if rc:
        return 1

    status_item('Log location')
    status_result(config.log_dir)
    rc = dir_check_make(config.log_dir)
    if rc:
        return 1

    status_item('Password base')
    status_result('****************')

    status_item('Stale age (minutes)')
    status_result(config.stale_age)

    return 0

def normalize_dir(dir):
    """ Add a trailing slash to a directory if none is present.  We need to
    ensure consistency here in order to have pathing work out for rsync calls
    etc. """
    if dir[-1] != '/':
        dir += '/'
    return dir

def print_header(activity):
    """ Display the start time of the activity and return the it for later
    reference. """
    time_init = time.time()
    print '*' * 79
    print
    print 'START: ' + activity + ' - ' + \
        time.strftime("%B %-d, %Y %H:%M:%S", time.localtime(time_init))
    print
    print '*' * 79
    return time_init

def print_footer(activity, time_init):
    time_final = time.time()
    print '*' * 79
    print
    print 'END: ' + activity + ' - ' + \
          time.strftime("%B %-d, %Y %H:%M:%S", time.localtime(time_final))
    print
    status_item('elapsed')
    status_result(str(int(time_final - time_init)) + ' seconds')
    print
    print '*' * 79

def status_item(item):
    sys.stdout.write('%38s: ' % item)

def status_result(result, type=0):
    """ Show the results of the item currently being worked on.  Optionally,
    show a color-coded result based on the type parameter where 0 is normal,
    1 is success (green), 2 is warning (yellow), and 3 is error (red). """
    if type == 0:
        print result
    elif type == 1:
        print '\033[32m' + result + '\033[0m'
    elif type == 2:
        print '\033[33m' + result + '\033[0m'
    elif type == 3:
        print '\033[31m' + result + '\033[0m'
    else:
        print '\033[31mINVALID status_result() type specified\033[0m'
