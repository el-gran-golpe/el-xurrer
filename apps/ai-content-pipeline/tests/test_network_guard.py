import socket

import pytest


def test_tests_cannot_reach_an_external_host():
    with socket.socket() as sock:
        with pytest.raises(RuntimeError, match="reach the network"):
            sock.connect(("203.0.113.1", 443))  # TEST-NET-3, never routable
