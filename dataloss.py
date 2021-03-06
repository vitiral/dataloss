#!/usr/bin/python

from __future__ import print_function

import sys
import os
import time
from datetime import datetime
import re
import struct
import tempfile
import signal
import argparse

import six

dtemp = tempfile.mkdtemp()
tmpdir = os.path.split(dtemp)[0]
os.rmdir(dtemp)
del dtemp
LOGPATH = os.path.join(tmpdir, 'dataloss.log')

UINT_MAX = 2**16
ENDIAN = '>'

SETTINGS_MSG = '- Settings: path={} bs={} size={}'
WRAPPED_MSG = '- Wrapped'
BLOCK_MSG = 'block: {}'
FAILED_MSG = 'Failed at ' + BLOCK_MSG
LAST_MSG = 'Last ' + BLOCK_MSG
INVALID_BLOCK_MSG = '- Invalid block. ' + FAILED_MSG
IO_ERROR_MSG = '- IO Error. ' + FAILED_MSG
SUCCESS_MSG = '- Success. ' + LAST_MSG
KILLED_MSG = '- Killed. ' + LAST_MSG

SETTINGS_PAT = re.compile(SETTINGS_MSG.format(r'(.*)', r'(\d+)', r'(\d+)\n'))
IO_ERROR_PAT = re.compile(IO_ERROR_MSG.format('(\d+)'))
BLOCK_PAT = re.compile(BLOCK_MSG.format('(\d+)'))


# SIGINT sets kill to True

kill = False
def sighandler(signum, frame):
    global kill
    kill = True

signal.signal(signal.SIGINT, sighandler)


class IncorrectBlockError(IOError):
    ''' Block value was not correct '''
    result = None
    expected = None
    possible = None


class WriteError(IOError):
    ''' Write failed '''
    def __init__(self, prev, block, uint):
        super(WriteError, self).__init__()
        self.prev = prev
        self.block = block
        self.uint = uint
        self.args = prev, block, uint

def log_event(fd, msg):
    now = time.time()
    timestamp = 'UTC[{}] LOC[{}] '.format(datetime.utcfromtimestamp(now), datetime.fromtimestamp(now))
    fd.write(timestamp + msg + '\n')

def get_uints(start, end, wrap):
    ''' get a series of uints wrapped at wrap '''
    return (n % wrap for n in six.moves.xrange(start, end))


def get_bytes(start, end, wrap):
    ''' get the bytes of uints put together '''
    uints = get_uints(start, end, wrap)
    return struct.pack(ENDIAN + str(int(end - start)) + 'H', *uints)


def validate_block(fd, bs, wrap, block, uint):
    ''' validate the block given the uint at the beginning'''
    new_uint = uint + int(bs / 2)
    expected = get_bytes(uint, new_uint, wrap)
    result = os.read(fd, bs)
    if not expected == result:
        err = IncorrectBlockError('block=' + str(block))
        err.result, err.expected = result, expected
        raise err
    return new_uint


def write_block(fd, uint, bs, wrap, block, last_uint=None):
    ''' write a block. If last_uint is not None, validate before overwritting '''
    if last_uint is not None:
        last_uint = validate_block(fd, bs, wrap, block, last_uint)
        os.lseek(fd, -bs, os.SEEK_CUR)
    os.write(fd, get_bytes(uint, uint + int(bs / 2), wrap))
    os.fsync(fd)
    return last_uint


def write(file_path, bs=4096, blocks=1000, period=None, validate=False,
          timeout=None, total_blocks=None, log_path=LOGPATH):
    ''' Write data until there is a failure or timeout, wrap at least once.

    This function uses an ultra simple method to write blocks, simply writing sequential
    uint_16t values and keeping track of which block it is writing to.

    The operation of this function is kept in a log, and from that log the data that was
    written can be validated.
    '''
    assert bs % 1024 == 0, "bs must be divisible by 1024"
    start = time.time()
    uint = 0
    block = 0
    blocks_written = 0
    last_uint = None
    wrapped = False
    logfile = open(log_path, 'w', 1)
    fd = os.open(file_path, os.O_RDWR)
    # with open(file_path, 'wb+', bs) as fd, open(log_path, 'w', 1) as logfile:
    try:
        log_event(logfile, "- PID: {}".format(os.getpid()))
        log_event(logfile, SETTINGS_MSG.format(file_path, bs, blocks))
        while True:
            try:
                write_block(fd, uint, bs, UINT_MAX, block, last_uint)
            except IncorrectBlockError as e:
                log_event(logfile, INVALID_BLOCK_MSG.format(block))
                raise
            except IOError as err:
                log_event(logfile, IO_ERROR_MSG.format(block))
                raise WriteError(err, block, uint)

            # exit if done
            if total_blocks is not None:
                blocks_written += 1
                if blocks_written >= total_blocks:
                    break
            elif timeout is not None and time.time() - start >= timeout:
                break
            elif kill:
                break

            if last_uint is not None:
                last_uint = int((last_uint + bs / 2) % UINT_MAX)
            uint = int((uint + bs / 2) % UINT_MAX)
            block += 1
            if block >= blocks:
                if not wrapped:
                    log_event(logfile, WRAPPED_MSG)
                    wrapped = True
                    last_uint = 0 if validate else None
                block = 0
                os.lseek(fd, 0, os.SEEK_SET)
            if period:
                time.sleep(period)
        if kill:
            log_event(logfile, KILLED_MSG.format(block) + '\n')
        else:
            log_event(logfile, SUCCESS_MSG.format(block) + '\n')
    finally:
        os.close(fd)
        logfile.close()
    return block


