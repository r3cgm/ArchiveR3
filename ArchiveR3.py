#!/usr/bin/env python

import ConfigParser
import sys
import time


def config_read():
    """ Read the configuration. """
    config = ConfigParser.RawConfigParser()
    config.read('config')
    config.archives = config.get('ArchiveR3', 'archives')
    config.backup_dir = config.get('ArchiveR3', 'backup_dir')
    config.log_dir = config.get('ArchiveR3', 'log_dir')
    config.data_dir = config.get('ArchiveR3', 'data_dir')
    config.stale_age = config.getint('ArchiveR3', 'stale_age')
    config.password_base = config.get('ArchiveR3', 'password_base')
    return config

def print_header(activity):
    """ Display the start time of the activity and return the it for later
    reference. """
    time_init = time.time()
    print '*' * 79
    print
    print 'START: ' + activity + ' - ' + \
        time.strftime("%B %d, %Y %H:%M:%S", time.localtime(time_init))
    print
    print '*' * 79
    return time_init

def print_footer(activity, time_init):
    time_final = time.time()
    print '*' * 79
    print
    print 'END: ' + activity + ' - ' + \
          time.strftime("%B %d, %Y %H:%M:%S", time.localtime(time_final))
    print
    status_item('elapsed')
    status_result(str(int(time_final - time_init)) + ' seconds')
    print
    print '*' * 79

def status_item(item):
    sys.stdout.write('%22s: ' % item)

def status_result(result):
    print result
