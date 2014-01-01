#!/bin/sh
''''exec python -u -- "$0" ${1+"$@"} # '''

# special shebang avoids output buffering


class backup:
    """ Perform a backup via rsync to an encrypted filesystem hosted in the
    cloud. """

    def __init__(self):
        self.init_vars()
        self.ArchiveR3 = ArchiveR3.ArchiveR3()
        self.ArchiveR3.config_read()
        self.init_vars()

    def init_vars(self):
        """ Initialize class variables. """

    def main(self):
        """ If you call the python as a script, this is what gets executed """


if __name__ == '__main__':
    backup = backup()
    backup.main()
