#!/bin/sh
''''exec python -u -- "$0" ${1+"$@"} # '''

# special shebang avoids output buffering

from ArchiveR3 import *
import argparse
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

    def backup(self):
        for i, s in enumerate(self.config.archive_list):
            status_item('Backing Up')
            status_result(self.config.backup_dir)
            arc_dir = self.config.backup_dir
            arc_file = self.config.archive_list[i].split('/')[-2] + '.archive'
            arc = arc_dir + arc_file
            status_item(arc_file)
            if os.path.isfile(arc):
                status_result('FOUND', 1)
            else:
                status_result('NOT FOUND', 2)
                status_item('Create? (y/n)')
                confirm_create = raw_input()
                if confirm_create == 'y':
                    status_item('Source size')
                    arc_size = dir_size(self.config.archive_list[i])
                    status_result(arc_size)
                else:
                    return 1

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
