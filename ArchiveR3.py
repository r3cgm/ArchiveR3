#!/usr/bin/env python

import ConfigParser
import os
import sys
import time


def dir_size(dir):
    """ Calculate the size of a directory by recursively adding up the size of
    all files within, recursively.  This does not double-count any symlinks or
    hard links. """
    total_size = 0
    seen = {}
    for dirpath, dirnames, filenames in os.walk(dir):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                stat = os.stat(fp)
            except OSError:
                continue

            try:
                seen[stat.st_ino]
            except KeyError:
                seen[stat.st_ino] = True
            else:
                continue
            total_size += stat.st_size

    return total_size


def dir_validate(dir, create=0, write=0, read=0):
    """ Validate that a directory exists.  Optionally specify create=1 to
    prompt the user to create it.  Specify write=1 to create (and remove) a
    test file.  Specify read=0 to read any random file from the directory.
    Return 1 if no valid directory exists at the end of this function. """
    if not os.path.exists(dir):
        if create:
            status_result('NOT FOUND ', 2)
            status_item('Create? (y/n)')
            confirm_create = raw_input()
            if confirm_create == 'y':
                status_item(dir)
                os.makedirs(dir)
                if os.path.exists(dir):
                    status_result('CREATED', 1, no_newline=1)
                else:
                    status_result('FAILED', 3)
                    return 1

    if not os.path.isdir(dir):
        status_result('NOT A DIRECTORY', 3)
        return 1

    if write:
        test_file = '.ArchiveR3-write-test'
        if os.path.exists(dir + test_file):
            status_result('CRUFT', 3)
            status_item('')
            status_result('REMOVE MANUALLY', 2)
            status_item('')
            status_result(dir + test_file, 2)
            return 1
        file = open(dir + test_file, 'w')
        file.write('test write')
        file.close()
        if os.path.isfile(dir + test_file):
            os.remove(dir + test_file)
            status_result('WRITEABLE', 1, no_newline=1)
        else:
            status_result('NOT WRITEABLE', 3)
            return 1

    if read:
        for root, dirs, files in os.walk(dir):
            for filename in files:
                file = open(dir + filename, 'r')
                test_byte = file.read(1)
                if test_byte:
                    status_result('READABLE', 1, no_newline=1)
                else:
                    status_result('NOT READABLE', 3)
                    return 1
                break

    status_result('')


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

    status_item(config.backup_dir)
    rc = dir_validate(config.backup_dir, create=1, write=1)
    if rc:
        return 1

    config.archive_list = config.archives.split()
    for i, s in enumerate(config.archive_list):
        config.archive_list[i] = normalize_dir(s)
        status_item(config.archive_list[i])
        rc = dir_validate(config.archive_list[i], read=1)
        if rc:
            return 1

    status_item(config.data_dir)
    rc = dir_validate(config.data_dir, create=1, write=1)
    if rc:
        return 1

    status_item(config.log_dir)
    rc = dir_validate(config.log_dir, create=1, write=1)
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


def section_break():
    print '-' * 79


def status_item(item):
    sys.stdout.write('%38s: ' % item)


def status_result(result, type=0, no_newline=0):
    """ Show the results of the item currently being worked on.  Optionally,
    show a color-coded result based on the type parameter where 0 is normal,
    1 is success (green), 2 is warning (yellow), and 3 is error (red). """
    if type == 0:
        print result,
    elif type == 1:
        print '\033[32m' + result + '\033[0m',
    elif type == 2:
        print '\033[33m' + result + '\033[0m',
    elif type == 3:
        print '\033[31m' + result + '\033[0m',
    else:
        print '\033[31mINVALID status_result() type specified\033[0m',

    if not no_newline:
        print
