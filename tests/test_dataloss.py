
import os
import time
import unittest
import tempfile
import random
import threading

import six

from .. import dataloss



get_uints = lambda *args: list(dataloss.get_uints(*args))


lrange = lambda *args: list(six.moves.range(*args))

class TestHelpers(unittest.TestCase):
    def test_uints(self):
        assert get_uints(0, 10, 100) == lrange(10)
        assert get_uints(10, 20, 100) == lrange(10, 20)
        assert get_uints(0, 20, 10) == lrange(10) * 2
        assert get_uints(0, 20, 7) == lrange(7) * 2 + lrange(6)

    def test_bytes(self):
        expected = b'\x00\x00\x00\x01\x00\x02'
        assert dataloss.get_bytes(0, 3, 10) == expected



class TestDataloss(unittest.TestCase):
    def setUp(self):
        self.fname = tempfile.mktemp()
        self.flog = tempfile.mktemp()

    def tearDown(self):
        if os.path.exists(self.fname):
            os.remove(self.fname)

        if os.path.exists(self.flog):
            os.remove(self.flog)

    def test_basic(self):
        num_blocks = 67
        block = dataloss.write(
            self.fname, blocks=num_blocks, period=0, validate=True,
            total_blocks=int(num_blocks * 9.3), log_path=self.flog)
        with open(self.fname, 'rb') as fd:
            dataloss.validate(fd, block)
        dataloss.validate_log(self.flog)

    def test_corrupt(self):
        num_blocks = 67
        bs = 4096
        block = dataloss.write(
            self.fname, bs=bs, blocks=num_blocks, period=0, validate=True,
            total_blocks=int(num_blocks * 9.3), log_path=self.flog)
        # validate it is correct
        with open(self.fname, 'rb') as fd:
            dataloss.validate(fd, block)
        seekto = block * bs + 10  # do at least one inside the block
        for _ in range(5):
            # corrupt the data a tiny bit
            with open(self.fname, 'rb+') as fd:
                fd.seek(seekto)
                value = ord(fd.read(1))
                fd.seek(seekto)
                fd.write(bytearray([int((value + 1) % 255)]))
                os.fsync(fd)
            with self.assertRaises(dataloss.IncorrectBlockError):
                with open(self.fname, 'rb') as fd:
                    dataloss.validate(fd, block)
            with open(self.fname, 'rb+') as fd:
                fd.seek(seekto)
                fd.write(bytearray([value]))
                os.fsync(fd)
            with open(self.fname, 'rb') as fd:
                dataloss.validate(fd, block)
            seekto = random.randint(0, (num_blocks - 1) * 4096)

    def test_simultanious_corrupt(self):
        kill = False
        num_blocks = 67
        bs = 4096
        def corrupt():
            ''' corrupt the file in a separate thread '''
            time.sleep(0.1)
            with open(self.fname, 'wb+') as fd:
                while not kill:
                    time.sleep(0.05)
                    fd.seek(random.randint(0, (num_blocks - 1) * bs))
                    fd.write(bytearray([random.randint(0, 255)]))
                    os.fsync(fd)

        corruptor = threading.Thread(target=corrupt)
        corruptor.start()
        try:
            with self.assertRaises(dataloss.IncorrectBlockError):
                dataloss.write(
                    self.fname, bs=bs, blocks=num_blocks, period=0, validate=True,
                    timeout=0.3, log_path=self.flog)
        finally:
            kill = True
            corruptor.join()


