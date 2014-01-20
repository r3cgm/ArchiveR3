#!/usr/bin/env python

import ConfigParser
import os
import re
import subprocess
import sys
import time


class Unbuffered:
    """ Provide a means to display stdout without buffering it. """
    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        self.stream.write(data)
        self.stream.flush()

    def __getattr__(self, attr):
        return getattr(self.stream, attr)


def dir_size(dir, block_size=0):
    """ Calculate the size of a directory by recursively adding up the size of
    all files within, recursively.  This does not double-count any symlinks or
    hard links.  Optionally specify a blocksize so that file sizes will be
    padded and more accurately represent actual consumed size on disk. """
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
            if block_size:
                total_size += stat.st_size - (stat.st_size % block_size) + \
                    block_size
            else:
                total_size += stat.st_size

    return total_size


def dir_validate(dir, create=0, write=0, read=0, sudo=0):
    """ Validate that a directory exists.  Optionally specify create=1 to
    prompt the user to create it.  Specify write=1 to create (and remove) a
    test file.  Specify read=1 to read any random file from the directory.
    Specify sudo=1 to perform mkdir operations with root-level privileges.
    Return 1 if no valid directory exists at the end of this function. """
    if not os.path.exists(dir):
        if create:
            status_result('NOT FOUND ', 2)
            status_item('Create? (y/n)')
            confirm_create = raw_input()
            if confirm_create == 'y':
                status_item(dir)
                if sudo:
                    try:
                        subprocess.call(['sudo', 'mkdir', dir])
                    except Exception, e:
                        status_result('ERROR ' + e, 3)
                else:
                    os.makedirs(dir)

                if os.path.exists(dir):
                    status_result('CREATED', 1, no_newline=1)
                else:
                    status_result('CREATION FAILED', 3)
                    return 1
            else:
                status_item(dir)
                status_result('CREATION ABORTED', 3)
                return 1
        else:
            status_item(dir)
            status_result('BAILING', 3)
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

    if not read and not write:
        status_result('FOUND', 1)
    else:
        # make sure we get a newline in
        status_result('')


def lb_exists(file):
    """ Determine if a loopback device has been allocated for a particular
    file.  If found, return it.  If not, return 0.  Note this is opposite
    normal functions where 0 means success. """
    status_item('Container > Loopback Device')
    p1 = subprocess.Popen(['sudo', 'losetup', '--associated', file],
                          stdout=subprocess.PIPE)
    lbmatch = p1.communicate()[0]
    lbmatch = ''.join(lbmatch.split())
    if re.match('.*\(' + file + '\).*', str(lbmatch)):
        lbmatch = re.sub(':.*$', '', lbmatch)
        status_result('ASSOCIATED ' + lbmatch, 1)
        return lbmatch
    else:
        status_result('MISSING', 2)
        return 0
    return 0


def lb_next():
    """ Return the name of the next free loopback device. """
    status_item('Allocate Loopback')
    p1 = subprocess.Popen(['sudo', 'losetup', '-f'], stdout=subprocess.PIPE)
    lbdevice = p1.communicate()[0]
    lbdevice = ''.join(lbdevice.split())
    if lbdevice:
        status_result(lbdevice, 1)
        return lbdevice
    else:
        status_result('FAILED', 3)
        return 0


def lb_setup(lbdevice, file):
    """ Associate a loopback device with a file.  Return 1 if failure or 0
    if successful. """
    status_item('Loopback Setup')
    result = subprocess.Popen(['sudo', 'losetup', lbdevice, file],
                          stderr=subprocess.PIPE).communicate()[0]
    if re.match('.*Loop device is ' + lbdevice + '.*', result):
        status_result(str(file) + ' > ' + lbdevice, 1)
        return 0
    else:
        status_result('FAILED', 3)
        print 'did not match: ' + result
        return 1


def lb_encrypted(lbdevice, password_base, container_file):
    """ Perform tests to determine if the loopback device is a valid
    encrypted container. """
    status_item('Password Test')
    try:
#       p1 = subprocess.Popen('expect -c "spawn sudo tcplay ' +
#                             '-i -d ' + lbdevice + "\n" +
#                             "set timeout 2\n" +
#                             "expect Passphrase\n" +
#                             "send " + password_base +
#                             container_file + '\\r' + "\n" +
#                             "expect Passphrase\n" +
#                             "send " + password_base +
#                             container_file + '\\r' + "\n" +
#                             "expect Passphrase\n" +
#                             "send " + password_base +
#                             container_file + '\\r' + "\n" +
#                             "expect eof\n" +
#                             '"', stdout=subprocess.PIPE, shell=True)