def validate(fd, total_blocks, last_block, io_error=False, bs=4096):
    ''' validate data given the last block to be written and whether it failed '''
    assert isinstance(fd, int)
    assert bs % 1024 == 0, "bs must be divisible by 1024"
    struct_fmt = ENDIAN + str(int(bs / 2)) + 'H'

    # the block after the failed block is the "start" of the uint sequences
    block = int((last_block + 1) % total_blocks)
    very_first_uint = None  # the last uint before the block
    start_uint = None
    almost_finished = False
    while True:
        if kill:
            raise KeyboardInterrupt()
        os.lseek(fd, block * bs, os.SEEK_SET)
        raw = os.read(fd, bs)
        data = struct.unpack(struct_fmt, raw)
        if very_first_uint is None:
            # this is the first loop, use the first uint to
            # load the state
            very_first_uint = data[0]
            start_uint = very_first_uint

        expected = tuple(get_uints(start_uint, start_uint + int(bs / 2), UINT_MAX))
        if data != expected:
            if io_error and last_block == block:
                # spot where there was an io-error. It is possible the data was not written
                failed_uint = very_first_uint - int(bs / 2)
                if failed_uint < 0:
                    failed_uint += UINT_MAX
                expected_failed = get_uints(failed_uint, failed_uint + int(bs / 2), UINT_MAX)
                if data != expected_failed:
                    err = IncorrectBlockError('failed-block=' + str(block))
                    err.result, err.expected, err.possible = data, expected, expected_failed
                    raise err
            else:
                err = IncorrectBlockError('block=' + str(block))
                err.result, err.expected = data, expected
                raise err
        start_uint = int((data[-1] + 1) % UINT_MAX)
        block = int((block + 1) % total_blocks)
        if block == last_block:
            almost_finished = True
        elif almost_finished:
            return


def validate_log(log_path):
    ''' given a log file, validate the data '''
    with open(log_path, 'r') as fd:
        log_txt = fd.read()
    path, bs, total_blocks = SETTINGS_PAT.search(log_txt).groups()
    bs, total_blocks = int(bs), int(total_blocks)

    io_error = IO_ERROR_PAT.search(log_txt)
    if io_error:
        block = io_error.group(1)
    else:
        block = BLOCK_PAT.search(log_txt).group(1)
    block = int(block)

    if not re.search(WRAPPED_MSG, log_txt):
        # if we have not wrapped then we have only written to index block
        total_blocks = block + 1
    fd = os.open(path, os.O_RDONLY)
    try:
        validate(fd, total_blocks, last_block=block, io_error=bool(io_error), bs=bs)
    finally:
        os.close(fd)


def main(argv):
    parser = argparse.ArgumentParser(description='Run some IO and be able to detect and validate'
                                     ' failure')
    parser.add_argument('path', help='path to write-to or validate')
    parser.add_argument('-l', '--log', help='log to write or validate from. '
                        ' default=/tmp/dataloss.log')
    parser.add_argument('-v', '--validate', action='store_true',
                        help='validate using logfile provided')

    parser.add_argument('--bs', type=int, default=4096, help='block size default=4096')
    parser.add_argument('--blocks', type=int, default=1000, help='num of blocks before wrapping.'
                        ' default=1000')
    parser.add_argument('-a', '--auto-validate', action='store_true',
                        help='if set, data will be validated while writting takes place')
    parser.add_argument('--period', type=float, help='period between writes. default=0')
    parser.add_argument('--timeout', type=float, help='time in seconds to write. default=inf')
    parser.add_argument('--total-blocks', type=int, help='total number of blocks to write'
                        ' default=inf')

    args = parser.parse_args(argv[1:])
    logpath = args.log or LOGPATH
    if args.validate:
        try:
            validate_log(logpath)
        except IncorrectBlockError as err:
            print('ERROR:', err, file=sys.stderr)
            sys.exit(2)
        except Exception as err:
            print('ERROR: log at', logpath, 'is not complete:',
                  repr(err), file=sys.stderr)
            sys.exit(3)
    else:
        try:
            write(args.path, args.bs, args.blocks, args.period, args.auto_validate,
                  args.timeout, args.total_blocks, logpath)
        except IncorrectBlockError as err:
            print('ERROR:', err, file=sys.stderr)
            sys.exit(2)
        except WriteError as err:
            print('ERROR:', repr(err), file=sys.stderr)
            sys.exit(1)

if __name__ == '__main__':
    main(sys.argv)
