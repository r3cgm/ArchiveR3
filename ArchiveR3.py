#!/usr/bin/env python

# System libraries
import logging
import re
import shlex
import struct
import subprocess
import sys
import time
from threading import Thread

# Additional libraries
import ConfigParser
try:
    from hurry.filesize import size
except ImportError, e:
    print e
    print 'Hint: try running "pip install hurry.filesize"'
    sys.exit(1)
import os
try:
    import pexpect
except ImportError, e:
    print e
    print 'Hint: try running "pip install pexpect"'
    sys.exit(1)

# https://stackoverflow.com/questions/375427
# /non-blocking-read-on-a-subprocess-pipe-in-python
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


def status_item(item):
    sys.stdout.write('%38s: ' % item)


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


def print_pipe(type_type, pipe):
    for line in iter(pipe.readline, ''):
        print('    ' + line.rstrip())


def print_header(activity):
    """ Display start time of the activity and return it for later reference.
    """
    logger = logging.getLogger()
    time_init = time.time()
    logger.info('ArchiveR3 ' + activity + ' START - ' + \
        time.strftime("%B %-d, %Y %H:%M:%S", time.localtime(time_init)))
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
    status_item('Inventory')
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

    status_result('DONE', 1)
    status_item('')
    status_result('files ' + str(file_count) + ' dirs ' + str(dir_count) +
                  ' size ' + str(total_size) + ' (' + size(total_size) + ')')
    return total_size


def dir_validate(dir, auto=0, create=0, read=0, sudo=0, write=0):
    """ Validate a directory exists.

    Optional parameters:

      auto=True         create directory automatically; requires create=True
      create=True       prompt the user to create it
      read=True         read any random file from the directory
      sudo=True         perform mkdir operations with root-level privileges
      write=True        create (and remove) a test file

    Return 1 if no valid directory exists at the end of this function. """

    # TODO - sudo support never implemented

    logger = logging.getLogger()

    if not os.path.exists(dir):
        if create:
            logger.warning(dir + ' not found')

            if auto:
                logger.info('automatic directory creation enabled')
            else:
                print '\nCreate directory ' + dir + '? [y]',
                prompt_dircreate = raw_input()
                print '\n',

            if auto or prompt_dircreate in ['y', '']:
                logger.warning(dir + ': creating directory')
                if sudo:
                    try:
                        subprocess.call(['sudo', 'mkdir', dir])
                    except Exception, e:
                        logger.error(dir + ': directory creation failed ' + e)
                else:
                    os.makedirs(dir)

                if os.path.exists(dir):
                    logger.info(dir + ': directory creation confirmed')
                else:
                    logger.error(dir + ': directory creation failure')
                    return 1
            else:
                logger.error(dir + ': user declined directory creation')
                return 1
        else:
            logger.error(dir + ': skipping directory creation')
            return 1

    if not os.path.isdir(dir):
        logger.error(dir + ': directory does not exist')
        return 1

    if write:
        logger.info(dir + ': write test initiated')
        test_file = '.ArchiveR3-write-test'
        if os.path.exists(dir + test_file):
            logger.error(dir + ': previous test file found: ' + test_file)
            logger.warning(dir + ': remove test file manually')
            return 1
        try:
            file = open(dir + test_file, 'w')
        except IOError:
            logger.error(dir + ': could not open test file for writing')
            return 1
        file.write('test write')
        file.close()
        if os.path.isfile(dir + test_file):
            os.remove(dir + test_file)
            logger.info(dir + ': confirmed writable')
        else:
            logger.error(dir + ': file creation succeeded but confirmation '
                         'failed')
            return 1

    if read:
        logger.info(dir + ': attempt to read 1 byte from first file found')
        read_proved = False

        for root, dirs, files in os.walk(dir):
            if files:
                for filename in files:
                    file = open(root + '/' + filename, 'r')
                    test_byte = file.read(1)
                    if test_byte:
                        read_proved = True
                        logger.info(dir + ': confirmed readable')
                    else:
                        logger.error(dir + ': file found but could not read '
                                     '1st byte')
                        return 1
                    break
                break
        if not read_proved:
            logger.warning(dir + ': no test files found to read')
            return 1

    logger.info(dir + ': existence confirmed')


def loopback_exists(file):
    """ Determine if a loopback device has been allocated for a particular
    file.  If found, return it.  If not, return 0.  Note this is opposite
    normal functions where 0 means success. """
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


