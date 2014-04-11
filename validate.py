#!/bin/sh
''''exec python -u -- "$0" ${1+"$@"} # '''

# special shebang avoids output buffering

import ArchiveR3
import argparse
import datetime
import hashlib
import os
import pickle
# TODO: Convert SHA-1 (insecure) to SHA3
# import sha3
from signal import signal, SIGPIPE, SIG_DFL
import sys
import time


class validate:
    """ Verify a backup has integrity by comparing local files against remote
    ones.  The calculation and comparison of SHA-1 hashes is the primary
    method used for comparison, but other factors are used as well such as:
    ctime, mtime, owner, and permissions.  A pickle is stored with telemetry
    data for both local and remote filestores.
    
    Note: it is OK to Ctrl-C out of this program and not worry about losing
    data.  However, piping it to anything else (like more, less, tee) and then
    breaking the pipe will cause the program to exit without updating the
    pickle file.  However, the original pickle file from before this program
    ran will still have integrity."""

    def __init__(self):
        signal(SIGPIPE, SIG_DFL)
        self.ArchiveR3 = ArchiveR3.ArchiveR3()
        self.ArchiveR3.config_read()
        self.init_vars()

    def init_vars(self):
        """ initialize class variables """
#       self.logdir = '/home/r3cgm/digest/log/'
#       self.pickledir = '/home/r3cgm/digest/pickle/'
#       self.pickle_snapshot = self.pickledir + 'snapshot.p'
#       self.sourcedir = '/mnt/nas/r3cgm/'
        # in seconds
