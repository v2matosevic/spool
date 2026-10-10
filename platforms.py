"""Discover installed extractor support without pretending every URL was live-tested."""
from functools import lru_cache

from yt_dlp.extractor import gen_extractor_classes

FEATURED = [
    ('YouTube', 'Videos & Shorts', 'youtube.com'),
    ('TikTok', 'Videos & clean playback sources', 'tiktok.com'),
    ('Instagram', 'Posts & Reels', 'instagram.com'),
    ('Facebook', 'Videos & Reels', 'facebook.com'),
    ('Twitter', 'X / Twitter videos', 'x.com'),
    ('Reddit', 'Native videos & linked media', 'reddit.com'),
    ('Vimeo', 'Public videos', 'vimeo.com'),
    ('Twitch', 'Clips & recorded streams', 'twitch.tv'),
    ('Dailymotion', 'Public videos', 'dailymotion.com'),
    ('Pinterest', 'Video pins', 'pinterest.com'),
    ('Bluesky', 'Video posts', 'bsky.app'),
    ('Bilibili', 'Public videos', 'bilibili.com'),
    ('Soundcloud', 'Audio tracks', 'soundcloud.com'),
    ('Snapchat', 'Public stories & Spotlight', 'snapchat.com'),
    ('LinkedIn', 'Public videos', 'linkedin.com'),
    ('Rumble', 'Public videos', 'rumble.com'),
    ('Streamable', 'Video links', 'streamable.com'),
    ('Bandcamp', 'Audio tracks', 'bandcamp.com'),
]


@lru_cache(maxsize=1)
def catalog():
    result = []
    for extractor in gen_extractor_classes():
        if extractor.IE_DESC is False or extractor.IE_NAME == 'generic':
            continue
        result.append({'name':extractor.IE_NAME, 'description':extractor.IE_DESC or extractor.IE_NAME,
                       'available':extractor.working()})
    return sorted(result, key=lambda item:item['name'].lower())


def platform_data(query='', limit=80):
    entries = catalog()
    term = query.strip().lower()
    matches = [entry for entry in entries if term in (entry['name'] + ' ' + entry['description']).lower()]
    featured = [{'name':name, 'description':description, 'domain':domain}
                for name, description, domain in FEATURED
                if any(name.lower() in entry['name'].lower() and entry['available'] for entry in entries)]
    featured.insert(2,{'name':'Spotify','description':'Song links · audio matched on YouTube','domain':'open.spotify.com'})
    if not term or 'spotify' in term or term in 'spotify':
        matches = [{'name':'Spotify tracks','description':'Spotify metadata with matched YouTube audio (spotDL)','available':__import__('spotify_support').ready()},*matches]
    return {'total':len(entries), 'matched':len(matches), 'results':matches[:max(1,min(limit,200))],
            'featured':featured, 'note':'Extractor support, not a live availability guarantee. Individual video links only.'}
