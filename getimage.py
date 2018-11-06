#!/usr/bin/env pypy3
"""
    Reynir: Natural language processing for Icelandic

    Image retrieval module

    Copyright (c) 2016 Vilhjalmur Thorsteinsson
    All rights reserved
    See the accompanying README.md file for further licensing and copyright information.

    This module contains a function that retrieves the URL of an image corresponding to
    a (person) name. It uses a Google API on top of the Google Custom Search feature.

    Retrieved image information is cached in the database.

"""

import sys
import json
import urllib.request
import urllib.parse
from urllib.error import HTTPError
from datetime import datetime, timedelta
from collections import namedtuple
from contextlib import closing
from scraperdb import SessionContext, Link, Person


def _server_query(url, q):
    """ Query a server via HTTP GET with a URL-encoded query string obtained from the dict q """
    doc = None
    if len(q):
        url += "?" + urllib.parse.urlencode(q)
    try:
        with closing(urllib.request.urlopen(url)) as response:
            if response:
                # Decode the HTML Content-type header to obtain the
                # document type and the charset (content encoding), if specified
                encoding = 'ISO-8859-1'
                ctype = response.getheader("Content-type", "")
                if ';' in ctype:
                    s = ctype.split(';')
                    ctype = s[0]
                    enc = s[1].strip()
                    s = enc.split('=')
                    if s[0] == "charset" and len(s) == 2:
                        encoding = s[1]
                if ctype == "application/json":
                    doc = response.read() # doc is a bytes object
                    if doc:
                        doc = doc.decode(encoding)
    except HTTPError as ex:
        logging.warning("server_query exception: {0}".format(ex))
    return doc


# The Custom Search identifier
_CX = "001858240983628375092:9aogptqla5e"
# The Google API identifier (you must obtain your own key if you want to use this code)
_API_KEY = ""
# The content type we're using in the links table
_CTYPE = "image-search-"
# Time (in days) before cached items expire
_CACHE_EXPIRATION_DAYS = 14
# The returned image descriptor tuple
Img = namedtuple('Img', ['src', 'width', 'height', 'link', 'origin', 'name'])

def get_image_url(name, size="large", enclosing_session=None, from_cache=True):
    """ Use Google Custom Search API to obtain an image corresponding to a (person) name """
    jdoc = None
    ctype = _CTYPE + size

    with SessionContext(commit=True, session=enclosing_session) as session:

        if from_cache:
            q = session.query(Link.content, Link.timestamp) \
                .filter(Link.ctype == ctype) \
                .filter(Link.key == name) \
                .one_or_none()
            if q is not None:
                # Found in cache
                if datetime.utcnow() - q.timestamp > timedelta(days=_CACHE_EXPIRATION_DAYS):
                    _purge_single(name, ctype=ctype, session=session)
                else:
                    jdoc = q.content

        if not jdoc:
            # Not found in cache: prepare to ask Google
            global _API_KEY
            if not _API_KEY:
                try:
                    # Read the Google API key from a server file
                    # You need to obtain your own key if you want to use this code
                    with open("resources/GoogleServerKey.txt") as f:
                        _API_KEY = f.read().rstrip()
                except FileNotFoundError as ex:
                    _API_KEY = ""

            if not _API_KEY:
                # No API key: can't ask for an image
                logging.warning("No API key for image lookup")
                return None

            # Assemble the query parameters
            q = dict(
                q = '"' + name + '"', # Try for an exact match
                num = 1,
                start = 1,
                imgSize = size,
                searchType = "image",
                cx = _CX,
                key = _API_KEY
            )
            jdoc = _server_query("https://www.googleapis.com/customsearch/v1", q)
            if jdoc:
                # Store in the cache
                l = Link(
                    ctype = ctype,
                    key = name,
                    content = jdoc,
                    timestamp = datetime.utcnow()
                )
                session.add(l)

    if not jdoc:
        return None

    answer = json.loads(jdoc)

    if answer and "items" in answer and answer["items"] and "link" in answer["items"][0]:
        # Answer looks legit
        item = answer["items"][0]
        image = item["image"]

        return Img(item["link"], image["width"], image["height"], 
                image["contextLink"], item["displayLink"], name)

    # No answer that makes sense
    return None

def update_broken_image_url(name, url):
    """ Refetch image URL for name if broken """

    # Verify that URL w. name exists in DB
    # TODO: content column should be converted to jsonb
    # from varchar to query faster & more intelligently
    with SessionContext() as session:
        r = session.query(Link) \
            .filter(Link.key == name) \
            .filter(Link.content.like('%'+url+'%')) \
            .one_or_none()

        # If not recently updated...
        if r and r.timestamp < datetime.utcnow() - timedelta(minutes=30):
            # Verify that URL is indeed broken
            if not check_image_url(url):
                # Purge from cache and refetch
                _purge_single(name, ctype=r.ctype)
                return get_image_url(name)

    return None

def check_image_url(url):
    """ Check if image exists at URL by sending HEAD request """
    req = urllib.request.Request(url, method="HEAD")
    try:
        response = urllib.request.urlopen(req, timeout=2.0)
        return (response.status == 200)
    except:
        pass
    
    return False

def _purge():
    """ Remove all cache entries """
    if input("Purge all cached data? (y/n): ").lower().startswith('y'):
        with SessionContext(commit=True) as session:
            session.query(Link).delete()

def _purge_single(key, ctype=None, enclosing_session=None):
    """ Remove cache entry """
    with SessionContext(commit=True, session=enclosing_session) as session:
        filters = [Link.key == key]
        if ctype:
            filters.append(Link.ctype == ctype)

        session.query(Link) \
        .filter(*filters) \
        .delete()

def _test():
    """ Test image lookup """
    print("Testing...")
    print("Bjarni Benediktsson")
    img = get_image_url("Bjarni Benediktsson")
    print("{0}".format(img))

    print("Vilhjálmur Þorsteinsson")
    img = get_image_url("Vilhjálmur Þorsteinsson")
    print("{0}".format(img))

    print("Blængur Klængsson Eyfjörð")
    img = get_image_url("Blængur Klængsson Eyfjörð")
    print("{0}".format(img)) # Should be None


if __name__ == "__main__":

    cmap = {
        "test": _test,
        "purge": _purge,
    }

    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"

    if cmd in cmap.keys():
        cmap[cmd]()
    elif cmd:
        # Any other arg is a name to fetch an image for
        img = get_image_url(cmd, from_cache=False)
        print("{0}".format(img))
               