#       self.stale_age = 60 * 60 * 24
        self.time_init = time.time()

    def abort(self, message, archive):
        print
        self.status_item('ABORT')
        self.status_result(message)
        self.pickle_close(archive)
        sys.exit(1)

    def status_item(self, item):
        sys.stdout.write('%22s: ' % item)

    def status_result(self, result):
        print result

    def args_process(self):
        """ process command-line arguments """
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
        parser.add_argument('archives', action='store',
            help='Specify a specific archive to validate, or \'all\' to '
            'process every archive listed in the ARCHIVES environment '
            'variable. (currently: ' + os.environ.get('ARCHIVES') + ')')
        parser.add_argument('-v', dest='verbose', action='store_true',
            help='Print the status of each file as it is being processed.  '
            'Otherwise, a progress dot is printed for every 100 files '
            'processed.')
        if len(sys.argv) == 1:
            parser.print_help()
            sys.exit(1)
        self.args = parser.parse_args()

    def get_archives(self):
        """ determine which archives to work with """
        archives = []
        if self.args.archives == 'all':
            archives = os.environ.get('ARCHIVES').split(' ')
        else:
            archives.append(self.args.archives)
        return archives

    def generate_hash(self, file):
        """ generate a fingerprint for a file used for comparison.  currently
        uses SHA-1 but should be modified to use SHA-3 in the future; maybe
        when the sha3 python lib is installed by default. """
        with open(file, 'rb') as afile:
            BLOCKSIZE = 65536
            hasher = hashlib.sha1()
            buf = afile.read(BLOCKSIZE)
            while len(buf) > 0:
                hasher.update(buf)
                buf = afile.read(BLOCKSIZE)
        return hasher.hexdigest()

    def snapshot_open(self):
        """ open the snapshot pickle """
        if os.path.exists(self.pickle_snapshot):
            self.snapshot = pickle.load(open(self.pickle_snapshot, 'rb'))
            status_item('snapshot pickle')
            status_result('opened')
            print self.snapshot

    def snapshot_update(self, archive):
        """ update the snapshot to indicate we just successfully scanned an
        archive. """
        status_item('snapshot ' + archive)
        self.snapshot[archive] = time.time()
        status_result(time.time())

    def snapshot_close(self):
        pickle.dump(self.snapshot, open(self.pickle_snapshot, 'wb'))


    def pickle_open(self, archive):
        """ open an existing pickle and load it into self.digests.  if the
        pickle does not exist, it will be created automatically by
        pickle_close() """
        if os.path.exists(self.pickledir + archive + '.p'):
            self.digests = pickle.load(open(self.pickledir + archive + '.p',
                'rb'))
            self.status_item('pickle keys')
            self.status_result(str(len(self.digests.keys())))
        else:
            self.status_item('pickle creation')
            self.status_result('pending')

    def pickle_close(self, archive):
        """ overwrite an existing pickle or create a new one """
        self.status_item('pickle')
        pickle.dump(self.digests, open(self.pickledir + archive + '.p', 'wb'))
        self.status_result('closed')
        self.status_item('pickle keys')
        self.status_result(str(len(self.digests)))
        self.summary()

    def summary(self):
        self.status_item('size bytes')
        self.status_result( \
            '%.1f' % (float(self.totalsize) / 1024 / 1024 / 1024) + \
            'G (' + str(format(self.totalsize, ',d')) + ')')

        self.status_item('size block')
        self.status_result( \
            '%.1f' % (float(self.totalsize_block) / 1024 / 1024 / 1024) + \
            'G (' + str(format(self.totalsize_block, ',d')) + ')')

        self.status_item('dirs')
        self.status_result(str(self.totaldirs))

        self.status_item('files')
        self.status_result(str(self.totalfiles))

        self.status_item('entries')
        self.status_result(str(self.totalentries))

    def file_blocksize(self, size):
        blocksize = 512
        size = size - (size % blocksize) + blocksize
        return size

    def validate_dir(self, dirpath, archive):
        if self.args.verbose is True:
            sys.stdout.write(dirpath)
        else:
            if self.totalentries % 100 == 0:
                sys.stdout.write('.')

        if not os.path.exists(dirpath):
            print 'ERROR: ' + dirpath + ' found during os.walk() but the ' + \
                  'exists() check failed.'
            sys.exit(1)

        if dirpath in self.digests \
            and 'checked' in self.digests[dirpath] \
            and self.digests[dirpath]['checked'] \
                > time.time() - self.stale_age:
            if self.args.verbose is True:
                print ' SKIPPING'
            self.totalsize_block += self.file_blocksize(0)
        else:
            if self.args.verbose is True:
                if dirpath not in self.digests:
                    print ' INDEXING'
                elif 'checked' not in self.digests[dirpath]:
                    print ' REINDEXING (missing check time)'
                elif self.digests[dirpath]['checked'] \
                    > time.time() - self.stale_age:
                    print ' REINDEXING (stale)'
            self.digests.setdefault(dirpath, {})['type'] = 'dir'
            self.digests.setdefault(dirpath, {})['size'] = 0
            self.digests.setdefault(dirpath, {})['checked'] = time.time()
            self.totalsize_block += self.file_blocksize(0)

        self.totaldirs += 1
        self.totalentries += 1

    def validate_file(self, filepath, archive):
        if self.args.verbose is True:
            sys.stdout.write(filepath)
        else:
            if self.totalentries % 100 == 0:
                sys.stdout.write('.')

        if not os.path.exists(filepath):
            print 'ERROR: ' + filepath + ' found during os.walk() but the ' + \
                  'exists() check failed.'
            sys.exit(1)

        if filepath in self.digests \
            and 'checked' in self.digests[filepath] \
            and self.digests[filepath]['checked'] \
                > time.time() - self.stale_age:
            if self.args.verbose is True:
                print ' SKIPPING'
            self.totalsize += self.digests[filepath]['size']
            self.totalsize_block += \
                self.file_blocksize(self.digests[filepath]['size'])
        else:
            if self.args.verbose is True:
                if filepath not in self.digests:
                    print ' INDEXING'
                elif 'checked' not in self.digests[filepath]:
                    print ' REINDEXING (missing check time)'
                elif self.digests[filepath]['checked'] \
                    > time.time() - self.stale_age:
                    print ' REINDEXING (stale)'

            hash = self.generate_hash(filepath)
            size = os.stat(filepath).st_size

            if os.stat(filepath).st_nlink > 1:
                abort('more than 1 hard link found for file. investigate: ' + \
                    filepath, archive)

            self.digests.setdefault(filepath, {})['type'] = 'file'
            self.digests.setdefault(filepath, {})['hash'] = hash
            self.digests.setdefault(filepath, {})['mode'] = \
                os.stat(filepath).st_mode
            self.digests.setdefault(filepath, {})['mtime'] = \
                os.stat(filepath).st_mtime
            self.digests.setdefault(filepath, {})['size'] = \
                os.stat(filepath).st_size
            self.digests.setdefault(filepath, {})['uid'] = \
                os.stat(filepath).st_uid
            self.digests.setdefault(filepath, {})['gid'] = \
                os.stat(filepath).st_gid
            self.digests.setdefault(filepath, {})['checked'] = time.time()

            self.totalsize += size
            self.totalsize_block += self.file_blocksize(size)

        self.totalfiles += 1
        self.totalentries += 1

    def validate_archive(self, archive):
        self.status_item('location')
        self.status_result(self.sourcedir + archive)

        # total size of entries based on consumed block size
        self.totalsize_block = 0
        self.totalsize = 0

        self.totalfiles = 0
        self.totaldirs = 0
        self.totalentries = 0

        self.digests = {}
        self.pickle_open(archive)

        try:
            self.status_item('inventory local')
            for root, dirs, files in os.walk(self.sourcedir + archive, \
                topdown=True):
                try:
                    for dir in dirs:
                        try:
                            dirpath = os.path.join(root, dir)
                            self.validate_dir(dirpath, archive)
                        except KeyboardInterrupt:
                            self.abort('directory processing', archive)
                    for file in files:
                        try:
                            filepath = os.path.join(root, file)
                            self.validate_file(filepath, archive)
                        except KeyboardInterrupt:
                            self.abort('file processing', archive)
                except KeyboardInterrupt:
                    self.abort('recursive directory traversal', archive)
            print
        except KeyboardInterrupt:
            self.abort('archive directory processing', archive)
        else:
            self.pickle_close(archive)
            self.snapshot_update(archive)
            self.snapshot_close()

    def validate(self):
        for archive in self.get_archives():
            self.status_item('processing')
            self.status_result(archive)
            self.validate_archive(archive)
            # only do the first archive
            break

    def main(self):
        """ If you call the python as a script, this is what gets executed """
        self.args_process()
        self.print_header()
        self.validate()
        self.print_footer()


if __name__ == '__main__':
#   try:
        validate = validate()
        validate.main()
#   except KeyboardInterrupt:
#       pass
