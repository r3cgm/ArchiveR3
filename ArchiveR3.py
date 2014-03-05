#!/usr/bin/env python

import ConfigParser
try:
    from hurry.filesize import size
except ImportError, e:
    print e
    print 'Hint: try running "pip install hurry.filesize"'
    sys.exit(1)
import os
import re
import shlex, subprocess
import struct
import subprocess
import sys
# import threading
import time
from threading import Thread

# https://stackoverflow.com/questions/375427/non-blocking-read-on-a-subprocess-pipe-in-python
try:
    from Queue import Queue, Empty
except ImportError:
    from queue import Queue, Empty  # python 3.x

ON_POSIX = 'posix' in sys.builtin_module_names


class Unbuffered:
    """ Provide a means to display stdout without buffering it. """
    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        self.stream.write(data)
        self.stream.flush()

    def __getattr__(self, attr):
        return getattr(self.stream, attr)


def enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)


def dir_size(dir, block_size=0):
    """ Calculate the size of a directory by recursively adding up the size of
    all files within, recursively.  This does not double-count any symlinks or
    hard links.  Optionally specify a blocksize so that file sizes will be
    padded and more accurately represent actual consumed size on disk.
    If blocksize is specified directories will be tabulated as well, assuming
    they consume 1 block.  Return -1 if any files or directories are not
    readable. """
    total_size = 0
    file_count = 0
    dir_count = 0
    seen = {}
    status_item('Sizing ' + dir)
    for dirpath, dirnames, filenames in os.walk(dir):
        for f in filenames:
            file_count += 1
            if file_count % 1000 == 0:
                status_result('.', no_newline=True)
            fp = os.path.join(dirpath, f)
            try:
                stat = os.stat(fp)
            except OSError:
                continue

            # TODO
            # os.access() is unreliable.  There is at least one edge case where
            # a remote mounted CIFS share which appears to have readable
            # permissions (by looking at 'ls' output) actually fails to open
            # due to remote-side ownership issues:
            #
            # IOError: [Errno 13] Permission denied:
            # '/mnt/remotedir/somefile'
            #
            # Unfortunately, the only recourse here is to perform direct open
            # attempts on every single file.

#           if not os.access(fp, os.R_OK):
#               status_result('PERMISSION DENIED ' + fp, 3)
#               return -1
            try:
                fh = open(fp, "r")
                fh.close()
            except IOError as e:
                status_result('PERMISSION DENIED ' + fp, 3)
                return -1
            except:
                status_result('UNEXPECTED ERROR' + sys.exc_info()[0], 3)
                return -1

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

        for d in dirnames:
            dp = os.path.join(dirpath, d)
            # TODO: change a CIFS remote dir to some bogus ownership, rendering
            # some particular directory technically unreadable but looking like
            # it should be based on 'ls' output, then verify the os.access()
            # function fails on it.  If necessary rewrite this routine like
            # the one above for handling unreadable files.
            if not os.access(dp, os.R_OK):
                status_result('PERMISSION DENIED /' + dp, 3)
                return -1
            if block_size:
                dir_count += 1
                total_size += block_size

    status_result('')
    status_item('')
    status_result('DONE', 1, no_newline=True)
    status_result('files ' + str(file_count) + ' dirs ' + str(dir_count))
    status_item('')
    status_result('size ' + str(total_size) + ' (' + size(total_size) + ')')
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
            if raw_input() == 'y':
                status_item(dir)
                if sudo:
                    try:
                        subprocess.call(['sudo', 'mkdir', dir])
                    except Exception, e:
                        status_result('ERROR ' + e, 3)
                else:
                    os.makedirs(dir)

                if os.path.exists(dir):
                    status_result('CREATED', 1, no_newline=True)
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
            status_result('WRITEABLE', 1, no_newline=True)
        else:
            status_result('NOT WRITEABLE', 3)
            return 1

    if read:
        read_proved = False

        def dir_error(error):
            print 'error ' + str(error)
            return 1

        for root, dirs, files in os.walk(dir):
            if files:
                for filename in files:
                    file = open(root + '/' + filename, 'r')
                    test_byte = file.read(1)
                    if test_byte:
                        read_proved = True
                        status_result('READABLE', 1, no_newline=True)
                    else:
                        status_result('NOT READABLE', 3)
                        return 1
                    break
                break
        if not read_proved:
            status_result('NO FILES FOUND', 3)
            return 1

    if not read and not write:
        status_result('FOUND', 1)
    else:
        # make sure we get a newline in
        status_result('')