def loopback_setup(lbdevice, file, verbose=False):
    """ Associate a loopback device with a file.  Return 1 if failure or 0
    if successful. """
    if verbose:
        status_item('Command')
        status_result('sudo losetup --verbose ' + lbdevice + ' ' + file)

    status_item('Loopback Device')
    status_result(lbdevice)
    result = subprocess.Popen(['sudo', 'losetup', '--verbose', lbdevice, file],
                              stdout=subprocess.PIPE).communicate()[0]
    status_item('')
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
    if verbose:
        status_item('Command')
        status_result('sudo tcplay -i -d ' + lbdevice)

    status_item('Encryption Integrity')
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
    if not sum:
        status_result('EMPTY FILE?', 2)
        return 1

    try:
        child = pexpect.spawn('sudo tcplay -i -d ' + lbdevice)
        child.expect('Passphrase')
        child.sendline(password_base + container_file + "\r")

        i = child.expect(['PBKDF2', 'Incorrect password'])
        if i == 0:
            status_result('PASSWORD VALID', 1)
        elif i == 1:
            status_result('BAD PASSWORD / CORRUPTED', 3)
            child.kill(0)
            return 1
        child.expect(pexpect.EOF)
    except Exception, e:
        status_result('tcplay FAILURE', 3)
        status_item('Debugging')
        status_result("\n\n" + str(e) + "\n")
        return 1


def loopback_encrypt(lbdevice, password_base, container_file, verbose=False):
    """ Encrypt a loopback device. """
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

        if verbose:
            status_item('Command')
            status_result(cmd)

        status_item('Encrypting Volume')
        status_result('IN PROGRESS', 2, no_newline=True)

        p = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE)

        q = Queue()
        t = Thread(target=enqueue_output, args=(p.stdout, q))
        t.daemon = True  # thread dies with the program
        t.start()

        iter = 0

        # Give tcplay a chance to get going before we start SIGUSR1'ing it.
        time.sleep(0.5)
        print
        print
        while p.poll() is None:
            if iter % 100 == 0:
                cmd = 'sudo killall tcplay --signal SIGUSR1'
                subprocess.Popen(shlex.split(cmd), stderr=subprocess.PIPE)
            try:
                line = q.get(timeout=0.1)  # or q.get(timeout=.1)
            except Empty:
                pass  # no output
            else:
                print '    ' + line.rstrip()
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
    status_item('')
    status_result('ENCRYPTED', 4)
    print


def config_read(config_file):
    """ Read the configuration file.  Return a ConfigParser object on success
    or nothing on failure. """

    logger = logging.getLogger()

    if not os.path.isfile(config_file):
        logger.error('configuration file not found')
        return

    config = ConfigParser.RawConfigParser()

    try:
        config.read(config_file)
    except ConfigParser.ParsingError, e:
        logger.error('configuration file parsing error: ' + str(e))
        return

    config.backup_dir = normalize_dir(config.get('ArchiveR3', 'backup_dir'))
    config.mount_dir = normalize_dir(config.get('ArchiveR3', 'mount_dir'))
    config.archives = normalize_dir(config.get('ArchiveR3', 'archives'))
    config.data_dir = normalize_dir(config.get('ArchiveR3', 'data_dir'))
    config.log_dir = normalize_dir(config.get('ArchiveR3', 'log_dir'))
    config.password_base = config.get('ArchiveR3', 'password_base')
    config.provision_capacity_percent = \
        config.getint('ArchiveR3', 'provision_capacity_percent')
    config.provision_capacity_reprovision = \
        config.getint('ArchiveR3', 'provision_capacity_reprovision')
    return config


def config_validate(config, interactive):
    """ Make sure all the configuration settings make sense.  Try to be helpful
    and intervene if there are issues, otherwise bail. """

    logger = logging.getLogger()

    logger.info(config.backup_dir + ': container directory')
    if dir_validate(config.backup_dir, create=interactive, write=1):
        return 1

    logger.info(config.mount_dir + ': mount point directory')
    if dir_validate(config.mount_dir):
        return 1

    logger.info(config.data_dir + ': data directory')
    if dir_validate(config.data_dir, create=1, write=1):
        return 1

    if config.password_base:
        logger.info('password base found')
    else:
        logger.error('password base missing from config file')
        return 1

    logger.info('provision container initial capacity: ' +
                str(config.provision_capacity_percent) + '%')

    logger.info('reprovision when container reaches: ' +
                str(config.provision_capacity_reprovision) + '%')

    # create a blackhole stream so that we can redirect the output of
    # dependency utilities. for example, send the output of 'dd --version' to
    # /dev/null so that it does not appear inline while this program is
    # running

    devnull = open('/dev/null', 'w')

    # TODO logging (return here and resume)

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
    status_item('Mapped Device')
    status_result(archive_map)
    if os.path.islink('/dev/mapper/' + container_file):
        status_item('/dev/mapper' + container_file)
        status_result('FOUND MAP', 1)
    else:
        if mapper_container(lbdevice, container_file, password_base, verbose):
            return 1


