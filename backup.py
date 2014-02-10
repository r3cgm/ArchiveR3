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


class backup:
    """ Perform a backup via rsync to an encrypted filesystem hosted in the
    cloud. """

    def __init__(self):
        self.init_vars()

    def init_vars(self):
        """ Initialize class variables. """
        # lost storage due to overhead of encrypted container
        self.container_overhead = 1471488
        self.container_overhead_m = 2

    def args_process(self):
        """ Process command-line arguments. """
        parser = argparse.ArgumentParser(
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            description='Backup files from a \'local\' to a \'remote\' '
            'location.  Please be sure to create and edit your config file, '
            'for example by copying config.generic to config.mine and '
            'invoking this tool with it.')
        parser.add_argument('config', action='store',
                            help='Specify an ArchiveR3 config file.')
        parser.add_argument('-c', '--cleanup', action='store_true',
                            help='Do *not* perform normal cleanup operations '
                            'after backing up such as unmounting and '
                            'unmapping the archive container.')
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

    def create_archive(self, archive_dir, container, backup_dir, arc_block):
        """ Create an encrypted container.  The resulting containersize is only
        accurate to the nearest megabyte.  Return 1 if any problems or 0 for
        success. """
        status_item('!! CREATE CONTAINER? (y/n)')
        if raw_input() == 'y':
            archive_size = int(float(arc_block) /
                               float(self.config.provision_capacity_percent)
                               * 100)
            archive_size_m = int(math.ceil(float(archive_size) / 1024 / 1024))
            status_item('Archive Size')
            status_result(str(arc_block) + ' (' + size(arc_block) + ')')
            status_item('Provisioned Archive Size')
            status_result(str(archive_size) + ' (' + size(archive_size) + ')')
            status_item('Required Container Size')
            container_size_needed = archive_size + self.container_overhead
            container_size_needed_m = archive_size_m + \
                self.container_overhead_m
            status_result(str(container_size_needed_m * 1048576) + ' (' +
                          str(container_size_needed_m) + 'M)')
            status_item('Generating Container')
            status_result('IN PROGRESS', 2)
            try:
                print
                subprocess.check_call('dd if=/dev/zero bs=1048576 ' +
                                      'status=none ' +
                                      'count=' + str(container_size_needed_m) +
                                      ' | pv -s ' +
                                      str(container_size_needed_m * 1048576) +
                                      ' | ' + 'dd status=none ' +
                                      'of=' + container, shell=True)
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
        """ Unmount, unmap, and remove the loopback device associated with
        the encrypted container. """
        if self.archive_mount:
            umount(self.archive_mount)
        if self.container_file:
            unmap(self.container_file)
        if self.lbdevice:
            loopback_delete(self.lbdevice)

    def backup(self):
        # TODO: make the definitions backing up these checks all consistent,
        # in terms of who is reponsible for printing status info, the caller
        # or the function, etc.
        for i, s in enumerate(self.config.archive_list):

            section_break()

            archive_dir = self.config.archive_list[i]
            status_item('Archive')
            status_result(archive_dir)

            container_dir = self.config.backup_dir
            self.container_file = self.config.archive_list[i].split('/')[-2] \
                + '.archive'
            container = container_dir + self.container_file

            arc_block = dir_size(archive_dir, block_size=512)

            status_item(self.container_file)
            if os.path.isfile(container):
                status_result('CONTAINER FOUND', 1)
            else:
                status_result('CONTAINER NOT FOUND', 2)
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

            status_item('Estimated Container Capacity')
            container_size_net = container_size - \
                (self.container_overhead_m * 1048576)
            capacity_est = float(arc_block) / float(container_size_net) * 100
            if capacity_est > 100:
                capacity_est = 100

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

                status_item('Reprovision? (y/n)')
                if raw_input() == 'y':
                    if self.create_archive(self.config.archive_list[i],
                                           container, self.config.backup_dir,
                                           arc_block +
                                           self.container_overhead):
                        return 1
                    else:
                        status_item('Reprovision')
                        status_result('SUCCESS', 1)
                else:
                    status_item('Capacity')
                    status_result('EXCEEDED', 3)
                    return 1

            self.lbdevice = loopback_exists(container)

            if not self.lbdevice:
                loopback_cleanup(container)
                self.lbdevice = loopback_next()
                if not self.lbdevice:
                    return 1
                if loopback_setup(self.lbdevice, container):
                    return 1

            if loopback_encrypted(self.lbdevice, self.config.password_base,
                                  self.config.backup_dir, self.container_file,
                                  self.args.verbose):
                status_item('!! (RE)ENCRYPT CONTAINER? (y/n)')
                if raw_input() == 'y':
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
                status_item('!! REFORMAT FILESYSTEM? (y/n)')
                if raw_input() == 'y':
                    if filesystem_format(archive_map, self.args.verbose):
                        return 1
                else:
                    return 1

            self.archive_mount = self.config.mount_dir + self.container_file

            if mount_check(archive_map, self.archive_mount):
                return 1

            stat = os.statvfs(self.archive_mount)
            cryptfs_size = str(stat.f_blocks * stat.f_frsize)
            if not cryptfs_size:
                status_item('Encrypted Filesystem Size')
                status_result('PROBE FAILED', 3)
                return 1

            status_item('Capacity Actual')
            capacity_act = float(arc_block) / float(cryptfs_size) * 100
            if capacity_act > 100:
                capacity_act = 100

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
                    status_result('SUCCESS BUT NEED TO RESTART AND MAKE SURE' +
                                  'NOT RUNNING WITH --cleanup OPTION', 2)
                    return 1

# TODO: cleanup
#           status_result('free ' + str(stat.f_bavail * stat.f_frsize))
#           status_result('total ' + str(stat.f_blocks * stat.f_frsize))
#           status_result('avail ' + str((stat.f_blocks - stat.f_bfree) * \
#                         stat.f_frsize))
#           status_result(str(get_fs_freespace(self.archive_mount)))

            if sync(archive_dir, self.archive_mount):
                return 1

            if not self.args.cleanup:
                self.cleanup()

        return 0

    def main(self):
        """ If you call the python as a script, this is what gets executed. """

        # These 3 variables are key to performing safe cleanup.  they do not
        # need to be populated now, but they need to be declared.  At any point
        # the user may Ctrl-C out, and we will use these variables to clean up.
        self.archive_mount = ''
        self.container_file = ''
        self.lbdevice = ''

        try:
            self.args_process()
            time_init = print_header('backup')

            self.config = config_read(self.args.config)

            if self.config:
                if config_validate(self.config):
                    status_item('Configuration')
                    status_result('VALIDATION FAILED', 3)
                else:
                    status_item('Configuration')
                    status_result('VALIDATED', 1)
                    rc = self.backup()
                    status_item('Backup')
                    if rc == 1:
                        status_result('FAILED', 3)
                    else:
                        status_result('SUCCESS', 1)

            print_footer('backup', time_init)
        except KeyboardInterrupt:
            print
            status_item('Backup')
            status_result('ABORT', 3)
            if not self.args.cleanup:
                status_item('Cleanup')
                if self.cleanup():
                    status_result('FAILURE', 3)
                else:
                    status_result('SUCCESS', 1)
            status_item('Safe Quit')
            status_result('SUCCESS', 1)
            pass


if __name__ == '__main__':
    sys.stdout = Unbuffered(sys.stdout)

    backup = backup()
    backup.main()