def loopback_exists(file):
    """ Determine if a loopback device has been allocated for a particular
    file.  If found, return it.  If not, return 0.  Note this is opposite
    normal functions where 0 means success. """
#   lbmatch = subprocess.Popen(['sudo', 'losetup', '--associated', file],
#                              stdout=subprocess.PIPE).communicate()[0]
    # stderr prints 'SOMEFILE: No such file or directory' if not found
    # TODO: verify trapping stderr here works
    lbmatch = subprocess.Popen(['sudo', 'losetup', '--associated', file],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE).communicate()[0]
    lbmatch = ''.join(lbmatch.split())
    if re.match('.*\(' + file + '\).*', str(lbmatch)):
        lbmatch = re.sub(':.*$', '', lbmatch)
        status_item('Container > Loopback Device')
        status_result('ASSOCIATED ' + lbmatch, 1)
        return lbmatch


def loopback_cleanup(file):
    """ Attempt to clean up any residual loopback devices associated with a
    particular file which are not in use. """
#   matches = subprocess.Popen(['sudo', 'losetup', '--all'],
#                              stdout=subprocess.PIPE).communicate()[0]
    # stderr prints 'SOMEFILE: No such file or directory' if not found
    # TODO: verify trapping stderr here works
    matches = subprocess.Popen(['sudo', 'losetup', '--all'],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE).communicate()[0]
    for match in str(matches).splitlines():
        if re.match('.*\(' + file + '\)', match):
            loopback_old = re.sub(':.*$', '', match)
            status_item('Removing Old Loopback Device')
            subprocess.Popen(['sudo', 'losetup', '-d', loopback_old])
            status_result(loopback_old, 4)


def loopback_next():
    """ Return the name of the next free loopback device. """
    result = subprocess.Popen(['sudo', 'losetup', '-f'],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT).communicate()[0]
    if re.match('.*could not find any free loop device.*', result):
        status_item('Allocate Loopback')
        status_result('NO FREE DEVICES', 3)
        return
    elif result:
        return result.strip()


def loopback_setup(lbdevice, file):
    """ Associate a loopback device with a file.  Return 1 if failure or 0
    if successful. """
    status_item(lbdevice)
    result = subprocess.Popen(['sudo', 'losetup', '--verbose', lbdevice, file],
                              stdout=subprocess.PIPE).communicate()[0]
    if re.match('.*Loop device is ' + str(lbdevice) + '.*', result):
        status_result('LOOPBACKED', 4)
        return 0
    else:
        status_result('FAILED', 3)
        print 'did not match: ' + result
        return 1


def loopback_delete(lbdevice):
    """ Delete the specified loopback device. """
    status_item(lbdevice)
    try:
        subprocess.check_call(['sudo', 'losetup', '--detach', lbdevice])
    except subprocess.CalledProcessError, e:
        status_result('LOOPBACK DEALLOCATION ERROR')
        return 1
    except Exception, e:
        status_result('LOOPBACK DEALLOCATION NOT FOUND')
        return 1
    status_result('UNLOOPBACKED', 4)