def mount_check(archive_map, archive_mount, mountcreate=False, verbose=False):
    """ Determine if the directory where an encrypted container will be
    mounted exists.  If mountcreate is True then the directory will be
    automatically created. """
    if verbose:
        status_item('Command')
        status_result('sudo mountpoint ' + archive_mount)

    status_item('Mount Point')
    status_result(archive_mount)
    status_item('')
    if dir_validate(archive_mount, create=True, sudo=True, auto=mountcreate):
        return 1

    if verbose:
        status_item('Command')
        status_result('sudo mount ' + archive_map + ' ' + archive_mount)

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


def umount(mount_point, remove=False):
    """ Perform an umount operation to release a filesystem, typically during
    cleanup.  Operation is performed via sudo.  Optionally remove the mount
    point.  Return 1 if problems. """
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
    if remove:
        status_item(mount_point)
        try:
            subprocess.call(['sudo', 'rmdir', mount_point])
        except:
            status_result('REMOVAL FAILED', 1)
            return 1
        status_result('REMOVED MOUNT POINT', 4)


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
        if verbose:
            status_item('Command')
            status_result('sudo tcplay -m ' + container_file + ' -d ' +
                          lbdevice)
        status_item('')
        child = pexpect.spawn('sudo tcplay -m ' + container_file + ' -d ' +
                              lbdevice)
        child.expect('Passphrase')
        child.sendline(password_base + container_file + "\r")
        i = child.expect(['All ok!'])
        if i == 0:
            status_result('MAPPED,', 4, no_newline=True)
        else:
            child.kill(0)
            status_result('FAIL', 3)
            return 1
        child.expect(pexpect.EOF)
    except Exception, e:
        status_result('tcplay FAILURE', 3)
        status_item('Debugging')
        status_result("\n\n" + str(e) + "\n")
        return 1

    if os.path.islink('/dev/mapper/' + container_file):
        status_result('VERIFIED', 1)
    else:
        status_result('FAILURE', 3)
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
    status_item('Filesystem')
    devnull = open('/dev/null', 'w')
    try:
        subprocess.check_call(['sudo', 'e2fsck', '-n', archive_map],
                              stdout=devnull, stderr=devnull)
    except subprocess.CalledProcessError, e:
        if re.match('.*status 8.*', str(e)):
            status_result('INVALID', 2)
            return 1
    except Exception, e:
        print 'error ' + str(e)
        status_result('COMMAND NOT FOUND', 3)
        return 1
    status_result('VALID', 1)


def filesystem_format(archive_map, verbose=False):
    """ Create an ext4 filesystem on a mapped device. """
    status_item('Filesystem Create')
    status_result('IN PROGRESS', 2)
    try:
        if verbose:
            status_item('Command')
            status_result('sudo mkfs.ext4 ' + archive_map)

        p = subprocess.Popen(['sudo', 'mkfs.ext4', archive_map],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print
        t1 = Thread(target=print_pipe, args=('stdout', p.stdout,))
        t1.start()
        t2 = Thread(target=print_pipe, args=('stderr', p.stderr,))
        t2.start()
        t1.join()
        t2.join()
    except subprocess.CalledProcessError, e:
        status_result('FORMAT ERROR ' + str(e), 3)
        return 1
    except Exception, e:
        status_result('FORMAT COMMAND NOT FOUND ' + str(e), 3)
        return 1
    status_item('')
    status_result('FORMATTED', 4)
    print


def sync(source, target, bwlimit=1300):
    """ Synchronize files from a source to a target location. """
    status_item('Sync')
    status_result('IN PROGRESS', 2)
    try:
        cmd = 'sudo rsync ' \
              '--bwlimit ' + str(bwlimit) + ' ' + \
              '--compress ' + \
              '--recursive ' + \
              '--links ' + \
              '--perms ' + \
              '--times ' + \
              '--group ' + \
              '--owner ' + \
              '--partial ' + \
              '--verbose ' + \
              '--progress ' + \
              '--delete ' + \
              '--delete-delay ' + \
              '--max-delete=100 ' + \
              '--human-readable ' + \
              '--itemize-changes ' + \
              source.rstrip('/') + ' ' + target

        p = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        print
        t1 = Thread(target=print_pipe, args=('stdout', p.stdout,))
        t1.start()
        t2 = Thread(target=print_pipe, args=('stderr', p.stderr,))
        t2.start()
        t1.join()
        t2.join()
        print
    except subprocess.CalledProcessError, e:
        status_result('ERROR', 3)
        return 1
    except Exception, e:
        status_result('NOT FOUND ' + str(e), 3)
        return 1
    status_item('')
    status_result('SYNCHRONIZED', 1)
    print
