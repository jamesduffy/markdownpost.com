import math
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import RateLimitEvent

from . import helpful, ranking, storage
from .models import Helpful, Post

User = get_user_model()
PW = "x-pass-12345"


def make_user(name, **kw):
    return User.objects.create_user(name, password=PW, **kw)


def make_post(author, title="A post", **kw):
    kw.setdefault("visibility", "public")
    kw.setdefault("is_draft", False)
    return Post.objects.create(author=author, title=title, **kw)


def vote_at(user, post, when):
    """Cast a vote as if it were `when` now (through the real code path)."""
    with mock.patch("django.utils.timezone.now", return_value=when):
        helpful.mark(user, post)


def rank_of(post):
    return Post.objects.get(pk=post.pk).helpful_rank


def order(qs=None):
    qs = qs if qs is not None else Post.objects.filter(visibility="public", is_draft=False)
    from django.db.models import F

    return list(qs.order_by(F("helpful_rank").desc(nulls_last=True), "-created_at", "-pk").values_list("title", flat=True))


class RankingMathTests(TestCase):
    def test_half_life_halves_a_votes_weight(self):
        now = timezone.now()
        for days in (1, 14, 100):
            older = ranking.rank_from_votes([now - timedelta(days=days)])
            newer = ranking.rank_from_votes([now])
            self.assertAlmostEqual(math.exp(older - newer), 0.5 ** (days / 14), places=9)

    @override_settings(HELPFUL_HALF_LIFE_DAYS=7)
    def test_half_life_setting_is_used(self):
        now = timezone.now()
        self.assertAlmostEqual(math.exp(ranking.rank_from_votes([now - timedelta(days=7)]) - ranking.rank_from_votes([now])), 0.5, places=9)

    def test_no_votes_is_none(self):
        self.assertIsNone(ranking.rank_from_votes([]))
        self.assertEqual(ranking.decayed_score(None, timezone.now()), 0.0)

    def test_incremental_equals_full_recompute(self):
        now = timezone.now()
        times = [now - timedelta(days=d, hours=h) for d, h in ((400, 3), (90, 1), (30, 7), (2, 2), (0, 1), (0, 0))]
        rank = None
        for t in times:
            rank = ranking.add_vote(rank, t)
        self.assertAlmostEqual(rank, ranking.rank_from_votes(times), places=9)

    def test_logaddexp_is_stable(self):
        self.assertAlmostEqual(ranking.logaddexp(1000.0, 1000.0), 1000.0 + math.log(2))
        self.assertAlmostEqual(ranking.logaddexp(1000.0, -1000.0), 1000.0)

    def test_order_is_time_invariant(self):
        """Ordering by the stored value equals ordering by the decayed score at any later moment."""
        now = timezone.now()
        a = ranking.rank_from_votes([now - timedelta(days=40)] * 20)
        b = ranking.rank_from_votes([now - timedelta(days=1)] * 2)
        for later in (now, now + timedelta(days=30), now + timedelta(days=900)):
            self.assertEqual(a > b, ranking.decayed_score(a, later) > ranking.decayed_score(b, later))

    def test_five_year_old_mass_loses_to_a_few_fresh_votes(self):
        now = timezone.now()
        old = ranking.rank_from_votes([now - timedelta(days=5 * 365)] * 100_000)
        fresh = ranking.rank_from_votes([now] * 2)
        self.assertLess(old, fresh)