def loopback_encrypted(lbdevice, password_base, backup_dir, container_file,
                       verbose=False):
    """ Perform tests to determine if the loopback device is a valid
    encrypted container. """
    status_item('Container Integrity')
    sum = 0
    file = open(backup_dir + container_file, 'rb')
    count = 0
    integer = struct.unpack('i', file.read(4))[0]
    while integer and count < 100000:
        sum += integer
        integer_file = file.read(4)
        integer_file = '\0' * (4 - len(integer_file)) + integer_file
        integer = struct.unpack('i', integer_file)[0]
        count += 1
    file.close()
    if sum:
        status_result('BINARY,', 1, no_newline=True)
    else:
        status_result('INVALID', 2)
        return 1

    try:
        p1 = subprocess.Popen('expect -c "spawn sudo tcplay ' +
                              '-i -d ' + lbdevice + "\n" +
                              "set timeout 5\n" +
                              "expect Passphrase\n" +
                              "send " + password_base +
                              container_file + '\\r' + "\n" +
                              "expect eof\n" +
                              '"', stdout=subprocess.PIPE, shell=True)
        result = p1.communicate()[0]
        if re.match(r'.*Incorrect password or not a TrueCrypt volume.*',
                    result, re.DOTALL):
            status_result('BAD PASSWORD / CORRUPTED', 3)
            return 1
        elif re.match('.*PBKDF2.*', result, re.DOTALL):
            status_result('PASSWORD VERIFIED', 1)
            if verbose:
                print
                print result
        else:
            status_result('UNKNOWN PASSWORD CONDITION', 3)
            return 1
    except subprocess.CalledProcessError, e:
        status_result('PASSWORD FAILURE')
        status_item('Map Command')
        status_result('ERROR', 3)
        return 1
    except Exception, e:
        status_result('FAILURE')
        status_item('Map Command')
        status_result('NOT FOUND', 3)
        return 1


def loopback_encrypt(lbdevice, password_base, container_file, verbose=False):
    """ Encrypt a loopback device. """
    status_item('Encrypting Volume')
    try:
        cmd = 'expect -c "spawn sudo tcplay ' + \
              '-c -d ' + lbdevice + ' ' + \
              '-a whirlpool -b AES-256-XTS' + "\n" + \
              "set timeout -1\n" + \
              "expect Passphrase\n" + \
              "send " + password_base + \
              container_file + '\\r' + "\n" + \
              "expect Repeat\n" + \
              "send " + password_base + \
              container_file + '\\r' + "\n" + \
              'expect proceed' + "\n" + \
              'send y' + '\\r' + "\n" + \
              'expect done' + "\n" + \
              "expect eof\n" + '"'

        p1 = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE)

        q = Queue()
        t = Thread(target=enqueue_output, args=(p1.stdout, q))
        t.daemon = True # thread dies with the program
        t.start()

        iter = 0

        # Give tcplay a chance to get going before we start SIGUSR1'ing it.
        time.sleep(0.5)
        print
        print
        while p1.poll() is None:
            if iter % 100 == 0:
                subprocess.Popen(
                    'sudo killall tcplay --signal SIGUSR1',
                    stderr=subprocess.PIPE, shell=True)

            try:
                line = q.get(timeout=0.1) # or q.get(timeout=.1)
            except Empty:
                pass # no output
            else:
                print '>>> ' + line.rstrip()
            iter += 1
            if iter > 99:
                iter = 0
        print
        t.join()

    except subprocess.CalledProcessError, e:
        status_result('ENCRYPT ERROR', 3)
        return 1
    except Exception, e:
        status_result('ENCRYPT NOT FOUND ' + str(e), 3)
        return 1
    status_result('ENCRYPTED', 4)


