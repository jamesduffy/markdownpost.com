from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings


class AccountTests(TestCase):
    def test_uses_custom_user_model(self):
        self.assertEqual(get_user_model()._meta.label, "accounts.User")

    def test_signup_logs_in_and_redirects_to_editor(self):
        res = self.client.post("/signup/", {"username": "carol", "password1": "a-long-pass-123", "password2": "a-long-pass-123"})
        self.assertRedirects(res, "/new/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/new/").status_code, 200)

    def test_new_post_requires_login(self):
        self.assertEqual(self.client.get("/new/").status_code, 302)


class RateLimitTests(TestCase):
    def login(self, username="nobody", password="wrong", ip="10.0.0.1"):
        return self.client.post("/login/", {"username": username, "password": password}, REMOTE_ADDR=ip)

    def test_login_blocks_after_repeated_failures_for_same_user(self):
        for _ in range(5):
            self.assertEqual(self.login().status_code, 200)
        blocked = self.login()
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked)

    def test_blocked_user_cannot_login_even_with_right_password(self):
        get_user_model().objects.create_user("dana", password="right-pass-123")
        for _ in range(5):
            self.login("dana")
        self.assertEqual(self.login("dana", "right-pass-123").status_code, 429)

    def test_other_users_and_ips_unaffected(self):
        get_user_model().objects.create_user("erin", password="right-pass-123")
        for _ in range(5):
            self.login("dana")
        self.assertEqual(self.login("erin", "right-pass-123").status_code, 302)  # same IP, different user

    def test_successful_login_resets_user_counter(self):
        get_user_model().objects.create_user("fay", password="right-pass-123")
        for _ in range(4):
            self.login("fay")
        self.assertEqual(self.login("fay", "right-pass-123").status_code, 302)
        self.client.logout()
        for _ in range(4):
            self.assertEqual(self.login("fay").status_code, 200)

    def test_ip_budget_stops_username_spraying(self):
        with self.settings(LOGIN_LIMIT_PER_IP=6):
            for i in range(6):
                self.login(f"user{i}")
            self.assertEqual(self.login("another").status_code, 429)
            self.assertEqual(self.login("another", ip="10.0.0.2").status_code, 200)

    def test_signup_limited_per_ip(self):
        for i in range(5):
            res = self.client.post("/signup/", {"username": f"u{i}", "password1": "a-long-pass-123", "password2": "a-long-pass-123"}, REMOTE_ADDR="10.0.0.9")
            self.assertEqual(res.status_code, 302)
            self.client.logout()
        res = self.client.post("/signup/", {"username": "u9", "password1": "a-long-pass-123", "password2": "a-long-pass-123"}, REMOTE_ADDR="10.0.0.9")
        self.assertEqual(res.status_code, 429)
        self.assertFalse(get_user_model().objects.filter(username="u9").exists())

    def test_forwarded_header_ignored_unless_proxy_trusted(self):
        from django.test import RequestFactory

        from .ratelimit import client_ip

        req = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="1.1.1.1, 2.2.2.2", REMOTE_ADDR="9.9.9.9")
        self.assertEqual(client_ip(req), "9.9.9.9")
        with self.settings(TRUST_PROXY=True):
            self.assertEqual(client_ip(req), "2.2.2.2")


class ProfileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("pat", password="right-pass-123")
        self.client.force_login(self.user)

    def png(self, size=(40, 20)):
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", size, (200, 30, 30)).save(buf, "PNG")
        return buf.getvalue()

    def save(self, **extra):
        data = {"full_name": "Pat Doe", "location": "Leeds", "bio": "Writes things.", "website": "", "github": "", "linkedin": "", "bluesky": "", "mastodon": "", "threads": ""}
        data.update(extra)
        return self.client.post("/settings/", data)

    def test_settings_require_login(self):
        self.client.logout()
        for url in ("/settings/", "/settings/account/", "/settings/password/"):
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_profile_saved_and_shown(self):
        self.assertRedirects(self.save(), "/settings/", fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual((self.user.full_name, self.user.location, self.user.bio), ("Pat Doe", "Leeds", "Writes things."))
        html = self.client.get("/@pat/").content.decode()
        for needle in ("Pat Doe", "Leeds", "Writes things.", "@pat"):
            self.assertIn(needle, html)

    def test_social_handles_become_canonical_links(self):
        self.save(website="example.com/me", github="@octo-cat", linkedin="pat-doe", bluesky="@pat.bsky.social", mastodon="@pat@mastodon.social", threads="@pat.writes")
        self.user.refresh_from_db()
        self.assertEqual(self.user.website, "https://example.com/me")
        self.assertEqual(self.user.github, "https://github.com/octo-cat")
        self.assertEqual(self.user.linkedin, "https://www.linkedin.com/in/pat-doe")
        self.assertEqual(self.user.bluesky, "https://bsky.app/profile/pat.bsky.social")
        self.assertEqual(self.user.mastodon, "https://mastodon.social/@pat")
        self.assertEqual(self.user.threads, "https://www.threads.com/@pat.writes")
        html = self.client.get("/@pat/").content.decode()
        self.assertIn('href="https://github.com/octo-cat"', html)
        self.assertIn("pat@mastodon.social", html)

    def test_pasted_urls_work_and_wrong_sites_are_rejected(self):
        self.save(github="https://github.com/octo-cat/some-repo", mastodon="https://fosstodon.org/@pat")
        self.user.refresh_from_db()
        self.assertEqual(self.user.github, "https://github.com/octo-cat")
        self.assertEqual(self.user.mastodon, "https://fosstodon.org/@pat")
        for field, bad in (("github", "https://evil.test/octo"), ("linkedin", "https://evil.test/in/x"), ("website", "javascript:alert(1)"), ("bluesky", "not a handle"), ("mastodon", "pat"), ("threads", "bad name!")):
            res = self.save(**{field: bad})
            self.assertEqual(res.status_code, 200, field)  # form re-rendered with an error, nothing saved
            self.assertContains(res, "errorlist", msg_prefix=field)

    @override_settings(STORAGE_BACKEND="memory")
    def test_avatar_upload_replace_and_remove(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from posts import storage

        storage._instance = storage.MemoryStorage()
        self.save(avatar=SimpleUploadedFile("me.png", self.png(), "image/png"))
        self.user.refresh_from_db()
        first = self.user.avatar_key
        self.assertRegex(first, r"^avatars/\d+-[0-9a-f]{12}\.webp$")
        served = self.client.get(self.user.avatar_url)
        self.assertEqual((served.status_code, served["Content-Type"]), (200, "image/webp"))
        from PIL import Image
        import io

        self.assertEqual(Image.open(io.BytesIO(served.content)).size, (256, 256))  # square crop
        self.save(avatar=SimpleUploadedFile("me2.png", self.png((30, 30)), "image/png"))
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.avatar_key, first)
        with self.assertRaises(storage.NotFound):
            storage.get_storage().get(first)  # old file removed
        self.save(remove_avatar="on")
        self.user.refresh_from_db()
        self.assertEqual(self.user.avatar_key, "")

    @override_settings(STORAGE_BACKEND="memory")
    def test_avatar_rejects_non_images(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        res = self.save(avatar=SimpleUploadedFile("x.png", b"<svg onload=alert(1)/>", "image/png"))
        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.avatar_key, "")

    def test_email_and_password_change(self):
        self.client.post("/settings/account/", {"email": "pat@example.com"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "pat@example.com")
        res = self.client.post("/settings/password/", {"old_password": "right-pass-123", "new_password1": "brand-new-pass-9", "new_password2": "brand-new-pass-9"})
        self.assertRedirects(res, "/settings/account/", fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("brand-new-pass-9"))
        self.assertEqual(self.client.get("/settings/").status_code, 200)  # still signed in

    @override_settings(STORAGE_BACKEND="memory")
    def test_delete_account_requires_password_and_username(self):
        from posts import storage
        from posts.models import Post

        storage._instance = storage.MemoryStorage()
        post = Post.objects.create(author=self.user, title="Bye")
        storage.put_body(post, "body")
        self.client.post("/settings/delete/", {"password": "wrong", "confirm": "pat"})
        self.client.post("/settings/delete/", {"password": "right-pass-123", "confirm": "nope"})
        self.assertTrue(get_user_model().objects.filter(username="pat").exists())
        self.client.post("/settings/delete/", {"password": "right-pass-123", "confirm": "pat"})
        self.assertFalse(get_user_model().objects.filter(username="pat").exists())
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())
        with self.assertRaises(storage.NotFound):
            storage.get_storage().get(post.body_key)


class AdminTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("root", "root@example.com", "root-pass-12345")
        self.client.force_login(self.admin)

    def test_every_model_is_registered_and_pages_load(self):
        from posts.models import Post

        author = get_user_model().objects.create_user("writer", password="x-pass-12345", full_name="Wri Ter")
        Post.objects.create(author=author, title="Hello", visibility="public")
        for url in (
            "/admin/",
            "/admin/accounts/user/",
            f"/admin/accounts/user/{author.pk}/change/",
            "/admin/accounts/user/add/",
            "/admin/accounts/ratelimitevent/",
            "/admin/posts/post/",
            f"/admin/posts/post/?author__id__exact={author.pk}",
            "/admin/posts/post/?q=hello",
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        post = Post.objects.get()
        self.assertEqual(self.client.get(f"/admin/posts/post/{post.pk}/change/").status_code, 200)
        self.assertContains(self.client.get("/admin/posts/post/"), f"/admin/accounts/user/{author.pk}/change/")
        self.assertContains(self.client.get("/admin/accounts/user/"), f"?author__id__exact={author.pk}")

    def test_visibility_action_and_body_cleanup_on_delete(self):
        from posts import storage
        from posts.models import Post

        with self.settings(STORAGE_BACKEND="memory"):
            storage._instance = storage.MemoryStorage()
            author = get_user_model().objects.create_user("writer2", password="x-pass-12345")
            post = Post.objects.create(author=author, title="T")
            storage.put_body(post, "body")
            self.client.post("/admin/posts/post/", {"action": "make_public", "_selected_action": [post.pk]})
            post.refresh_from_db()
            self.assertEqual(post.visibility, "public")
            self.client.post("/admin/posts/post/", {"action": "delete_selected", "_selected_action": [post.pk], "post": "yes"})
            self.assertFalse(Post.objects.filter(pk=post.pk).exists())
            with self.assertRaises(storage.NotFound):
                storage.get_storage().get(post.body_key)


class RegistrationFlagTests(TestCase):
    data = {"username": "dave", "password1": "a-long-pass-123", "password2": "a-long-pass-123"}

    def close(self):
        from accounts.models import SiteSettings

        SiteSettings.objects.update_or_create(pk=1, defaults={"registration_open": False})

    def test_open_by_default(self):
        self.assertContains(self.client.get("/signup/"), "Create your account")
        self.assertContains(self.client.get("/login/"), "Create an account")

    def test_closed_blocks_signup_page_and_post(self):
        self.close()
        self.assertEqual(self.client.get("/signup/").status_code, 403)
        self.assertEqual(self.client.post("/signup/", self.data).status_code, 403)
        self.assertFalse(get_user_model().objects.filter(username="dave").exists())

    def test_closed_hides_signup_links_but_login_still_works(self):
        self.close()
        get_user_model().objects.create_user("erin", password="a-long-pass-123")
        page = self.client.get("/login/")
        self.assertNotContains(page, 'href="/signup/"')
        res = self.client.post("/login/", {"username": "erin", "password": "a-long-pass-123"})
        self.assertEqual(res.status_code, 302)

    def test_admin_page_for_superuser(self):
        admin = get_user_model().objects.create_superuser("root", password="a-long-pass-123")
        self.client.force_login(admin)
        res = self.client.get("/admin/accounts/sitesettings/", follow=True)
        self.assertContains(res, "New registrations open")
