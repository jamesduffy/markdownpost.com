"""/sitemap.xml: discoverable posts and the profiles of authors who have at least one (same gate as Discover, feeds
and search; drafts, unlisted and private posts never appear). Django's sitemap index splits it into pages of at most
50,000 URLs."""

from django.contrib.auth import get_user_model
from django.contrib.sitemaps import Sitemap
from django.conf import settings
from django.db.models import Max
from django.urls import reverse

from . import scheduling, tags
from .models import Post

User = get_user_model()


class PostSitemap(Sitemap):
    limit = 50000
    protocol = None  # follow the request (https behind the proxy)

    def items(self):
        scheduling.maybe_publish_due()
        return Post.objects.discoverable().select_related("author").order_by("-created_at", "-pk")

    def lastmod(self, post):
        return post.updated_at


class ProfileSitemap(Sitemap):
    limit = 50000

    def items(self):
        authors = Post.objects.discoverable().values("author").annotate(last=Max("updated_at")).values("author", "last")
        last = {row["author"]: row["last"] for row in authors}
        users = list(User.objects.filter(pk__in=last).order_by("username"))
        for user in users:
            user.sitemap_lastmod = last[user.pk]
        return users

    def location(self, user):
        return reverse("profile", args=[user.username])

    def lastmod(self, user):
        return user.sitemap_lastmod


class TagSitemap(Sitemap):
    """Tag pages only once they have TAG_MIN_POSTS discoverable posts (the same bar that lifts their noindex)."""

    limit = 50000

    def items(self):
        return list(tags.listed_tags(settings.TAG_MIN_POSTS))

    def location(self, tag):
        return reverse("tag_page", args=[tag.slug])

    def lastmod(self, tag):
        return tag.touched


SITEMAPS = {"posts": PostSitemap, "profiles": ProfileSitemap, "tags": TagSitemap}