def config_read(config_file):
    """ Read the configuration.  Return a ConfigParser object on success or
    nothing on failure. """
    status_item('Config \'' + config_file + '\'')

    if not os.path.isfile(config_file):
        status_result('NOT FOUND', 3)
        return

    config = ConfigParser.RawConfigParser()

    try:
        config.read(config_file)
    except ConfigParser.ParsingError, e:
        status_result('PARSE ERROR', 3)
        print
        print str(e)
        print
        return

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
    status_result('LOADED', 1)
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

    status_item('Password Base')
    if config.password_base:
        status_result('FOUND', 1)
    else:
        status_result('MISSING', 3)

    status_item('Stale age (minutes)')
    status_result(str(config.stale_age) + ' !UNUSED!')

    status_item('Provision Capacity')
    status_result(str(config.provision_capacity_percent) + '%')

    status_item('Reprovision Capacity')
    status_result(str(config.provision_capacity_reprovision) + '%')

    devnull = open('/dev/null', 'w')

    status_item('Dependencies (* = sudo)')
    try:
        subprocess.check_call(['dd', '--version'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('dd ERROR', 3)
        return 1
    except Exception, e:
        status_result('dd MISSING', 3)
        return 1
    status_result('dd', 1, no_newline=True)

    try:
        subprocess.check_call(['sudo', 'dmsetup', '-h'], stderr=devnull)
    except subprocess.CalledProcessError, e:
        status_result('*dmsetup ERROR', 3)
        return 1
    except Exception, e:
        status_result('*dmsetup MISSING', 3)
        return 1
    status_result('*dmsetup', 1, no_newline=True)

    try:
        subprocess.check_call(['sudo', 'e2fsck'], stderr=devnull)
    except subprocess.CalledProcessError, e:
        if re.match('.*returned non-zero exit status 16.*', str(e)):
            status_result('*e2fsck', 1, no_newline=True)
        else:
            status_result('*e2fsck ERROR', 3)
            return 1
    except Exception, e:
        status_result('*e2fsck MISSING', 3, no_newline=True)
        return 1

    try:
        subprocess.check_call(['expect', '-v'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('expect ERROR', 3)
        return 1
    except Exception, e:
        status_result('expect MISSING', 3)
        return 1
    status_result('expect', 1, no_newline=True)

    try:
        subprocess.check_call(['sudo', 'killall', '--version'], stderr=devnull)
    except subprocess.CalledProcessError, e:
        status_result('*killall ERROR', 3)
        return 1
    except Exception, e:
        status_result('*killall MISSING', 3)
        return 1
    status_result('*killall', 1)

    status_item('')

    try:
        subprocess.check_call(['sudo', 'losetup', '-h'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('*losetup ERROR', 3)
        return 1
    except Exception, e:
        status_result('*losetup MISSING', 3)
        return 1
    status_result('*losetup', 1, no_newline=True)

    try:
        subprocess.check_call(['sudo', 'mkdir', '--help'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('*mkdir ERROR', 3)
        return 1
    except Exception, e:
        status_result('*mkdir MISSING', 3)
        return 1
    status_result('*mkdir', 1, no_newline=True)

    try:
        subprocess.check_call(['sudo', 'mkfs.ext4', '-V'], stderr=devnull)
    except subprocess.CalledProcessError, e:
        status_result('*mkfs.ext4 ERROR', 3)
        return 1
    except Exception, e:
        status_result('*mkfs.ext4 MISSING', 3)
        return 1
    status_result('*mkfs.ext4', 1, no_newline=True)

    try:
        subprocess.check_call(['sudo', 'mount'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('*mount ERROR', 3)
        return 1
    except Exception, e:
        status_result('*mount MISSING', 3)
        return 1
    status_result('*mount', 1)

    status_item('')

    try:
        subprocess.check_call(['sudo', 'mountpoint', '/'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('*mountpoint ERROR', 3)
        return 1
    except Exception, e:
        status_result('*mountpoint MISSING', 3)
        return 1
    status_result('*mountpoint', 1, no_newline=True)

    try:
        subprocess.check_call(['pv', '--version'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('pv ERROR', 3)
        return 1
    except Exception, e:
        status_result('pv MISSING', 3)
        return 1
    status_result('pv', 1, no_newline=True)

    try:
        subprocess.check_call(['sudo', 'rsync', '--version'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('*rsync ERROR', 3)
        return 1
    except Exception, e:
        status_result('*rsync MISSING', 3)
        return 1
    status_result('*rsync', 1, no_newline=True)

    try:
        subprocess.check_call(['sudo', 'tcplay', '-v'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('*tcplay ERROR', 3)
        return 1
    except Exception, e:
        status_result('*tcplay MISSING', 3)
        return 1
    status_result('*tcplay', 1, no_newline=True)

    try:
        subprocess.check_call(['sudo', 'umount', '-h'], stdout=devnull)
    except subprocess.CalledProcessError, e:
        status_result('*umount ERROR', 3)
        return 1
    except Exception, e:
        status_result('*umount MISSING', 3)
        return 1
    status_result('*umount', 1)

    config.archive_list = config.archives.split()
    for i, s in enumerate(config.archive_list):
        config.archive_list[i] = normalize_dir(s)
        status_item('Archive ' + config.archive_list[i])
        rc = dir_validate(config.archive_list[i], read=1)
        if rc:
            return 1


def normalize_dir(dir):
    """ Add a trailing slash to a directory if none is present.  We need to
    ensure consistency here in order to have pathing work out for rsync calls
    etc. """
    if dir[-1] != '/':
        dir += '/'
    return dir


def mapper_check(lbdevice, archive_map, container_file, password_base,
                 verbose=False):
    """ Verify we have a container mapping and offer to create one if not. """
    status_item(archive_map)
    if os.path.islink('/dev/mapper/' + container_file):
        status_result('FOUND MAP', 1)
    else:
        if mapper_container(lbdevice, container_file, password_base, verbose):
            return 1


def mount_check(archive_map, archive_mount):
    """ Determine if the directory where an encrypted container will be
    mounted exists. """
    status_item('Mount Point ' + archive_mount)
    if dir_validate(archive_mount, create=True, sudo=True):
        return 1

    status_item('Mount Check')
    p1 = subprocess.Popen(['sudo', 'mountpoint', archive_mount],
                          stdout=subprocess.PIPE)
    result = p1.communicate()[0]
    if re.match('.*' + archive_mount + ' is a mountpoint.*', str(result)):
        status_result('MOUNTED', 1)
        return
    else:
        try:
            subprocess.check_call(['sudo', 'mount',
                                  archive_map, archive_mount])
        except subprocess.CalledProcessError, e:
            status_result('MOUNT ERROR', 3)
            return 1
        except Exception, e:
            status_result('MOUNT NOT FOUND', 3)
            return 1
        status_result('MOUNTED', 4)


def umount(mount_point):
    """ Perform an umount operation to release a filesystem, typically during
    cleanup.  Operation is performed via sudo.  Return 1 if problems. """
    devnull = open('/dev/null', 'w')
    try:
        subprocess.check_call(['sudo', 'umount', mount_point], stderr=devnull)
    except subprocess.CalledProcessError, e:
        if re.match('.* returned non-zero exit status 1', str(e)):
            # Not mounted.
            return
        status_item(mount_point)
        status_result('ERROR UNMOUNTING', 3)
        return 1
    except Exception, e:
        status_item(mount_point)
        status_result('UNMOUNT COMMAND MISSING', 3)
        return 1
    status_item(mount_point)
    status_result('UNMOUNTED', 4)


def unmap(container_file):
    """ Unmap a dm-crypt volume. """
    if not os.path.islink('/dev/mapper/' + container_file):
        return 0

    status_item('/dev/mapper/' + container_file)
    try:
        subprocess.check_call(['sudo', 'dmsetup', 'remove', container_file])
    except subprocess.CalledProcessError, e:
        status_result('ERROR UNMAPPING', 3)
        return 1
    except Exception, e:
        status_result('UNMAP COMMAND MISSING', 3)
    status_result('UNMAPPED', 4)


def mapper_container(lbdevice, container_file, password_base, verbose=False):
    """ Map an encrypted container as a loopback device. """
    try:
        result = subprocess.Popen('expect -c "spawn sudo tcplay ' +
                                  '-m ' + container_file + ' ' +
                                  '-d ' + lbdevice + "\n" +
                                  "set timeout -1\n" +
                                  "expect Passphrase\n" +
                                  "send " + password_base +
                                  container_file + '\\r' + "\n" +
                                  "expect All\n" +
                                  "expect eof\n" +
                                  '"', stdout=subprocess.PIPE,
                                  shell=True).communicate()[0]
        if verbose:
            print
            print result

    except subprocess.CalledProcessError, e:
        status_result('COMMAND ERROR ' + str(e), 3)
        return 1
    except Exception, e:
        status_result('COMMAND NOT FOUND ' + str(e), 3)
        return 1

    if os.path.islink('/dev/mapper/' + container_file):
        status_result('MAPPED', 4)
    else:
        status_result('MAPPING FAILURE', 3)
        status_item('')
        status_result('POSSIBLE CORRUPTION', 3)
        status_item('')
        status_result('debug manually or rm ' + container_file)
        status_item('')
        status_result('and let this utility recreate it')
        return 1


def filesystem_check(archive_map):
    """ Verify the integrity of an ext4 filesystem within an encrypted
    container. """
    status_item('Filesystem Check')
    devnull = open('/dev/null', 'w')
    try:
        subprocess.check_call(['sudo', 'e2fsck', '-n', archive_map],
                              stdout=devnull, stderr=devnull)
    except subprocess.CalledProcessError, e:
        if re.match('.*status 8.*', str(e)):
            status_result('FILESYSTEM INVALID', 2)
            return 1
    except Exception, e:
        print 'error ' + str(e)
        status_result('COMMAND NOT FOUND', 3)
        return 1
    status_result('VALID', 1)


def filesystem_format(archive_map, verbose=False):
    """ Create an ext4 filesystem on a mapped device. """
    status_item('Filesystem Create')
    try:
        p1 = subprocess.Popen(['sudo', 'mkfs.ext4', archive_map],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        result = p1.communicate()[0]
        print
        print result
    except subprocess.CalledProcessError, e:
        status_result('FORMAT ERROR ' + str(e), 3)
        return 1
    except Exception, e:
        status_result('FORMAT COMMAND NOT FOUND ' + str(e), 3)
        return 1
    status_result('FORMAT SUCCESS', 1)


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


def sync(source, target):
    """ Synchronize files from a source to a target location. """
    status_item('Sync')
    try:
        p1 = subprocess.Popen('sudo rsync ' +
                              '--bwlimit 1300 ' +
                              '--compress ' +
                              '--recursive ' +
                              '--links ' +
                              '--perms ' +
                              '--times ' +
                              '--group ' +
                              '--owner ' +
                              '--partial ' +
                              '--verbose ' +
                              '--progress ' +
                              '--delete ' +
                              '--delete-delay ' +
                              '--max-delete=100 ' +
                              '--human-readable ' +
                              '--itemize-changes ' +
                              source.rstrip('/') + ' ' + target, shell=True,
                              stdout=subprocess.PIPE)
        print
        print
        for line in iter(p1.stdout.readline, ''):
            print(">>> " + line.rstrip())
        print
    except subprocess.CalledProcessError, e:
        status_result('ERROR', 3)
        return 1
    except Exception, e:
        status_result('NOT FOUND', 3)
        return 1
    status_item('')
    status_result('SUCCESS', 1)


def status_result(result, type=0, no_newline=False):
    """ Show the results of the item currently being worked on.  Optionally,
    show a color-coded result based on the type parameter where 0 is normal,
    1 is success (green), 2 is warning (yellow), 3 is error (red), and 4 is
    success with action taken (blue). """
    if type == 0:
        print result,
    elif type == 1:
        print '\033[32m' + result + '\033[0m',
    elif type == 2:
        print '\033[33m' + result + '\033[0m',
    elif type == 3:
        print '\033[31m' + result + '\033[0m',
    elif type == 4:
        print '\033[34m' + result + '\033[0m',
    else:
        print '\033[31mINVALID status_result() type specified\033[0m',

    if not no_newline:
        print
