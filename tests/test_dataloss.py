
import os
import unittest
import tempfile

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