#       p1 = subprocess.Popen('expect -c "spawn sudo tcplay ' +
#                             '-i -d ' + lbdevice + "\n" +
#                             "set timeout 2\n" +
#                             "expect Passphrase\n" +
#                             "send " + password_base +
#                             container_file + '\\r' + "\n" +
#                             "expect eof\n" +
#                             '"', stdout=subprocess.PIPE, shell=True)

        p1 = subprocess.Popen('expect -c "spawn sudo tcplay ' +
                              '-i -d ' + lbdevice + "\n" +
                              "set timeout 2\n" +
                              "expect Passphrase\n" +
                              "send " + password_base +
                              container_file + '\\r' + "\n" +


                              "expect eof\n" +
                              '"', stdout=subprocess.PIPE, shell=True)

# put this inside the whitespace gap above
# failure condition
#                             "expect Passphrase\n" +
#                             "send " + password_base +
#                             container_file + '\\r' + "\n" +
#                             "expect Passphrase\n" +
#                             "send " + password_base +
#                             container_file + '\\r' + "\n" +

        result = p1.communicate()[0]
        print 'result ' + result
        if re.match(r'.*Incorrect password or not a TrueCrypt volume.*',
                    result, re.DOTALL):
            status_result('INCORRECT OR NOT A VALID VOLUME', 3)
            return 1
        else:
            # TODO - this condition will need to be flushed out more once
            # we have a legit encrypted volume
            status_result('SUCCESS', 1)
    except subprocess.CalledProcessError, e:
        status_result('FAILURE')
        status_item('Map Command')
        status_result('ERROR', 3)
        return 1
    except Exception, e:
        status_result('FAILURE')
        status_item('Map Command')
        status_result('NOT FOUND', 3)
        return 1

    status_item('Non-0 File Test')
    # TODO - return here when ready to test a valid archive


def lb_encrypt(lbdevice, password_base, container_file):
    """ Encrypt a loopback device. """
    status_item('Encrypting Volume')
    try:
        p1 = subprocess.Popen('expect -c "spawn sudo tcplay ' +
                              '-c -d ' + lbdevice + ' ' +
                              '-a whirlpool -b AES-256-XTS' + "\n" +
                              "set timeout 2\n" +
                              "expect Passphrase\n" +
                              "send " + password_base +
                              container_file + '\\r' + "\n" +
                              "expect Repeat\n" +
                              "send " + password_base +
                              container_file + '\\r' + "\n" +
                              'expect proceed' + "\n" +
                              'send y' + '\\r' + "\n" +
                              'interact' + "\n" +
                              '"', stdout=subprocess.PIPE, shell=True)
        result = p1.communicate()[0]
        print 'result: ' + result
# TODO
#       if re.match(r'.*Incorrect password or not a TrueCrypt volume.*',
#                   result, re.DOTALL):
#           status_result('INCORRECT OR NOT A VALID VOLUME', 3)
#           return 1
#       else:
#           # TODO - this condition will need to be flushed out more once
#           # we have a legit encrypted volume
#           status_result('SUCCESS', 1)

    except subprocess.CalledProcessError, e:
        status_result('FAILURE')
        status_item('Encrypt Command')
        status_result('ERROR', 3)
        return 1
    except Exception, e:
        status_result('FAILURE')
        status_item('Encrypt Command')
        status_result('NOT FOUND', 3)
        return 1



def config_read(config_file):
    """ Read the configuration. """
    if not os.path.isfile(config_file):
        return

    config = ConfigParser.RawConfigParser()
    config.read(config_file)
    config.backup_dir = normalize_dir(config.get('ArchiveR3', 'backup_dir'))
    config.mount_dir = normalize_dir(config.get('ArchiveR3', 'mount_dir'))
    config.archives = normalize_dir(config.get('ArchiveR3', 'archives'))
    config.data_dir = normalize_dir(config.get('ArchiveR3', 'data_dir'))
    config.log_dir = normalize_dir(config.get('ArchiveR3', 'log_dir'))
    config.password_base = config.get('ArchiveR3', 'password_base')
    config.stale_age = config.getint('ArchiveR3', 'stale_age')
    config.provision_capacity_percent = \
        config.getint('ArchiveR3', 'provision_capacity_percent')
    config.provision_capacity_reprovision = \
        config.getint('ArchiveR3', 'provision_capacity_reprovision')
    return config


