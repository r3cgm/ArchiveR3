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
        self.config = config_read()
        self.init_vars()

    def args_process(self):
        """ Process command-line arguments. """
        parser = argparse.ArgumentParser(
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            description='Verify a backup has integrity by comparing local '
            'files against remote ones.  The contents of each file are '
            'inspected, as well as the presense or absense of local and '
            'remote files.  The state of both local archive and remote '
            'backup are stored.  This state is used later in order to speed '
            'up the validation process.  For example, this tool can '
            'preferentially validate the files whose previously known state '
            'is the oldest.')
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

    def init_vars(self):
        """ Initialize class variables. """

    def backup(self):
        status_item('Performing backups now')
        status_result('TBD')

    def main(self):
        """ If you call the python as a script, this is what gets executed """
        self.args_process()
        time_init = print_header('backup')
        self.backup()
        print_footer('backup', time_init)


if __name__ == '__main__':
    backup = backup()
    backup.main()
