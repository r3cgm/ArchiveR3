#!/bin/sh

export ARCHIVE=core
export ARCHIVE_FILE="${ARCHIVE}.archive"
export SIZE_M=2200
export PASSWORDBASE=abc123
export REMOTE_DIR=/mnt/cloud/somedir

# create archive
dd if=/dev/zero of=$REMOTE_DIR$ARCHIVE_FILE bs=1 count=0 seek=${SIZE_M}M

# find free loopback device
LOOPBACK_DEV=$(sudo losetup -f)

# associate loopback device with archive
sudo losetup $LOOPBACK_DEV $REMOTE_DIR$ARCHIVE_FILE

# to enable Expect debugging, add this:
# exp_internal 1

# encrypt loopback device
expect -c "spawn sudo tcplay -c -d $LOOPBACK_DEV -a whirlpool -b AES-256-XTS
set timeout 2
expect Passphrase
send $PASSWORDBASE$ARCHIVE_FILE\r
expect Repeat
send $PASSWORDBASE$ARCHIVE_FILE\r
expect proceed
send y\r
interact
"

# had to run this twice, why?

# create a dm-crypt drive mapping
expect -c "spawn sudo tcplay -m $ARCHIVE_FILE -d $LOOPBACK_DEV
set timeout 1
expect Passphrase
send $PASSWORDBASE$ARCHIVE_FILE\r
expect eof
"

# format archive with ext4
sudo mkfs.ext4 /dev/mapper/$ARCHIVE_FILE

[[ -d "/mnt/$ARCHIVE_FILE" ]] || sudo mkdir /mnt/$ARCHIVE_FILE

# mount archive
sudo mount /dev/mapper/$ARCHIVE_FILE /mnt/$ARCHIVE_FILE


# UNDO


# unmount archive
sudo umount /mnt/$ARCHIVE_FILE

# remove volume
sudo dmsetup remove $ARCHIVE_FILE

# delete loopback device
sudo losetup -d $LOOPBACK_DEV

# remove the archive
# rm $REMOTE_DIR$ARCHIVE_FILE
