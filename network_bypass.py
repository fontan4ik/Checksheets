"""HTTP adapters for bypassing macOS Network Extension VPN routes safely."""

from __future__ import annotations

import socket
import sys

from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection
from urllib3.poolmanager import PoolManager


# Darwin's IP_BOUND_IF is not exposed by every Python build, but its stable
# socket option value is defined by macOS as 25.
_DARWIN_IP_BOUND_IF = 25


class SourceAddressAdapter(HTTPAdapter):
    """Bind HTTP connections to a physical interface on macOS.

    A source-address-only bind is rejected by full-tunnel Network Extension
    clients such as Happ.  On macOS, IP_BOUND_IF provides the same behavior as
    ``curl --interface en1``.  Other platforms retain the previous source-IP
    behavior.
    """

    def __init__(self, source_ip: str, interface_name: str | None = None, **kwargs):
        self._source_address = (source_ip, 0)
        self._interface_name = interface_name
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        if sys.platform == "darwin" and self._interface_name:
            interface_index = socket.if_nametoindex(self._interface_name)
            pool_kwargs["socket_options"] = list(HTTPConnection.default_socket_options) + [
                (socket.IPPROTO_IP, _DARWIN_IP_BOUND_IF, interface_index),
            ]
        else:
            pool_kwargs["source_address"] = self._source_address

        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs,
        )
