#!/usr/bin/env python

import ConfigParser


class ArchiveR3:
    """ Library class for the ArchiveR3 backup, verify, and restore system. """

    def __init__(self):
        self.init_vars()

    def init_vars(self):
        """ Initialize class variables. """

    def config_read(self):
        """ Read the configuration. """
        self.config = ConfigParser.RawConfigParser()
        self.config.read('config')
        self.config.archives = self.config.get('ArchiveR3', 'archives')
        self.config.backup_dir = self.config.get('ArchiveR3', 'backup_dir')
        self.config.log_dir = self.config.get('ArchiveR3', 'log_dir')
        self.config.data_dir = self.config.get('ArchiveR3', 'data_dir')
        self.config.stale_age = self.config.getint('ArchiveR3', 'stale_age')
        self.config.password_base = self.config.get('ArchiveR3',
                                                    'password_base')

    def status_item(self, item):
        sys.stdout.write('%22s: ' % item)

    def status_result(self, result):
        print result

    def main(self):
        """ If you call the python as a script, this is what gets executed. """


if __name__ == '__main__':
    ArchiveR3 = ArchiveR3()
