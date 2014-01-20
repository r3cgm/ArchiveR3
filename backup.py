#!/usr/bin/env python

from ArchiveR3 import *
import argparse
try:
    from hurry.filesize import size
except ImportError, e:
    print e
    print 'Hint: try running "pip install hurry.filesize"'
    sys.exit(1)
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
        parser.add_argument('-v', dest='verbose', action='store_true',
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
        status_item('Create new archive? (y/n)')
        confirm_create = raw_input()
        if confirm_create == 'y':
            archive_size = int(float(arc_block) /
                               float(self.config.provision_capacity_percent) * 100)
            archive_size_m = int(float(archive_size) / 1024 / 1024)
            status_item('Required Archive Size')
            status_result(str(archive_size) + ' (' + size(archive_size) + ')')
            status_item('Generating Container')
            status_result('IN PROGRESS', 2)
            try:
                subprocess.check_call('dd if=/dev/zero bs=1048576 status=none ' +
                                      'count=' + str(archive_size_m) +
                                      ' | pv -s ' + str(archive_size) + ' | ' +
                                      'dd status=none ' +
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

    def backup(self):
        for i, s in enumerate(self.config.archive_list):
            archive_dir = self.config.archive_list[i]
            status_item('Archive')
            status_result(archive_dir)

            status_item('Archive Size (512 byte blocks)')
            arc_block = dir_size(archive_dir, block_size=512)
            status_result(str(arc_block) + ' (' + size(arc_block) + ')')

            container_dir = self.config.backup_dir
            container_file = self.config.archive_list[i].split('/')[-2] + \
                '.archive'
            container = container_dir + container_file

            status_item('Container')
            status_result(container)

            # existence check

            status_item(container_file)
            if os.path.isfile(container):
                status_result('FOUND', 1)
            else:
                status_result('NOT FOUND', 2)
                rc = self.create_archive(self.config.archive_list[i],
                                         container, self.config.backup_dir,
                                         arc_block)
                if rc:
                    return 1

            status_item('Container Size')
            container_size = os.path.getsize(container)
            status_result(str(container_size) + ' (' +
                          size(container_size) + ')')

            # capacity check

            status_item('Capacity')
            if container_size:
                capacity = float(arc_block) / float(container_size) * 100
                if capacity > 100:
                    capacity = 100
            else:
                capacity = 100

            if capacity < self.config.provision_capacity_reprovision:
                status_result(str('%0.1f%%' % capacity), 1)
            else:
                status_result(str('%0.1f%%' % capacity), 2)
#               status_item('Reprovision? (y/n)')
#               confirm_reprovision = raw_input()
#               status_item('Reprovisioning')
                rc = self.create_archive(self.config.archive_list[i],
                                         container, self.config.backup_dir,
                                         arc_block)
                if rc:
                    return 1
                return 1

            # loopback device check

            lbdevice = lb_exists(container)
            if not lbdevice:
                lbdevice = lb_next()
                rc = lb_setup(lbdevice, container)
                if rc:
                    return 1

            # determine if loopback device is valid (encrypted)

            rc = lb_encrypted(lbdevice, self.config.password_base,
                              self.config.backup_dir, container_file)
            if rc:
                status_item('!! DESTROY AND RECREATE ARCHIVE? (y/n)')
                confirm_create = raw_input()
                if confirm_create == 'y':
                    rc = lb_encrypt(lbdevice, self.config.password_base,
                                    container_file)
                else:
                    return 1

            # mount point check

            archive_mount = self.config.mount_dir + container_file
            status_item('Mount Point ' + archive_mount)
            rc = dir_validate(archive_mount, create=1, sudo=1)
            if rc:
                return 1


            # mapper check

#           archive_map = '/dev/mapper/' + container_file
#           status_item('Map ' + archive_map)
#           if os.path.isdir('/dev/mapper/' + container_file):
#               status_result('FOUND', 1)
#           else:
#               status_result('NOT FOUND', 2)
#               rc = map_container(lbdevice, container_file,
#                                  self.config.password_base)
#               if rc:
#                   return 1

        return 0

    def main(self):
        """ If you call the python as a script, this is what gets executed. """
        self.args_process()
        time_init = print_header('backup')
        status_item('Config \'' + self.args.config + '\'')

        self.config = config_read(self.args.config)
        if self.config:
            status_result('LOADED', 1)
            if config_validate(self.config):
                status_item('Configuration')
                status_result('VALIDATION FAILED', 3)
            else:
                status_item('Configuration')
                status_result('VALIDATED', 1)
                section_break()
                rc = self.backup()
                status_item('Backup')
                if rc == 1:
                    status_result('FAILED', 3)
                else:
                    status_result('SUCCESS', 1)
        else:
            status_result('NOT FOUND', 3)

        print_footer('backup', time_init)


if __name__ == '__main__':
    sys.stdout = Unbuffered(sys.stdout)

    try:
        backup = backup()
        backup.main()
    except KeyboardInterrupt:
        print
        status_item('Backup')
        status_result('ABORT', 3)
        status_item('Safe Quit')
        status_result('SUCCESS', 1)
        pass
