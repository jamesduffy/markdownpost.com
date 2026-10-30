"""Public help pages. Nothing here reads request.user or the database: every response is the same for everyone
(only the site's own address, taken from the request, differs), so it is safe to cache."""

import hashlib

from django.core.cache import cache
from django.http import Http404, HttpResponse, HttpResponseNotModified
from django.shortcuts import render
from django.utils.cache import patch_cache_control
from django.views.decorators.http import require_safe

from posts.render import render_document

from . import content, registry

MAX_AGE = 300


def _page_or_404(slug):
    page = registry.BY_SLUG.get(slug)
    if page is None:
        raise Http404
    return page


def _text_response(request, text, content_type):
    """A text body with an ETag and a short public cache lifetime (it is identical for every visitor)."""
    etag = content.etag_for(text)
    if request.headers.get("If-None-Match") == etag:
        response = HttpResponseNotModified()
    else:
        response = HttpResponse(text, content_type=content_type)
    response["ETag"] = etag
    patch_cache_control(response, public=True, max_age=MAX_AGE)
    return response


def _render(md):
    key = "help:" + hashlib.sha256(md.encode("utf-8")).hexdigest()
    doc = cache.get(key)
    if doc is None:
        doc = render_document(md)
        cache.set(key, doc, 3600)
    return doc


@require_safe
def index(request):
    origin = content.origin_of(request)
    response = render(request, "helpdocs/index.html", {"groups": registry.grouped(), "origin": origin})
    patch_cache_control(response, private=True, max_age=MAX_AGE)  # the menu in the page header knows who is signed in
    return response


@require_safe
def page(request, slug):
    pg = _page_or_404(slug)
    origin = content.origin_of(request)
    markdown = content.source(pg, origin)
    doc = _render(content.strip_title(markdown))
    toc = [t for t in doc.toc if t["level"] in (2, 3)]
    prev_page, next_page = registry.neighbours(pg)
    context = {
        "page": pg,
        "doc": doc,
        "toc": toc if len(toc) >= 3 else [],
        "markdown": markdown,
        "groups": registry.grouped(),
        "prev_page": prev_page,
        "next_page": next_page,
        "origin": origin,
        "has_rich": 'class="math' in doc.html or 'class="mermaid' in doc.html,
    }
    response = render(request, "helpdocs/page.html", context)
    patch_cache_control(response, private=True, max_age=MAX_AGE)
    return response


@require_safe
def page_markdown(request, slug):
    pg = _page_or_404(slug)
    return _text_response(request, content.source(pg, content.origin_of(request)), "text/markdown; charset=utf-8")


@require_safe
def all_markdown(request):
    return _text_response(request, content.all_source(content.origin_of(request)), "text/markdown; charset=utf-8")


@require_safe
def llms_txt(request):
    return _text_response(request, content.llms_txt(content.origin_of(request)), "text/plain; charset=utf-8")
