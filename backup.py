#!/usr/bin/env python

from ArchiveR3 import *
import argparse
try:
    from hurry.filesize import size
except ImportError, e:
    print e
    print 'Hint: try running "pip install hurry.filesize"'
    sys.exit(1)
import math
import re
import subprocess
import sys
import time


class backup:
    """ Perform a backup via rsync to an encrypted filesystem hosted in the
    cloud. """

    def __init__(self):
        self.init_vars()

    def init_vars(self):
        """ Initialize class variables. """
        # Lost storage due to overhead of encrypted container.
        # ~6.4M fixed overhead.
        # Plus 7.5% relative overhead.
        self.container_overhead_fixed = 6225865
        self.container_overhead_percent = 7.5
        self.logfile = 'ArchiveR3-' + time.strftime("%Y%m%d-%H%M%S")

    def args_process(self):
        """ Process command-line arguments. """
        parser = argparse.ArgumentParser(
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            description='Back up files to an archive.  This is performed in '
            'phases: 1. create a zeroed file archive container, 2. encrypt '
            'the container, and 3. synchronize files with the archive. '
            'To specify directories to back up, edit your config file, '
            'for example by copying config.generic to config.mine and '
            'invoking this tool with it.')
        parser.add_argument('config', action='store',
                            help='Specify an ArchiveR3 config file.')
        parser.add_argument('-a', '--auto', action='store_true',
                            help='Automatically create, encrypt, format, '
                            'mount, and archive without prompting.  '
                            'Equivalent to --create --encrypt --format'
                            '--mountcreate')
        parser.add_argument('-b', '--bwlimit', type=int,
                            help='Bandwidth limit during synchronization '
                            'in KBps.  A value of 0 means no limit. '
                            'Removing the bandwidth limit can be useful if '
                            'for example the archive is being created on a '
                            'local filesystem where you do not care about '
                            'saturating the connection and want to write '
                            'as quickly as possible.', default=1300)
        parser.add_argument('-c', '--cleanup', action='store_true',
                            help='Perform cleanup operations only, no '
                            'backup.  Cleanup consists of unmounting, '
                            'unmapping, and removing the loopback device '
                            'associated with the encrypted container.')
        parser.add_argument('--create', action='store_true',
                            help='Create container without prompting.')
        parser.add_argument('--encrypt', action='store_true',
                            help='Encrypt container without prompting.')
        parser.add_argument('--format', action='store_true',
                            help='Format encrypted container without '
                            'prompting.')
        parser.add_argument('--mountcreate', action='store_true',
                            help='Create the mount point automatically.')
        parser.add_argument('--reprovision', action='store_true',
                            help='Reprovision the container automatically '
                            'if too small.')
        parser.add_argument('-n', '--nocleanup', action='store_true',
                            help='Do not perform normal cleanup operations '
                            'after backing up such as unmounting and '
                            'unmapping the archive container.')
        parser.add_argument('-s', '--skipbackup', action='store_true',
                            help='Skip backup.  This can be useful to test '
                            'basic mounting and unmounting.  Used with '
                            '--nocleanup this simply mounts the archive and '
                            'leaves it mounted when the program exits.')
        parser.add_argument('-v', '--verbose', action='store_true',
                            help='Print the status of each file as it is '
                            'being processed.  Otherwise, a progress dot is '
                            'printed for every 100 files processed.  '
                            '\'processing\' refers not just to backing up '
                            'files, but also checking to see if they have '
                            'previously been backed up.')
        if len(sys.argv) == 1:
            parser.print_help()
            sys.exit(1)
        self.args = parser.parse_args()
        if self.args.auto:
            self.args.create = True
            self.args.encrypt = True
            self.args.format = True
            self.args.mountcreate = True
            self.args.reprovision = True

    def calc_container_overhead(self, container_size):
        """ Given a container size, calculate the expected overhead due
        to encryption, reserved space for root, journaling, etc. """
        container_overhead = self.container_overhead_fixed \
            + (
                (container_size
                    - self.container_overhead_fixed)
                *
                (self.container_overhead_percent / 100))
        container_overhead = int(math.ceil(container_overhead))
        return container_overhead

    def calc_archive_container(self, archive_size):
        """ Given an archive size, calculate the approximate minimum size of
        the container necessary to hold the archive.  This takes into account
        expected overhead due to encrypt, reserved space for root, journaling,
        etc. """
        archive_container = archive_size \
            * ((self.container_overhead_percent + 100) / 100) \
            + self.container_overhead_fixed
        archive_container = int(math.ceil(archive_container))
        return archive_container

    def create_archive(self, archive_dir, container, backup_dir, arc_block):
        """ Create an encrypted container.  The resulting containersize is only
        accurate to the nearest megabyte.  Return 1 if any problems or 0 for
        success. """
        if self.args.create:
            status_item('!! CREATE CONTAINER')
            status_result('CONFIRMED', 4)
        else:
            status_item('!! CREATE CONTAINER? (y/n)')

        if self.args.create or raw_input() == 'y':
            archive_size = int(float(arc_block) /
                               float(self.config.provision_capacity_percent)
                               * 100)
            status_item('Archive Block Size')
            status_result(str(arc_block) + ' (' + size(arc_block) + ')')
            status_item('Provision Capacity')
            status_result(str(archive_size) + ' (' + size(archive_size) + ')')
            status_item('Required Container Size')
            # Round to the nearest megabyte to speed up dd blocksize below.
            container_size_needed_m = \
                int(math.ceil(self.calc_archive_container(archive_size)
                    / 1048576))

            status_result(str(container_size_needed_m * 1048576) + ' (' +
                          str(container_size_needed_m) + 'M)')
            status_item('Generating Container')
            status_result('IN PROGRESS', 2)
            try:
                # TODO: need to convert this into a scheme which is not
                # dependent on Unix pipes
