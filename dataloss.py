import sys
import os
import time
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

FAILED_MSG = 'Failed at block: {}'
LAST_MSG = 'Last block: {}'
SETTINGS_MSG = '- Settings: {} {}'
WRAPPED_MSG = '- Wrapped'
INVALID_BLOCK_MSG = '- Invalid block. ' + FAILED_MSG
IO_ERROR_MSG = '- IO Error. ' + FAILED_MSG
SUCCESS_MSG = '- Success. ' + LAST_MSG
KILLED_MSG = '- Killed. ' + LAST_MSG

SETTINGS_PAT = re.compile(SETTINGS_MSG.format(r'(.*)', r'(\d+)' + '\n'))
FAILED_PAT = re.compile(FAILED_MSG.format('(\d+)'))
SUCCESS_PAT = re.compile(LAST_MSG.format('(\d+)'))


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
    def __init__(self, block, uint):
        super(WriteError, self).__init__()
        self.block = block
        self.uint = uint
        self.args = block, uint


def get_uints(start, end, wrap):
    ''' get a series of uints wrapped at wrap '''
    return (n % wrap for n in six.moves.xrange(start, end))


def get_bytes(start, end, wrap):
    ''' get the bytes of uints put together '''
    uints = get_uints(start, end, wrap)
    return struct.pack(ENDIAN + str(int(end - start)) + 'H', *uints)


def validate_block(fd, bs, wrap, uint):
    ''' validate the block given the uint at the beginning'''
    new_uint = uint + int(bs / 2)
    expected = get_bytes(uint, new_uint, wrap)
    result = fd.read(bs)
    if not expected == result:
        err = IncorrectBlockError()
        err.result, err.expected = result, expected
        raise err
    return new_uint


def write_block(fd, uint, bs, wrap, last_uint=None):
    ''' write a block. If last_uint is not None, validate before overwritting '''
    if last_uint is not None:
        loc = fd.tell()
        last_uint = validate_block(fd, bs, wrap, last_uint)
        fd.seek(loc)
    fd.write(get_bytes(uint, uint + int(bs / 2), wrap))
    os.fsync(fd)
    return last_uint



def write(file_path, bs=4096, blocks=1000, period=0.01, validate=False,
          timeout=None, total_blocks=None, log_path=LOGPATH):
    ''' Write data until there is a failure or timeout, wrap at least once '''
    assert bs % 2 == 0
    start = time.time()
    uint = 0
    block = 0
    blocks_written = 0
    last_uint = None
    wrapped = False
    with open(file_path, 'wb+', bs) as fd, open(log_path, 'w', 1) as logfile:
        logfile.write(SETTINGS_MSG.format(file_path, bs) + '\n')
        while True:
            try:
                write_block(fd, uint, bs, UINT_MAX, last_uint)
            except IncorrectBlockError as e:
                logfile.write(INVALID_BLOCK_MSG.format(block) + '\n')
                raise
            except IOError:
                logfile.write(IO_ERROR_MSG.format(block) + '\n')
                raise WriteError(block, uint)

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
                    logfile.write(WRAPPED_MSG + '\n')
                    wrapped = True
                    last_uint = 0 if validate else None
                block = 0
                fd.seek(0)
            if period:
                time.sleep(period)
        if kill:
            logfile.write(KILLED_MSG.format(block) + '\n')
        else:
            logfile.write(SUCCESS_MSG.format(block) + '\n')
    return block


def validate(fd, last_block=None, last_failed=False, bs=4096):
    ''' validate data given the last block to be written and whether it failed '''
    file_size = os.path.getsize(fd.name)
    assert file_size % bs == 0
    assert bs % 2 == 0
    total_blocks = int(file_size / bs)
    struct_fmt = ENDIAN + str(int(bs / 2)) + 'H'

    # the first block to check is the block after the failed block
    block = int((last_block + 1) % total_blocks) if last_block is not None else 0
    very_first_uint = None  # the last uint before the block
    start_uint = None
    while True:
        if kill:
            raise InterruptedError()
        fd.seek(block * bs)
        data = struct.unpack(struct_fmt, fd.read(bs))
        if very_first_uint is None:
            very_first_uint = data[0]
        else:
            expected = tuple(get_uints(start_uint, start_uint + int(bs / 2), UINT_MAX))
            if data != expected:
                if last_failed and last_block == block:
                    # spot where there was a failure, it is possible the data was not written
                    failed_uint = very_first_uint - int(bs / 2)
                    if failed_uint < 0:
                        failed_uint += UINT_MAX
                    expected_failed = get_uints(failed_uint, failed_uint + int(bs / 2), UINT_MAX)
                    if data != expected_failed:
                        err = IncorrectBlockError("invalid failed block")
                        err.result, err.expected, err.possible = data, expected, expected_failed
                        raise err
                else:
                    err = IncorrectBlockError()
                    err.result, err.expected = data, expected
                    raise err
        start_uint = int((data[-1] + 1) % UINT_MAX)
        block = int((block + 1) % total_blocks)
        if block == last_block:
            return


def validate_log(log_path):
    with open(log_path, 'r') as fd:
        log_txt = fd.read()
    path, bs = SETTINGS_PAT.search(log_txt).groups()
    bs = int(bs)
    wrapped = re.search(WRAPPED_MSG, log_txt)
    assert wrapped

    failed = FAILED_PAT.search(log_txt)
    if failed:
        block = failed.group(1)
    else:
        block = SUCCESS_PAT.search(log_txt).group(1)
    block = int(block)
    with open(path, 'rb') as fd:
        validate(fd, last_block=block, last_failed=bool(failed), bs=bs)


def main(argv):
    parser = argparse.ArgumentParser(description='Run some IO and be able to detect and validate'
                                     ' failure')
    parser.add_argument('path', help='path to write-to or validate')
    parser.add_argument('-l', '--log', help='log to write or validate from')
    parser.add_argument('-v', '--validate', action='store_true',
                        help='validate using logfile provided')

    parser.add_argument('--bs', type=int, default=4096, help='block size default=4096')
    parser.add_argument('--blocks', type=int, default=1000, help='num of blocks before wrapping')
    parser.add_argument('-a', '--auto-validate', action='store_true',
                        help='if set, data will be validated while writting takes place')
    parser.add_argument('--period', type=float, default=0, help='period between writes')
    parser.add_argument('--timeout', type=float, help='time in seconds to write')
    parser.add_argument('--total-blocks', type=int, help='total number of blocks to write')

    args = parser.parse_args(argv[1:])
    if args.validate:
        try:
            validate_log(args.log)
        except IncorrectBlockError as err:
            print('ERROR:', err)
            sys.exit(2)
    else:
        try:
            write(args.path, args.bs, args.blocks, args.period, args.auto_validate,
                args.timeout, args.total_blocks, args.log)
        except IncorrectBlockError as err:
            print('ERROR:', err)
            sys.exit(2)
        except WriteError as err:
            print('ERROR:', err)
            sys.exit(1)

if __name__ == '__main__':
    main(sys.argv)