class HelpfulModelTests(TestCase):
    def setUp(self):
        self.author = make_user("author")
        self.fan = make_user("fan")
        self.post = make_post(self.author)

    def test_unique_per_user_and_post(self):
        Helpful.objects.create(post=self.post, user=self.fan)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Helpful.objects.create(post=self.post, user=self.fan)

    def test_records_who_and_when(self):
        before = timezone.now()
        helpful.mark(self.fan, self.post)
        mark = Helpful.objects.get()
        self.assertEqual((mark.user, mark.post), (self.fan, self.post))
        self.assertTrue(before <= mark.created_at <= timezone.now())
        self.assertIn(self.post, self.fan.helpful_marks.values_list("post", flat=True) and [self.post])

    def test_mark_is_idempotent_and_does_not_touch_updated_at(self):
        updated = Post.objects.get(pk=self.post.pk).updated_at
        helpful.mark(self.fan, self.post)
        first = rank_of(self.post)
        helpful.mark(self.fan, self.post)
        self.assertEqual(Helpful.objects.count(), 1)
        self.assertEqual(rank_of(self.post), first)
        self.assertEqual(Post.objects.get(pk=self.post.pk).updated_at, updated)

    def test_cannot_mark_own_post(self):
        with self.assertRaises(helpful.HelpfulError):
            helpful.mark(self.author, self.post)
        self.assertEqual(Helpful.objects.count(), 0)

    def test_helpful_rank_not_editable_and_null_by_default(self):
        self.assertIsNone(self.post.helpful_rank)
        self.assertFalse(Post._meta.get_field("helpful_rank").editable)


class RankingBehaviourTests(TestCase):
    """The product promises, end to end through the real vote path."""

    def setUp(self):
        self.now = timezone.now()
        self.author = make_user("author")
        self.voters = [make_user(f"v{i}") for i in range(60)]

    def test_old_post_with_huge_votes_below_post_with_few_votes_today(self):
        old = make_post(self.author, "old-hit")
        new = make_post(self.author, "new-few")
        five_years = self.now - timedelta(days=5 * 365)
        Helpful.objects.bulk_create([Helpful(post=old, user=u) for u in self.voters])
        Helpful.objects.filter(post=old).update(created_at=five_years)
        helpful.recompute(old.pk)
        for u in self.voters[:3]:
            vote_at(u, new, self.now)
        self.assertIsNotNone(rank_of(old))
        self.assertEqual(order()[:2], ["new-few", "old-hit"])

    def test_many_fresh_votes_beat_few_fresh_votes(self):
        many, few = make_post(self.author, "many"), make_post(self.author, "few")
        for u in self.voters[:10]:
            vote_at(u, many, self.now)
        for u in self.voters[:2]:
            vote_at(u, few, self.now)
        self.assertEqual(order()[:2], ["many", "few"])

    def test_fresh_votes_on_old_post_lift_it_above_newer_post_with_older_votes(self):
        old = make_post(self.author, "old-lifted")
        newer = make_post(self.author, "newer")
        Post.objects.filter(pk=old.pk).update(created_at=self.now - timedelta(days=5 * 365))
        for u in self.voters[:5]:
            vote_at(u, newer, self.now - timedelta(days=60))
        for u in self.voters[:2]:
            vote_at(u, old, self.now - timedelta(days=400))
        self.assertEqual(order()[:2], ["newer", "old-lifted"])
        for u in self.voters[10:16]:
            vote_at(u, old, self.now)
        self.assertEqual(order()[:2], ["old-lifted", "newer"])

    def test_removing_a_vote_recomputes(self):
        post = make_post(self.author, "p")
        times = [self.now - timedelta(days=d) for d in (50, 10, 1)]
        for u, t in zip(self.voters, times):
            vote_at(u, post, t)
        helpful.unmark(self.voters[1], post)
        self.assertAlmostEqual(rank_of(post), ranking.rank_from_votes([times[0], times[2]]), places=9)
        helpful.unmark(self.voters[0], post)
        helpful.unmark(self.voters[2], post)
        self.assertIsNone(rank_of(post))

    def test_incremental_equals_full_recompute_in_db(self):
        post = make_post(self.author, "p")
        for i, u in enumerate(self.voters[:8]):
            vote_at(u, post, self.now - timedelta(days=i * 9, hours=i))
        incremental = rank_of(post)
        self.assertAlmostEqual(incremental, helpful.recompute(post.pk), places=9)

    def test_ties_fall_back_to_newest_and_unvoted_come_last(self):
        a = make_post(self.author, "older-tie")
        b = make_post(self.author, "newer-tie")
        none = make_post(self.author, "no-votes")
        Post.objects.filter(pk=a.pk).update(created_at=self.now - timedelta(days=3))
        Post.objects.filter(pk=b.pk).update(created_at=self.now - timedelta(days=2))
        Post.objects.filter(pk=none.pk).update(created_at=self.now)  # newest of all, but no votes
        Post.objects.filter(pk__in=[a.pk, b.pk]).update(helpful_rank=5.0)
        self.assertEqual(order(), ["newer-tie", "older-tie", "no-votes"])

    def test_deleting_an_account_recomputes_rank(self):
        post = make_post(self.author, "p")
        leaver, stayer = self.voters[0], self.voters[1]
        t_stay = self.now - timedelta(days=5)
        vote_at(leaver, post, self.now - timedelta(days=1))
        vote_at(stayer, post, t_stay)
        leaver.delete()
        self.assertAlmostEqual(rank_of(post), ranking.rank_from_votes([t_stay]), places=9)
        stayer.delete()
        self.assertIsNone(rank_of(post))

    def test_deleting_the_post_does_not_recompute_per_vote(self):
        post = make_post(self.author, "p")
        for u in self.voters[:5]:
            helpful.mark(u, post)
        with mock.patch.object(helpful, "recompute") as recompute:
            post.delete()
        recompute.assert_not_called()
        self.assertEqual(Helpful.objects.count(), 0)


class RankPostsCommandTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.author = make_user("author")
        self.posts = [make_post(self.author, f"p{i}") for i in range(3)]
        for i, post in enumerate(self.posts[:2]):
            for j in range(i + 2):
                vote_at(make_user(f"u{i}{j}"), post, self.now - timedelta(days=10 * j))

    def run_cmd(self):
        out = StringIO()
        call_command("rank_posts", stdout=out)
        return out.getvalue()

    def test_rebuilds_identical_values_and_is_rerunnable(self):
        before = {p.pk: rank_of(p) for p in self.posts}
        self.assertIsNone(before[self.posts[2].pk])
        out = self.run_cmd()
        self.assertNotIn("votes:", out)
        after = {p.pk: rank_of(p) for p in self.posts}
        for pk, value in before.items():
            if value is None:
                self.assertIsNone(after[pk])
            else:
                self.assertAlmostEqual(value, after[pk], places=9)
        again = {p.pk: (self.run_cmd(), rank_of(p))[1] for p in self.posts}
        self.assertEqual(after, again)

    def test_repairs_wrong_and_stale_values(self):
        Post.objects.filter(pk=self.posts[0].pk).update(helpful_rank=-1.0)
        Post.objects.filter(pk=self.posts[2].pk).update(helpful_rank=99.0)  # no votes: must go back to NULL
        self.run_cmd()
        self.assertIsNone(rank_of(self.posts[2]))
        self.assertNotEqual(rank_of(self.posts[0]), -1.0)

    def test_follows_half_life_change(self):
        before = rank_of(self.posts[1])
        with override_settings(HELPFUL_HALF_LIFE_DAYS=3):
            self.run_cmd()
        self.assertNotAlmostEqual(before, rank_of(self.posts[1]), places=3)


class MarkViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = make_user("author")
        cls.fan = make_user("fan")
        cls.post = make_post(cls.author, "Public one")
        cls.url = reverse("helpful_mark", args=["author", cls.post.id])
        cls.undo = reverse("helpful_unmark", args=["author", cls.post.id])
        cls.detail = reverse("post_detail", args=["author", cls.post.id])

    def setUp(self):
        storage._instance = storage.MemoryStorage()
        self.client.login(username="fan", password=PW)

    def test_anonymous_is_sent_to_sign_in(self):
        self.client.logout()
        r = self.client.post(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])
        self.assertEqual(Helpful.objects.count(), 0)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.client.get(self.undo).status_code, 405)

    def test_mark_redirects_back_with_friendly_message_and_no_numbers(self):
        r = self.client.post(self.url, follow=True)
        self.assertRedirects(r, self.detail + "#helpful")
        self.assertContains(r, "Thanks, marked as helpful.")
        self.assertContains(r, "You marked this helpful")
        self.assertEqual(Helpful.objects.filter(user__username="fan").count(), 1)

    def test_twice_is_idempotent(self):
        self.client.post(self.url)
        r = self.client.post(self.url, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Helpful.objects.count(), 1)
        self.assertContains(r, "Thanks, marked as helpful.")

    def test_undo(self):
        self.client.post(self.url)
        r = self.client.post(self.undo, follow=True)
        self.assertContains(r, "Your helpful mark was removed.")
        self.assertEqual(Helpful.objects.count(), 0)
        self.assertIsNone(rank_of(self.post))
        self.assertContains(r, "This was helpful")
        # undo when nothing is marked is harmless
        self.assertEqual(self.client.post(self.undo).status_code, 302)

    def test_cannot_mark_own_post(self):
        self.client.login(username="author", password=PW)
        r = self.client.post(self.url, follow=True)
        self.assertContains(r, "You can&#x27;t mark your own post as helpful.")
        self.assertEqual(Helpful.objects.count(), 0)

    def test_author_sees_no_control(self):
        self.client.login(username="author", password=PW)
        html = self.client.get(self.detail).content.decode()
        self.assertNotIn('id="helpful"', html)
        self.assertNotIn("This was helpful", html)
        self.assertNotIn("Sign in to say", html)

    def test_non_public_posts_are_404_for_everyone(self):
        for kw in ({"visibility": "private"}, {"visibility": "unlisted"}, {"is_draft": True}):
            p = make_post(self.author, "hidden", **kw)
            for name in ("helpful_mark", "helpful_unmark"):
                self.assertEqual(self.client.post(reverse(name, args=["author", p.id])).status_code, 404, (kw, name))
        self.assertEqual(self.client.post(reverse("helpful_mark", args=["author", "nope"])).status_code, 404)
        self.assertEqual(self.client.post(reverse("helpful_mark", args=["someoneelse", self.post.id])).status_code, 404)
        self.assertEqual(Helpful.objects.count(), 0)

    def test_signed_out_detail_shows_quiet_signin_link(self):
        self.client.logout()
        html = self.client.get(self.detail).content.decode()
        self.assertIn("Sign in to say this was helpful", html)
        self.assertNotIn("<form method=\"post\" action=\"%s\"" % self.url, html)

    def test_no_control_on_unlisted_posts(self):
        p = make_post(self.author, "unl", visibility="unlisted")
        html = self.client.get(reverse("post_detail", args=["author", p.id])).content.decode()
        self.assertNotIn('id="helpful"', html)

    def test_csrf_enforced(self):
        c = Client(enforce_csrf_checks=True)
        c.login(username="fan", password=PW)
        self.assertEqual(c.post(self.url).status_code, 403)
        self.assertEqual(Helpful.objects.count(), 0)
        html = c.get(self.detail).content.decode()
        self.assertIn("csrfmiddlewaretoken", html[html.index('id="helpful"'):])

    @override_settings(HELPFUL_LIMIT_PER_HOUR=2)
    def test_rate_limit_per_account(self):
        posts = [make_post(self.author, f"r{i}") for i in range(3)]
        for p in posts[:2]:
            self.client.post(reverse("helpful_mark", args=["author", p.id]))
        r = self.client.post(reverse("helpful_mark", args=["author", posts[2].id]), follow=True)
        self.assertContains(r, "doing that a lot")
        self.assertEqual(Helpful.objects.count(), 2)

    @override_settings(HELPFUL_LIMIT_PER_HOUR=1)
    def test_rate_limit_per_ip(self):
        other = make_user("fan2")
        p2 = make_post(self.author, "second")
        self.client.post(self.url)
        c2 = Client()
        c2.login(username="fan2", password=PW)
        r = c2.post(reverse("helpful_mark", args=["author", p2.id]), follow=True)  # different account, same address
        self.assertContains(r, "doing that a lot")
        self.assertFalse(Helpful.objects.filter(user=other).exists())

    @override_settings(HELPFUL_REQUIRE_VERIFIED_EMAIL=True)
    def test_optional_verified_email_rule(self):
        r = self.client.post(self.url, follow=True)
        self.assertContains(r, "Confirm your email")
        User.objects.filter(username="fan").update(email_verified=True)
        self.client.post(self.url)
        self.assertEqual(Helpful.objects.count(), 1)

    @override_settings(HELPFUL_MIN_ACCOUNT_AGE_DAYS=3)
    def test_optional_min_account_age_rule(self):
        r = self.client.post(self.url, follow=True)
        self.assertContains(r, "too new")
        User.objects.filter(username="fan").update(date_joined=timezone.now() - timedelta(days=4))
        self.client.post(self.url)
        self.assertEqual(Helpful.objects.count(), 1)

    def test_next_parameter_is_ignored(self):
        r = self.client.post(self.url + "?next=https://evil.example/", {"next": "https://evil.example/"})
        self.assertEqual(r["Location"], self.detail + "#helpful")

    def test_no_counts_or_ranks_in_any_output(self):
        # Several voters; then look at every place a count or rank could leak.
        for i in range(7):
            helpful.mark(make_user(f"extra{i}"), self.post)
        rank = rank_of(self.post)
        self.assertIsNotNone(rank)
        pages = ["/", "/discover/", "/discover/?sort=helpful", "/@author/", "/@author/?page=1", self.detail, self.detail + "raw/"]
        for who in (None, "fan", "author"):
            c = Client()
            if who:
                c.login(username=who, password=PW)
            for page in pages:
                body = c.get(page).content.decode()
                for needle in (repr(rank), f"{rank:.3f}", "helpful_rank", "helpful_marks", "7 people", "7 marks"):
                    self.assertNotIn(needle, body, (who, page, needle))
        for r in (self.client.post(self.url), self.client.post(self.undo)):
            self.assertNotIn(repr(rank).encode(), r.content)


class SortTabsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.person = make_user("pat")
        cls.bot = make_user("botty", is_agent=True)
        cls.voters = [make_user(f"v{i}") for i in range(4)]
        now = timezone.now()
        cls.alpha = make_post(cls.person, "Alpha docker guide")
        cls.beta = make_post(cls.bot, "Beta docker notes")
        cls.gamma = make_post(cls.bot, "Gamma plain")
        cls.delta = make_post(cls.person, "Delta docker newest")
        for i, p in enumerate((cls.alpha, cls.beta, cls.gamma, cls.delta)):
            Post.objects.filter(pk=p.pk).update(created_at=now - timedelta(days=10 - i))
        for u in cls.voters[:3]:
            helpful.mark(u, cls.alpha)
        helpful.mark(cls.voters[0], cls.beta)

    def titles(self, url):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        return [p.title for p in r.context["page"]] if "page" in r.context else [p.title for p in r.context["latest"]]

    def test_latest_is_default_and_unchanged(self):
        self.assertEqual(self.titles("/discover/"), ["Delta docker newest", "Gamma plain", "Beta docker notes", "Alpha docker guide"])
        self.assertEqual(self.titles("/discover/?sort=bogus"), self.titles("/discover/"))

    def test_helpful_sort_discover(self):
        self.assertEqual(self.titles("/discover/?sort=helpful"), ["Alpha docker guide", "Beta docker notes", "Delta docker newest", "Gamma plain"])

    def test_helpful_with_search_and_who(self):
        self.assertEqual(self.titles("/discover/?q=docker&sort=helpful"), ["Alpha docker guide", "Beta docker notes", "Delta docker newest"])
        self.assertEqual(self.titles("/discover/?q=docker&sort=helpful&who=agents"), ["Beta docker notes"])
        self.assertEqual(self.titles("/discover/?sort=helpful&who=people"), ["Alpha docker guide", "Delta docker newest"])

    def test_home_feed_helpful(self):
        self.assertEqual(self.titles("/?sort=helpful")[:2], ["Alpha docker guide", "Beta docker notes"])
        self.assertEqual(self.titles("/?sort=helpful&who=agents"), ["Beta docker notes", "Gamma plain"])
        self.assertEqual(self.titles("/?q=docker&sort=helpful")[0], "Alpha docker guide")  # old-style search links still work

    def test_tabs_combine_filters(self):
        html = self.client.get("/discover/?q=docker&who=agents&sort=helpful").content.decode()
        self.assertIn('href="/discover/?q=docker&amp;who=agents"', html)  # Latest keeps search + who
        self.assertIn('href="/discover/?q=docker&amp;who=people&amp;sort=helpful"', html)  # who tab keeps sort
        self.assertIn('href="/discover/?q=docker&amp;sort=helpful"', html)  # All keeps sort
        self.assertIn('name="sort" value="helpful"', html)  # the search box keeps sort
        latest = self.client.get("/discover/").content.decode()
        self.assertIn('href="/discover/?sort=helpful"', latest)
        self.assertIn('<a href="/discover/" aria-current="page">Latest</a>', latest)

    def test_pagination_keeps_sort(self):
        for i in range(25):
            make_post(self.person, f"filler {i}")
        html = self.client.get("/discover/?sort=helpful&who=people").content.decode()
        self.assertIn("page=2&amp;who=people&amp;sort=helpful", html)
        page2 = self.titles("/discover/?sort=helpful&page=2")
        page1 = self.titles("/discover/?sort=helpful")
        self.assertFalse(set(page1) & set(page2))

    def test_sort_query_count_is_flat(self):
        from django.db import connection as conn
        from django.test.utils import CaptureQueriesContext

        def count(url):
            with CaptureQueriesContext(conn) as ctx:
                self.client.get(url)
            return len(ctx)

        count("/discover/")  # warm caches
        self.assertEqual(count("/discover/?sort=helpful"), count("/discover/"))

    def test_drafts_and_private_never_appear_when_sorted(self):
        hidden = make_post(self.person, "Hidden hit", visibility="private")
        Post.objects.filter(pk=hidden.pk).update(helpful_rank=1e6)
        self.assertNotIn("Hidden hit", self.titles("/discover/?sort=helpful"))


class AdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("root", "root@example.com", PW)
        self.author = make_user("author")
        self.fan = make_user("fan")
        self.post = make_post(self.author, "Seen in admin")
        helpful.mark(self.fan, self.post)
        self.client.login(username="root", password=PW)

    def test_helpful_list_filters_and_search(self):
        r = self.client.get("/admin/posts/helpful/")
        self.assertContains(r, "fan")
        self.assertContains(r, "Seen in admin")
        self.assertContains(r, "user__id__exact")  # user filter
        self.assertContains(r, "created_at__gte")  # date filter
        self.assertContains(self.client.get("/admin/posts/helpful/?q=fan"), "Seen in admin")
        self.assertNotContains(self.client.get("/admin/posts/helpful/?q=zzz"), "Seen in admin")

    def test_helpful_cannot_be_added_or_edited_by_hand(self):
        self.assertEqual(self.client.get("/admin/posts/helpful/add/").status_code, 403)
        mark = Helpful.objects.get()
        r = self.client.post(f"/admin/posts/helpful/{mark.pk}/change/", {"user": self.author.pk})
        self.assertIn(r.status_code, (200, 403))
        mark.refresh_from_db()
        self.assertEqual(mark.user, self.fan)

    def test_admin_delete_reranks(self):
        Helpful.objects.get().delete()
        self.assertIsNone(rank_of(self.post))

    def test_post_admin_has_readonly_inline(self):
        r = self.client.get(f"/admin/posts/post/{self.post.pk}/change/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Helpful marks")
        self.assertContains(r, "fan")
        self.assertNotContains(r, 'name="helpful_marks-0-user"')
        self.assertNotContains(r, "helpful_rank")

    def test_non_staff_cannot_open(self):
        c = Client()
        c.login(username="fan", password=PW)
        self.assertEqual(c.get("/admin/posts/helpful/").status_code, 302)


class MigrationTests(TransactionTestCase):
    def test_migrates_a_populated_database(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("posts", "0004_post_search_text")])
        old = executor.loader.project_state([("posts", "0004_post_search_text")]).apps
        P = old.get_model("posts", "Post")
        user = make_user("legacy")  # accounts is already at its latest schema; only posts was rolled back
        P.objects.create(id="legacy1", author_id=user.pk, title="Old post", visibility="public", is_draft=False)
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        post = Post.objects.get(pk="legacy1")
        self.assertIsNone(post.helpful_rank)
        voter = make_user("late")
        helpful.mark(voter, post)
        self.assertIsNotNone(rank_of(post))
        self.assertEqual(Helpful.objects.count(), 1)
        self.assertEqual(order(), ["Old post"])
