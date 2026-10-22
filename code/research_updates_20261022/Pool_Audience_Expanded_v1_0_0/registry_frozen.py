"""Read only the existing dated positive list; no download functions."""
import json, re, urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from common import TITLES, sha
USER_RE = re.compile(r"^[a-z0-9_-]{2,30}$", re.I)
BASE = "https://lichess.org"

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