def config_validate(config):
    """ Make sure that all the configuration settings make sense.  Try to
    be helpful and intervene if there are issues, otherwise bail. """

    status_item('Containers ' + config.backup_dir)
    rc = dir_validate(config.backup_dir, create=1, write=1)
    if rc:
        return 1

    status_item('Container Mounts ' + config.mount_dir)
    rc = dir_validate(config.mount_dir)
    if rc:
        return 1

    status_item('Data ' + config.data_dir)
    rc = dir_validate(config.data_dir, create=1, write=1)
    if rc:
        return 1

    status_item('Logging ' + config.log_dir)
    rc = dir_validate(config.log_dir, create=1, write=1)
    if rc:
        return 1

    status_item('Password base')
    status_result('****************')

    status_item('Stale age (minutes)')
    status_result(str(config.stale_age) + ' !UNUSED!')

    status_item('Provision Capacity')
    status_result(str(config.provision_capacity_percent) + '%')

    status_item('Reprovision Capacity')
    status_result(str(config.provision_capacity_reprovision) + '%')

    devnull = open('/dev/null', 'w')

    status_item('dd')
    try:
        subprocess.check_call(['dd', '--version'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('ERROR', 3)
        return 1
    except Exception, e:
        status_result('NOT FOUND', 3)
        return 1
    status_result('FOUND', 1)

    status_item('expect')
    try:
        subprocess.check_call(['expect', '-v'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('ERROR', 3)
        return 1
    except Exception, e:
        status_result('NOT FOUND (install package "expect")', 3)
        return 1
    status_result('FOUND', 1)

    status_item('(sudo) losetup')
    try:
        subprocess.check_call(['sudo', 'losetup', '-h'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('ERROR', 3)
        return 1
    except Exception, e:
        status_result('NOT FOUND', 3)
        return 1
    status_result('FOUND', 1)

    status_item('(sudo) mkdir')
    try:
        subprocess.check_call(['sudo', 'mkdir', '--help'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('ERROR', 3)
        return 1
    except Exception, e:
        status_result('NOT FOUND', 3)
        return 1
    status_result('FOUND', 1)

    status_item('pv')
    try:
        subprocess.check_call(['pv', '--version'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('ERROR', 3)
        return 1
    except Exception, e:
        status_result('NOT FOUND (install package "pv")', 3)
        return 1
    status_result('FOUND', 1)

    status_item('(sudo) tcplay')
    try:
        subprocess.check_call(['sudo', 'tcplay', '-v'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('ERROR', 3)
        return 1
    except Exception, e:
        status_result('NOT FOUND (install package "tcplay")', 3)
        return 1
    status_result('FOUND', 1)

    config.archive_list = config.archives.split()
    for i, s in enumerate(config.archive_list):
        config.archive_list[i] = normalize_dir(s)
        status_item('Archive ' + config.archive_list[i])
        rc = dir_validate(config.archive_list[i], read=1)
        if rc:
            return 1

    return 0


def normalize_dir(dir):
    """ Add a trailing slash to a directory if none is present.  We need to
    ensure consistency here in order to have pathing work out for rsync calls
    etc. """
    if dir[-1] != '/':
        dir += '/'
    return dir


def map_container(lbdevice, container_file, password_base):
    """ Map an encrypted container as a loopback device. """
    status_item('Map container mount? (y/n)')
    confirm_mount_map = raw_input()
    if confirm_mount_map == 'y':

        try:
            print
            subprocess.check_call('expect -c "spawn sudo tcplay ' +
                                  '-m ' + container_file + ' ' +
                                  '-d ' + lbdevice + "\n" +
                                  "set timeout 1\n" +
                                  "expect Passphrase\n" +
                                  "send " + password_base +
                                  container_file + "\r" + "\n" +
                                  "expect eof\n" +
                                  '"', shell=True)
            print
            print
        except subprocess.CalledProcessError, e:
            status_item('Map Command')
            status_result('ERROR', 3)
            return 1
        except Exception, e:
            status_item('Map Command')
            status_result('NOT FOUND', 3)
            return 1

        status_item('Map /dev/mapper/' + container_file)
        if os.path.isdir('/dev/mapper/' + container_file):
            status_result('FOUND', 1)
        else:
            status_result('FAILED', 3)
            status_item('Container')
            status_result('POSSIBLE CORRUPTION', 3)
            status_item('')
            status_result('debug manually or rm ' + container_file)
            status_item('')
            status_result('and let this utility recreate it')
            return 1

    else:
        status_item('Device Mount')
        status_result('BAILING', 3)
        return 1


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
    status_item('Elapsed Time')
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
