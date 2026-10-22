"""Read-only, resumable acquisition of the PUBLIC streamer listing.

This is a dated positive list, not an exhaustive census or stream history.
No account profiles are downloaded. API profile data are read from local files.
"""
from __future__ import annotations
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from common import atomic_json, log, now, sha, TITLES

USER_RE = re.compile(r'^[a-z0-9_-]{2,30}$', re.I)
BASE = 'https://lichess.org'

class DirectoryParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.users = {}
        self.next_url = None
        self.article = None
        self.capture_title = False
        self.title_text = ''
        self.paginated = set()
        self.listing_container = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if 'streamer-list' in a.get('class', '').split():
            self.listing_container = True
        if tag == 'article' and 'streamer' in a.get('class', '').split():
            self.article = {'id': None, 'title': '', 'paginated': 'paginated' in a.get('class', '').split()}
        if tag == 'a' and a.get('rel') == 'next':
            self.next_url = urllib.parse.urljoin(BASE, a.get('href', ''))
        if self.article is None:
            return
        if tag == 'a' and 'overlay' in a.get('class', '').split():
            path = urllib.parse.urlparse(a.get('href', '')).path
            match = re.fullmatch(r'/streamer/([A-Za-z0-9_-]+)', path)
            if match:
                self.article['id'] = match.group(1).lower()
        if tag == 'span' and 'utitle' in a.get('class', '').split():
            self.capture_title = True
            self.title_text = ''

    def handle_data(self, data):
        if self.capture_title:
            self.title_text += data

    def handle_endtag(self, tag):
        if tag == 'span' and self.capture_title:
            if self.article is not None and self.title_text.strip().upper() in TITLES:
                self.article['title'] = self.title_text.strip().upper()
            self.capture_title = False
        if tag == 'article' and self.article is not None:
            uid = self.article['id']
            if uid and USER_RE.fullmatch(uid):
                self.users[uid] = self.article['title']
                if self.article['paginated']:
                    self.paginated.add(uid)
            self.article = None

def parse_directory(data):
    p = DirectoryParser()
    p.feed(data.decode('utf-8'))
    if not p.users and not p.listing_container:
        raise RuntimeError('Not a recognizable streamer directory response')
    if p.next_url:
        u = urllib.parse.urlparse(p.next_url)
        if u.scheme != 'https' or u.netloc != 'lichess.org' or u.path != '/streamer':
            raise RuntimeError('Unexpected directory pagination URL')
    return p

def download(url, delay=1.5):
    # Only the public directory is fetched. Single worker; honor server backoff.
    for attempt in range(8):
        try:
            request = urllib.request.Request(url, headers={
                'User-Agent': 'LichessKindnessAudienceAudit/1.0 (public directory research)',
                'Accept': 'text/html',
            })
            with urllib.request.urlopen(request, timeout=45) as response:
                if response.geturl().split('?')[0] != BASE + '/streamer':
                    raise RuntimeError('Directory request redirected away from the listing')
                data = response.read()
            time.sleep(delay)
            return data
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
            try:
                pause = max(60, int(e.headers.get('Retry-After', '60')))
            except ValueError:
                pause = 60
        except (urllib.error.URLError, TimeoutError):
            pause = min(60, 5 * (attempt + 1))
        log(f'Directory request retry {attempt+1}/8; waiting {pause}s')
        # Short waits keep a running terminal responsive.
        remaining = pause
        while remaining:
            step = min(30, remaining)
            time.sleep(step)
            remaining -= step
    raise RuntimeError('Directory acquisition failed after eight attempts; rerun to resume')

def collect_directory(cache, max_pages=400):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    manifest = cache / 'directory_manifest.json'
    if manifest.exists():
        info = json.loads(manifest.read_text())
        for item in info['pages']:
            if sha(cache / item['file']) != item['sha256']:
                raise RuntimeError('Cached streamer-directory hash mismatch')
        if info.get('pagination_completed'):
            log(f"Reusing frozen directory snapshot: {info['unique_users']} listed accounts")
            return reconstruct_directory(cache, info)
    else:
        info = {'started_utc': now(), 'pages': [], 'pagination_completed': False}
    users = {}
    next_url = BASE + '/streamer?page=1'
    # Page bodies and acquisition times are checkpointed independently, so an
    # interruption does not lose completed downloads or silently redate them.
    for page in range(1, max_pages + 1):
        filename = f'page_{page:04d}.html'
        path = cache / filename
        meta_path = cache / f'page_{page:04d}.json'
        if path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text())
            if meta['url'] != next_url or meta['sha256'] != sha(path):
                raise RuntimeError('Partial directory checkpoint differs; use a new cache directory')
            data = path.read_bytes()
        else:
            data = download(next_url)
            parser = parse_directory(data)
            if page == 1 and not parser.users:
                raise RuntimeError('First directory page has no recognizable accounts')
            tmp = path.with_suffix('.tmp')
            tmp.write_bytes(data)
            tmp.replace(path)
            meta = {'file': filename, 'url': next_url, 'fetched_utc': now(),
                    'sha256': hashlib.sha256(data).hexdigest()}
            atomic_json(meta_path, meta)
        parser = parse_directory(data)
        for uid, title in parser.users.items():
            users[uid] = title or users.get(uid, '')
        if len(info['pages']) < page:
            info['pages'].append(meta)
        info['unique_users'] = len(users)
        info['last_page_utc'] = meta['fetched_utc']
        if page == 1 or page % 25 == 0:
            log(f'Directory: {page} pages, {len(users):,} distinct listed accounts')
        if not parser.next_url:
            info['pagination_completed'] = True
            info['completed_utc'] = now()
            info['scope'] = 'Public paginated listing, including live cards; not all streamers'
            info['limitation'] = ('Current source code advertises 1000 non-live results; ranking changes '
                                 'during acquisition. Historical, unlisted and off-platform streams are not censused.')
            atomic_json(manifest, info)
            return users, info
        atomic_json(manifest, info)
        next_url = parser.next_url
    raise RuntimeError('Directory pagination did not finish within max-pages; no completed snapshot written')

def reconstruct_directory(cache, info):
    users = {}
    for item in info['pages']:
        parser = parse_directory((cache / item['file']).read_bytes())
        for uid, title in parser.users.items():
            users[uid] = title or users.get(uid, '')
    if len(users) != info['unique_users']:
        raise RuntimeError('Directory reconstruction count differs')
    return users, info

def read_extra_streamers(path):
    # Optional positive list of Lichess usernames, NOT Twitch channel names.
    import csv
    path = Path(path)
    if not path.exists():
        return {}, None
    users = {}
    with path.open(newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'username', 'source_url'} <= set(reader.fieldnames or []):
            raise ValueError('Extra streamer CSV requires username,source_url columns')
        for row in reader:
            uid = row['username'].strip().lower()
            if not uid:
                continue
            if not USER_RE.fullmatch(uid) or not row['source_url'].strip():
                raise ValueError('Extra streamer rows need a valid Lichess username and evidence URL')
            users[uid] = ''
    return users, {'sha256': sha(path), 'rows': len(users), 'scope': 'User-supplied positive list'}
