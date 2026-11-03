"""Execution-only HTTP repair; the frozen parser and response cache are unchanged.

Cloudflare 520–524 are transient origin errors. A 524 gets a minimum 120-second
cooldown; explicit longer Retry-After values take precedence. TLS/authentication
failures remain fatal. Every logical request has a finite 12-attempt budget.
"""
import http.client
import os
import socket
import ssl
import time
import urllib.error
import urllib.request
import metadata_http as frozen

RETRYABLE = frozenset((408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524))
MINIMUM_DELAY = {429: 60, 500: 30, 502: 60, 504: 120,
                 520: 60, 521: 120, 522: 120, 523: 120, 524: 120}
MAX_ATTEMPTS = 12


def retry_delay(status, headers, attempt, now):
    return max(MINIMUM_DELAY.get(status, 0),
               frozen.delay(status, headers, attempt, now))


class Client(frozen.Client):
    """Reuse verified TLS setup and durable, interruptible server cooldowns."""
    def __init__(self, cooldown_path, opener=None, sleeper=time.sleep, clock=time.time):
        super().__init__(cooldown_path, opener=opener, sleeper=sleeper, clock=clock)
        self.failure_history = []

    def get(self, ids):
        if (not 1 <= len(ids) <= 300 or len(set(ids)) != len(ids)
                or any(not isinstance(g, str) or not frozen.GID.fullmatch(g) for g in ids)):
            raise RuntimeError('Invalid 1–300-ID request')
        headers = {'Accept': 'application/x-ndjson', 'Content-Type': 'text/plain',
                   'Accept-Encoding': 'identity', 'User-Agent': 'LichessKindnessMaterialResume/1.0.4'}
        token = os.environ.get('LICHESS_API_TOKEN') or os.environ.get('LICHESS_TOKEN')
        if token:
            headers['Authorization'] = 'Bearer ' + token.strip()
        request = urllib.request.Request(frozen.URL, data=','.join(ids).encode('ascii'),
                                         headers=headers, method='POST')
        for attempt in range(MAX_ATTEMPTS):
            self.wait()
            status = None
            error_headers = {}
            started = time.monotonic()
            try:
                self.requests += 1
                with self.opener(request, timeout=180, context=self.context) as response:
                    if response.status != 200:
                        raise RuntimeError('Unexpected HTTP status')
                    if 'ndjson' not in response.headers.get('Content-Type', '').lower():
                        raise RuntimeError('Expected NDJSON response')
                    raw = response.read(32 * 1024**2 + 1)
                if len(raw) > 32 * 1024**2:
                    raise RuntimeError('Metadata response exceeds 32 MiB limit')
                frozen.parse(raw, ids)
                return raw
            except ssl.SSLCertVerificationError:
                raise RuntimeError('TLS verification failed; verification remains enabled') from None
            except urllib.error.HTTPError as error:
                status, error_headers = error.code, error.headers
                error.close()
                if status not in RETRYABLE:
                    raise RuntimeError('HTTP ' + str(status) + '; completed requests remain saved') from None
            except urllib.error.URLError as error:
                if isinstance(error.reason, ssl.SSLCertVerificationError):
                    raise RuntimeError('TLS verification failed; verification remains enabled') from None
            except (TimeoutError, socket.timeout, ConnectionError,
                    http.client.IncompleteRead, http.client.RemoteDisconnected):
                pass
            finally:
                self.http_seconds += time.monotonic() - started
            pause = retry_delay(status, error_headers, attempt, self.clock())
            frozen.io.js(self.path, dict(until=self.clock() + pause))
            self.failure_history.append(dict(http_status=status, attempt=attempt + 1,
                                             wait_seconds=pause))
            if attempt + 1 < MAX_ATTEMPTS:
                frozen.io.log(f'Metadata HTTP {status}: waiting {pause:.0f}s before '
                              f'attempt {attempt + 2}/{MAX_ATTEMPTS}; completed work is saved')
        raise RuntimeError('Metadata retry limit reached after 12 attempts; cached work is retained. '
                           'Rerun the same command when the API is responding')
