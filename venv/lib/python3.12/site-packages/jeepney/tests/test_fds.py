import errno
import os
import socket

import pytest

from jeepney import FileDescriptor, NoFDError

def assert_not_fd(fd: int):
    """Check that the given number is not open as a file descriptor"""
    with pytest.raises(OSError) as exc_info:
        os.stat(fd)
    assert exc_info.value.errno == errno.EBADF


def test_close(tmp_path):
    fd = os.open(tmp_path / 'a', os.O_CREAT | os.O_RDWR)

    with FileDescriptor(fd) as wfd:
        assert wfd.fileno() == fd
    # Leaving the with block is equivalent to calling .close()

    assert 'closed' in repr(wfd)
    with pytest.raises(NoFDError):
        wfd.fileno()

    assert_not_fd(fd)


def test_to_raw_fd(tmp_path):
    fd = os.open(tmp_path / 'a', os.O_CREAT)
    wfd = FileDescriptor(fd)
    assert wfd.fileno() == fd

    assert wfd.to_raw_fd() == fd

    try:
        assert 'converted' in repr(wfd)
        with pytest.raises(NoFDError):
            wfd.fileno()
    finally:
        os.close(fd)


def test_to_file(tmp_path):
    fd = os.open(tmp_path / 'a', os.O_CREAT | os.O_RDWR)
    wfd = FileDescriptor(fd)

    with wfd.to_file('w') as f:
        assert f.write('abc')

    assert 'converted' in repr(wfd)
    with pytest.raises(NoFDError):
        wfd.fileno()

    assert_not_fd(fd)  # Check FD was closed by file object

    assert (tmp_path / 'a').read_text() == 'abc'


def test_to_socket():
    s1, s2 = socket.socketpair()
    try:
        s1.sendall(b'abcd')
        sfd = s2.detach()
        wfd = FileDescriptor(sfd)

        with wfd.to_socket() as sock:
            b = sock.recv(16)
            assert b and b'abcd'.startswith(b)

        assert 'converted' in repr(wfd)
        with pytest.raises(NoFDError):
            wfd.fileno()

        assert_not_fd(sfd)  # Check FD was closed by socket object
    finally:
        s1.close()


