"""Requests PR #2148 / SWE-bench Lite psf__requests-2148.

A socket.error during Response.iter_content should be converted to
requests.exceptions.ConnectionError.

Before: the raw socket error escapes through requests/models.py.
After: Requests wraps the socket error, so the exception is caught here.

No real network or server is needed.
"""

import socket

from requests import Response
from requests.exceptions import ConnectionError as RequestsConnectionError


class ResettingStream:
    def stream(self, *args, **kwargs):
        raise socket.error(104, "Connection reset by peer")
        yield b"unreachable"  # ensure stream() is a generator


response = Response()
response.raw = ResettingStream()

try:
    list(response.iter_content(chunk_size=1))
except RequestsConnectionError:
    pass  # Expected Requests-level exception on the fixed commit.
