import hashlib, re, requests, yt_dlp
from flask import Flask, request, Response, jsonify, send_from_directory

app = Flask(__name__)
CACHE = {}

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

def best(videos):
    # videos: {'720p': [urls], ...} -> url of highest quality
    key = lambda k: int((re.match(r'\d+', k) or re.match(r'0', '0')).group())
    k = max(videos, key=key)
    u = videos[k]
    return (u[0] if isinstance(u, list) else u)

def from_rezka(url, s, e):
    from HdRezkaApi import HdRezkaApi
    r = HdRezkaApi(url)
    if not r.ok:
        raise Exception('rezka: ' + str(r.exception))
    st = r.getStream(s, e) if getattr(r, 'seriesInfo', None) else r.getStream()
    return best(st.videos), {}

def from_animelib(url, e):
    from anicli_api.source.anilib_me import Extractor
    m = re.search(r'/anime/\d+--([^/?#]+)', url)
    title = m.group(1).replace('-', ' ') if m else url
    anime = Extractor().search(title)[0].get_anime()
    ep = anime.get_episodes()[int(e) - 1]
    vids = ep.get_sources()[0].get_videos()
    v = max(vids, key=lambda x: int(x.quality or 0))
    if 'mpd' in str(v.type).lower():
        raise Exception('формат mpd, Safari не потянет')
    return v.url, dict(v.headers or {})

@app.route('/resolve')
def resolve():
    url = request.args.get('url', '')
    if not url.startswith('http'):
        return jsonify(error='плохая ссылка'), 400
    s_, e_ = request.args.get('s') or '1', request.args.get('e') or '1'
    try:
        low = url.lower()
        if 'rezka' in low or 'hdrezka' in low:
            direct, headers = from_rezka(url, s_, e_)
            vid = hashlib.md5((url + s_ + e_).encode()).hexdigest()[:12]
            if '.m3u8' in direct:
                return jsonify(mode='direct', direct=direct)
            CACHE[vid] = (direct, headers)
            return jsonify(mode='proxy', id=vid)
        if 'animelib' in low or 'anilib' in low:
            direct, headers = from_animelib(url, e_)
            vid = hashlib.md5((url + e_).encode()).hexdigest()[:12]
            if '.m3u8' in direct:
                return jsonify(mode='direct', direct=direct)
            CACHE[vid] = (direct, headers)
            return jsonify(mode='proxy', id=vid)
        opts = {'quiet': True, 'noplaylist': True,
                'format': 'best[protocol^=http][ext=mp4]/best[protocol^=http]/best'}
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)
        direct = info['url']
        headers = info.get('http_headers', {})
        vid = hashlib.md5(url.encode()).hexdigest()[:12]
        if '.m3u8' in direct or str(info.get('protocol', '')).startswith('m3u8'):
            return jsonify(mode='direct', direct=direct)
        CACHE[vid] = (direct, headers)
        return jsonify(mode='proxy', id=vid, title=info.get('title'))
    except Exception as e:
        return jsonify(error='сайт не отдаёт видео (' + str(e)[:80] + ')'), 422

@app.route('/stream/<vid>')
def stream(vid):
    if vid not in CACHE:
        return 'нет такого', 404
    u, h = CACHE[vid]
    h = dict(h)
    if 'Range' in request.headers:
        h['Range'] = request.headers['Range']
    r = requests.get(u, headers=h, stream=True, timeout=20)
    out = Response(r.iter_content(65536), status=r.status_code)
    for k in ('Content-Type', 'Content-Length', 'Content-Range', 'Accept-Ranges'):
        if k in r.headers:
            out.headers[k] = r.headers[k]
    return out
