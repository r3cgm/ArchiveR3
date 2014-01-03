#!/usr/bin/env python

import ConfigParser
import os
import sys
import time


def config_read():
    """ Read the configuration. """
    config = ConfigParser.RawConfigParser()
    config.read('config')

    config.archives = config.get('ArchiveR3', 'archives')

    config.backup_dir = config.get('ArchiveR3', 'backup_dir')
    config.backup_dir = normalize_dir(config.backup_dir)

    config.log_dir = config.get('ArchiveR3', 'log_dir')
    config.data_dir = config.get('ArchiveR3', 'data_dir')
    config.stale_age = config.getint('ArchiveR3', 'stale_age')
    config.password_base = config.get('ArchiveR3', 'password_base')

    return config

def config_validate(config):
    """ Make sure that all the configuration settings make sense.  Try to
    be helpful and intervene if there are issues, otherwise bail. """

    status_item('Backup location')
    status_result(config.backup_dir)

    status_item('Exists')
    if not os.path.exists(config.backup_dir):
        status_result('NO', 2)
        status_item('Create? (y/n)')
        confirm_create = raw_input()
        if confirm_create == 'y':
            status_item('mkdir ' + config.backup_dir)
            os.makedirs(config.backup_dir)
            if os.path.exists(config.backup_dir):
                status_result('CREATED', 1)
        else:
            return 1
    else:
        status_result('PASS', 1)

    status_item('Directory')
    if not os.path.isdir(config.backup_dir):
        status_result('NO', 2)
        return 1
    else:
        status_result('PASS', 1)


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