#               cmd = 'dd if=/dev/zero bs=1048576 ' + \
#                     'status=none ' + \
#                     'count=' + str(container_size_needed_m) + \
#                     ' | pv -s ' + \
#                     str(container_size_needed_m * 1048576) + \
#                     ' | ' + 'dd status=none ' + \
#                     'of=' + container

#               subprocess.check_call(shlex.split(cmd), shell=True)

                if self.args.verbose:
                    status_item('Command')
                    status_result('dd if=/dev/zero bs=1048576 status=none ' + \
                                  'count=' + str(container_size_needed_m) + \
                                  ' ' + 'of=' + container)

                print

                subprocess.check_call('dd if=/dev/zero bs=1048576 ' +
                                      'status=none ' +
                                      'count=' + str(container_size_needed_m) +
                                      ' | pv -s ' +
                                      str(container_size_needed_m * 1048576) +
                                      ' | ' + 'dd status=none ' +
                                      'of=' + container, shell=True)
                print
            except subprocess.CalledProcessError, e:
                status_item('Generation Result')
                status_result('FAILED: ' + str(e), 3)
                return 1
            except Exception, e:
                status_item('Generation Result')
                print e
                if re.match('.*No such file or directory', str(e)):
                    status_result('COMMAND NOT FOUND', 3)
                    return 1
            return 0
        else:
            return 1

    def cleanup(self):
        """ Unmount, remove mount point, unmap, and remove the loopback
        device associated with the encrypted container. """
        # Give the rsync time to gracefully terminate.
        status_item('Cleaning Up')
        status_result('.', no_newline=True)
        time.sleep(1)
        status_result('.', no_newline=True)
        time.sleep(1)
        status_result('.')
        time.sleep(1)
        if self.archive_mount:
            umount(self.archive_mount, remove=True)
        if self.container_file:
            unmap(self.container_file)
        if self.lbdevice:
            loopback_delete(self.lbdevice)

    def backup(self):
        for i, s in enumerate(self.config.archive_list):
            section_break()

            archive_dir = self.config.archive_list[i]
            status_item('Archive')
            status_result(archive_dir)

            self.container_file = self.config.archive_list[i].split('/')[-2] \
                + '.archive'

            self.archive_mount = self.config.mount_dir + self.container_file
            container = self.config.backup_dir + self.container_file

            self.lbdevice = loopback_exists(container)

            if self.args.cleanup:
                self.cleanup()
                return 2

            arc_block = dir_size(archive_dir, block_size=512)
            if arc_block == -1:
                status_item('ARCHIVE READABILITY')
                status_result('FAILED', 3)
                return 1

            status_item('Container')
            status_result(container)
            status_item('')
            if os.path.isfile(container):
                status_result('FOUND', 1)
            else:
                status_result('NOT FOUND', 2)
                if self.create_archive(self.config.archive_list[i],
                                       container, self.config.backup_dir,
                                       arc_block):
                    return 1

            container_size = os.path.getsize(container)
            if not container_size:
                status_item('Container Size')
                status_result('PROBE FAILED', 3)
                return 1

            if self.args.verbose:
                status_item('Archive Size')
                status_result(str(arc_block) + ' (' + size(arc_block) + ')')
                status_item('Container Size')
                status_result(str(container_size) + ' (' +
                              size(container_size) + ')')

            status_item('Estimated Consumption')
            container_size_net = container_size - \
                self.calc_container_overhead(container_size)

            capacity_est = float(arc_block) / float(container_size_net) * 100

            if capacity_est < self.config.provision_capacity_reprovision:
                capacity_est_condition = 1
            else:
                capacity_est_condition = 2

            status_result(str('%0.2f%%' % capacity_est),
                          capacity_est_condition, no_newline=True)
            status_result(str(arc_block) + '/' + str(container_size_net) + ' '
                          + size(arc_block) + '/' + size(container_size_net))

            if capacity_est_condition == 2:
                status_item('')
                status_result('OUT OF SPACE', capacity_est_condition)

                if self.args.reprovision:
                    status_item('!! REPROVISION?')
                    status_result('CONFIRMED', 4)
                else:
                    status_item('!! REPROVISION? (y/n)')

                if self.args.reprovision or raw_input() == 'y':
                    self.cleanup()
                    if self.create_archive(self.config.archive_list[i],
                                           container, self.config.backup_dir,
                                           arc_block):
                        return 1
                    else:
                        status_item('Container Generation')
                        status_result('SUCCESS', 1)
                else:
                    status_item('Capacity')
                    status_result('EXCEEDED', 3)
                    return 1

            if not self.lbdevice:
                loopback_cleanup(container)
                self.lbdevice = loopback_next()
                if not self.lbdevice:
                    return 1
                if loopback_setup(self.lbdevice, container, self.args.verbose):
                    return 1

            if loopback_encrypted(self.lbdevice, self.config.password_base,
                                  self.config.backup_dir, self.container_file,
                                  self.args.verbose):
                if self.args.encrypt:
                    status_item('!! (RE)ENCRYPT CONTAINER')
                    status_result('CONFIRMED', 4)
                else:
                    status_item('!! (RE)ENCRYPT CONTAINER? (y/n)')

                if self.args.encrypt or raw_input() == 'y':
                    if loopback_encrypt(self.lbdevice,
                                        self.config.password_base,
                                        self.container_file,
                                        self.args.verbose):
                        return 1
                else:
                    return 1

            archive_map = '/dev/mapper/' + self.container_file

            if mapper_check(self.lbdevice, archive_map, self.container_file,
                            self.config.password_base, self.args.verbose):
                return 1

            if filesystem_check(archive_map):
                if self.args.format:
                    status_item('!! (RE)FORMAT FILESYSTEM')
                    status_result('CONFIRMED', 4)
                else:
                    status_item('!! (RE)FORMAT FILESYSTEM? (y/n)')
                if self.args.format or raw_input() == 'y':
                    if filesystem_format(archive_map, self.args.verbose):
                        return 1
                else:
                    return 1

            if mount_check(archive_map, self.archive_mount,
                mountcreate=self.args.mountcreate, verbose=self.args.verbose):
                return 1

            stat = os.statvfs(self.archive_mount)

            cryptfs_size = str((stat.f_blocks -
                               (stat.f_bfree - stat.f_bavail)) * stat.f_frsize)

            if not cryptfs_size:
                status_item('Encrypted Filesystem Size')
                status_result('PROBE FAILED', 3)
                return 1

            status_item('Anticipated Consumption')

            capacity_act = float(arc_block) / float(cryptfs_size) * 100

            # capacity_act_condition will be 1 (green/OK) or 2 (yellow/WARNING)
            if capacity_act < self.config.provision_capacity_reprovision:
                capacity_act_condition = 1
            else:
                capacity_act_condition = 2

            status_result(str('%0.2f%%' % capacity_act),
                          capacity_act_condition, no_newline=True)
            status_result(str(arc_block) + '/' + cryptfs_size + ' ' +
                          size(arc_block) + '/' + size(int(cryptfs_size)))

            if capacity_act_condition == 2:
                status_item('Reprovision? (y/n)')
                confirm_reprovision = raw_input()
                self.cleanup()
                if self.create_archive(self.config.archive_list[i],
                                       container, self.config.backup_dir,
                                       arc_block + self.container_overhead):
                    return 1
                else:
                    status_item('Reprovision')
                    status_result('SUCCESS BUT NEED TO RESTART AND USE' +
                                  'WITH --nocleanup OPTION', 2)
                    return 1

            if not self.args.skipbackup:
                if sync(archive_dir, self.archive_mount, self.args.bwlimit):
                    return 1

            if not self.args.nocleanup:
                self.cleanup()

            # Clean up global variables so there is no chance of accidentally
            # using them next time through the loop.
            self.container_file = ''
            self.archive_mount = ''
            self.lbdevice = ''

        return 0

    def main(self):
        """ If you call the python as a script, this is what gets executed. """

        # These 3 variables are key to performing safe cleanup.  they do not
        # need to be populated now, but they need to be declared.  At any point
        # the user may Ctrl-C out, and we will use these variables to clean up.
        self.container_file = ''
        self.lbdevice = ''
        self.archive_mount = ''

        try:
            self.args_process()
            time_init = print_header('backup')

            self.config = config_read(self.args.config)

            if self.config:
                if config_validate(self.config):
                    status_item('Configuration')
                    status_result('VALIDATION FAILED', 3)
                    status_item('Backup')
                    status_result('FAILED', 3)
                else:
                    status_item('Configuration')
                    status_result('VALIDATED', 1)

                    status_item('Bandwidth Limit')
                    if self.args.bwlimit:
                        status_result(str(self.args.bwlimit) + ' KBps')
                    else:
                        status_result('NONE', 1)

                    status_item('Logfile')
                    status_result(self.config.log_dir + self.logfile)
 
                    rc = self.backup()
                    status_item('Backup')
                    if rc == 1:
                        status_result('FAILED', 3)
                        if not self.args.nocleanup:
                            self.cleanup()
                    elif rc == 2:
                        status_result('SKIPPED', 2)
                    else:
                        status_result('SUCCESS', 1)
            print_footer('backup', time_init)
        except KeyboardInterrupt:
            print
            status_item('Backup')
            status_result('ABORT', 3)
            if not self.args.nocleanup:
                self.cleanup()
            status_item('Safe Quit')
            status_result('SUCCESS', 1)
            pass


if __name__ == '__main__':
    sys.stdout = Unbuffered(sys.stdout)

    backup = backup()
    backup.main()
