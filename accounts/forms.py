from django import forms
from django.contrib.auth.forms import PasswordResetForm, UserCreationForm
from django.db import transaction

from . import avatars, recommendations, social, themes
from .models import ProfileRecommendation, User
from .validators import validate_plain_text, validate_username


def clean_new_email(value, exclude_pk=None):
    """The one rule for an address someone types (signup, onboarding, Settings): trimmed, and not already confirmed elsewhere."""
    email = (value or "").strip()
    if email and User.objects.filter(email__iexact=email, email_verified=True).exclude(pk=exclude_pk).exists():
        raise forms.ValidationError("That email is already verified on another account.")
    return email


EMAIL_OPTIONAL_LABEL = "Email (optional, lets you reset a forgotten password)"


class SignupForm(UserCreationForm):
    email = forms.EmailField(required=False, label=EMAIL_OPTIONAL_LABEL,
        help_text="Without a confirmed email we can't reset your password. It stays private.",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "you@example.com"}),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = "Letters, numbers, dots, dashes and underscores. It's part of your site address and can't be changed."

    def clean_email(self):
        return clean_new_email(self.cleaned_data.get("email"))

    def clean_username(self):
        username = super().clean_username()
        # Django NFKC-normalises the field before this runs, so also check what was actually typed.
        validate_username(self.data.get(self.add_prefix("username"), "").strip())
        validate_username(username)
        return username


class ProfileForm(forms.ModelForm):
    avatar = forms.ImageField(required=False, label="Profile photo", widget=forms.FileInput(attrs={"accept": "image/png,image/jpeg,image/webp,image/gif"}))
    remove_avatar = forms.BooleanField(required=False, label="Remove photo")

    class Meta:
        model = User
        fields = ("site_title", "tagline", "about_md", "full_name", "location", "bio", "website", "github", "linkedin", "bluesky", "mastodon", "threads", "show_related_posts", "allow_recommendations")
        labels = {"site_title": "Site title", "tagline": "Tagline", "about_md": "About (shown on your home page)", "full_name": "Full name", "bio": "Bio", "github": "GitHub", "linkedin": "LinkedIn", "show_related_posts": "Show related posts at the end of my posts", "allow_recommendations": "Allow others to recommend my site"}
        widgets = {
            "site_title": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "My corner of the internet"}),
            "tagline": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "Notes on code, coffee and other things"}),
            "about_md": forms.Textarea(attrs={"rows": 8, "maxlength": 5000, "spellcheck": "true"}),
            "full_name": forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Ada Lovelace"}),
            "location": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "London, UK"}),
            "bio": forms.Textarea(attrs={"rows": 3, "maxlength": 300, "placeholder": "A sentence or two about you and what you write."}),
        }

    # The social inputs are plain text so people can paste a handle or a link; the model stores the canonical URL.
    placeholders = {
        "website": "yoursite.com",
        "github": "username",
        "linkedin": "linkedin.com/in/you",
        "bluesky": "you.bsky.social",
        "mastodon": "@you@mastodon.social",
        "threads": "@you",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, hint in self.placeholders.items():
            if name not in self.fields:
                continue  # subclasses (onboarding) may offer only some fields
            # Plain CharFields: URLField would reject a bare handle before our cleaner ever sees it.
            self.fields[name] = forms.CharField(
                required=False,
                max_length=200,
                label=self.fields[name].label,
                widget=forms.TextInput(attrs={"placeholder": hint, "autocomplete": "off", "autocapitalize": "none", "spellcheck": "false"}),
            )
            if self.instance.pk and getattr(self.instance, name):
                # Show what they'd recognise (the handle), not the stored URL.
                self.initial[name] = social.handle_for(name, getattr(self.instance, name))
        if "allow_recommendations" in self.fields:
            from posts.discovery import user_is_discoverable

            existing = []
            if self.instance.pk:
                existing = [
                    item
                    for item in self.instance.recommendation_entries.select_related("recommended").all()
                    if item.recommended.allow_recommendations and user_is_discoverable(item.recommended)
                ]
            self.recommendation_fields = []
            self.recommendation_slots = []
            for position in range(recommendations.MAX_RECOMMENDATIONS):
                account_name = f"recommendation_{position + 1}"
                note_name = f"recommendation_note_{position + 1}"
                item = existing[position] if position < len(existing) else None
                self.fields[account_name] = forms.CharField(
                    required=False,
                    max_length=150,
                    label=f"Account {position + 1}",
                    widget=forms.TextInput(attrs={"placeholder": "@username", "autocomplete": "off", "autocapitalize": "none", "spellcheck": "false"}),
                )
                self.fields[note_name] = forms.CharField(
                    required=False,
                    max_length=recommendations.MAX_NOTE_LENGTH,
                    label=f"Note {position + 1}",
                    widget=forms.TextInput(attrs={"maxlength": recommendations.MAX_NOTE_LENGTH, "placeholder": "A short note (optional)"}),
                )
                self.recommendation_fields.append((account_name, note_name))
                self.recommendation_slots.append((self[account_name], self[note_name]))
                if item:
                    self.initial[account_name] = item.recommended.username
                    self.initial[note_name] = item.note

    def clean(self):
        data = super().clean()
        if not hasattr(self, "recommendation_fields") or self.errors:
            return data
        values = []
        for account_name, note_name in self.recommendation_fields:
            username = (data.get(account_name) or "").strip()
            note = (data.get(note_name) or "").strip()
            if username:
                values.append({"username": username, "note": note})
            elif note:
                self.add_error(note_name, "Add an account for this note.")
        if self.errors:
            return data
        try:
            self.cleaned_recommendations = recommendations.resolve_recommendations(self.instance, values)
        except forms.ValidationError as exc:
            self.add_error(None, exc)
        return data

    def clean_site_title(self):
        return validate_plain_text(self.cleaned_data["site_title"]).strip()

    def clean_tagline(self):
        return validate_plain_text(self.cleaned_data["tagline"]).strip()

    def clean_about_md(self):
        return validate_plain_text(self.cleaned_data["about_md"], allow_newlines=True).strip()

    def clean_full_name(self):
        return validate_plain_text(self.cleaned_data["full_name"])

    def clean_location(self):
        return validate_plain_text(self.cleaned_data["location"])

    def clean_bio(self):
        return validate_plain_text(self.cleaned_data["bio"], allow_newlines=True)

    def _clean_social(self, name):
        validate_plain_text(self.cleaned_data.get(name, ""))
        return social.CLEANERS[name](self.cleaned_data.get(name, ""))

    def clean_website(self):
        return self._clean_social("website")

    def clean_github(self):
        return self._clean_social("github")

    def clean_linkedin(self):
        return self._clean_social("linkedin")

    def clean_bluesky(self):
        return self._clean_social("bluesky")

    def clean_mastodon(self):
        return self._clean_social("mastodon")

    def clean_threads(self):
        return self._clean_social("threads")

    def clean_avatar(self):
        upload = self.cleaned_data.get("avatar")
        if upload:
            self._avatar_data = avatars.process(upload)  # validate now so the error shows on the form; saved in save()
        return upload

    def save(self, commit=True):
        user = super().save(commit=False)
        old_key = user.avatar_key
        upload = self.cleaned_data.get("avatar")
        if upload:
            user.avatar_key = avatars.save(user, getattr(self, "_avatar_data", upload))
        elif self.cleaned_data.get("remove_avatar"):
            user.avatar_key = ""
        if commit:
            with transaction.atomic():
                user.save()
                if hasattr(self, "recommendation_fields"):
                    ProfileRecommendation.objects.filter(recommender=user).delete()
                    ProfileRecommendation.objects.bulk_create(
                        ProfileRecommendation(recommender=user, recommended=target, note=note, position=position)
                        for position, (target, note) in enumerate(self.cleaned_recommendations)
                    )
            if old_key and old_key != user.avatar_key:
                avatars.delete(old_key)
        return user


class OnboardingSiteForm(ProfileForm):
    """Step 1 of /welcome/: the same fields and validators as Settings, just fewer of them."""

    class Meta(ProfileForm.Meta):
        fields = ("full_name", "site_title", "tagline", "bio")
        labels = {"full_name": "Your name", "site_title": "Site title", "tagline": "Tagline", "bio": "Short bio"}
        widgets = {
            "full_name": forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Ada Lovelace"}),
            "site_title": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "My corner of the internet"}),
            "tagline": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "Notes on code, coffee and other things"}),
            "bio": forms.Textarea(attrs={"rows": 3, "maxlength": 300, "placeholder": "A sentence or two about you and what you write."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only offered to people who have no address yet; it never overwrites one.
        self.offers_email = bool(self.instance.pk) and not self.instance.email
        if self.offers_email:
            self.fields["email"] = forms.EmailField(
                required=False,
                label=EMAIL_OPTIONAL_LABEL,
                help_text="Without a confirmed email we can't reset your password. It stays private.",
                widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "you@example.com"}),
            )

    def clean_email(self):
        return clean_new_email(self.cleaned_data.get("email"), self.instance.pk)

    def save(self, commit=True):
        user = super().save(commit=False)
        email = self.cleaned_data.get("email", "") if self.offers_email else ""
        if email:
            user.email, user.email_verified = email, False
        self.new_email = bool(email)
        if commit:
            user.save()
        return user


class EmailForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("email",)
        widgets = {"email": forms.EmailInput(attrs={"autocomplete": "email"})}
        help_texts = {"email": "Private. Never shown on your profile. Used for password resets."}

    def clean_email(self):
        return clean_new_email(self.cleaned_data["email"], self.instance.pk)


class VerifiedEmailPasswordResetForm(PasswordResetForm):
    """Reset links only go to addresses their owner has confirmed, so a typo or someone else's address can't receive one."""

    def get_users(self, email):
        return (user for user in super().get_users(email) if user.email_verified)


class ThemeForm(forms.Form):
    """The constrained theme knobs (site title, tagline and About live in the Profile form). Works as a plain POST; every value is validated by accounts.themes."""

    preset = forms.ChoiceField(required=False, choices=[*themes.PRESET_CHOICES], widget=forms.RadioSelect)

    color_bg = forms.CharField(label=themes.COLOR_LABELS["bg"], max_length=7)
    color_surface = forms.CharField(label=themes.COLOR_LABELS["surface"], max_length=7)
    color_text = forms.CharField(label=themes.COLOR_LABELS["text"], max_length=7)
    color_muted = forms.CharField(label=themes.COLOR_LABELS["muted"], max_length=7)
    color_accent = forms.CharField(label=themes.COLOR_LABELS["accent"], max_length=7)

    bg_type = forms.ChoiceField(label="Background type", choices=themes.BG_TYPE_CHOICES)
    bg_color2 = forms.CharField(label="Second color", max_length=7)
    bg_angle = forms.CharField(label="Gradient angle", max_length=4)
    bg_pattern = forms.ChoiceField(label="Pattern", choices=themes.PATTERN_CHOICES)
    bg_scale = forms.CharField(label="Pattern size", max_length=2)
    bg_image_file = forms.ImageField(required=False, label="Background image", widget=forms.FileInput(attrs={"accept": "image/png,image/jpeg,image/webp,image/gif"}))
    remove_bg_image = forms.BooleanField(required=False, label="Remove background image")
    bg_fit = forms.ChoiceField(label="Image fit", choices=themes.FIT_CHOICES)
    bg_fixed = forms.BooleanField(required=False, label="Keep the background still while scrolling")

    font_heading = forms.ChoiceField(label="Heading font", choices=themes.FONT_CHOICES)
    font_body = forms.ChoiceField(label="Body font", choices=themes.FONT_CHOICES)

    layout_width = forms.ChoiceField(label="Page width", choices=themes.WIDTH_CHOICES)
    layout_card = forms.ChoiceField(label="Card style", choices=themes.CARD_CHOICES)
    layout_radius = forms.ChoiceField(label="Corners", choices=themes.RADIUS_CHOICES)
    layout_headings = forms.ChoiceField(label="Headings", choices=themes.HEADINGS_CHOICES)
    layout_avatar = forms.ChoiceField(label="Photo shape", choices=themes.AVATAR_CHOICES)

    def __init__(self, *args, user, **kwargs):
        self.user = user
        self.warnings = []
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.set_initial(themes.resolve(user).theme)
        for name in ("color_bg", "color_surface", "color_text", "color_muted", "color_accent", "bg_color2"):
            self.fields[name].widget = forms.TextInput(attrs={"type": "color"})
        self.fields["bg_angle"].widget = forms.NumberInput(attrs={"type": "range", "min": 0, "max": 360, "step": 5})
        self.fields["bg_scale"].widget = forms.NumberInput(attrs={"type": "range", "min": 1, "max": 3, "step": 1})

    def set_initial(self, theme):
        self.initial.update(
            preset=theme.get("preset") if theme.get("preset") in themes.PRESETS else None,
            bg_image=theme["bg"]["image"],
            bg_fixed=theme["bg"]["fixed"],
            **{f"color_{k}": v for k, v in theme["colors"].items()},
            **{f"bg_{k}": v for k, v in theme["bg"].items() if k not in ("image", "fixed")},
            **{f"font_{k}": v for k, v in theme["fonts"].items()},
            **{f"layout_{k}": v for k, v in theme["layout"].items()},
        )

    @property
    def current_image(self):
        return self.user.theme.get("bg", {}).get("image", "") if isinstance(self.user.theme, dict) else ""

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        for name in ("color_bg", "color_surface", "color_text", "color_muted", "color_accent", "bg_color2"):
            data[name] = data[name].strip().lower()  # strict hex check happens in themes.clean
        g = data.get
        image = "" if g("remove_bg_image") else self.current_image
        theme = {
            "preset": g("preset") or "custom",
            "colors": {k: g(f"color_{k}") for k in themes.COLOR_KEYS},
            "bg": {
                "type": g("bg_type"), "color2": g("bg_color2"), "angle": g("bg_angle"), "pattern": g("bg_pattern"),
                "scale": g("bg_scale"), "image": image, "fit": g("bg_fit"), "fixed": g("bg_fixed"),
            },
            "fonts": {"heading": g("font_heading"), "body": g("font_body")},
            "layout": {k: g(f"layout_{k}") for k in themes.LAYOUT_ALLOWED},
        }
        try:
            cleaned = themes.clean(theme, self.user)
        except forms.ValidationError as exc:
            for message in exc.messages:
                self.add_error(None, message)
            return data
        upload = g("bg_image_file")
        if upload:
            # Last, so a form that failed above doesn't leave an orphaned upload behind.
            from uploads.service import UploadError, store_image

            try:
                cleaned["bg"]["image"] = store_image(self.user, upload)
            except UploadError as exc:
                self.add_error("bg_image_file", exc.message)
                return data
            if cleaned["bg"]["type"] != "image":
                cleaned["bg"]["type"] = "image"
        if cleaned["bg"]["type"] == "image" and not cleaned["bg"]["image"]:
            cleaned["bg"]["type"] = "solid"
        self.theme = cleaned
        self.warnings = themes.warnings_for(cleaned)
        return data

    def save(self):
        """Store the validated theme; drop the replaced background image if nothing else needs it."""
        user, old = self.user, self.current_image
        user.theme = self.theme
        user.save(update_fields=["theme"])
        if old and old != self.theme["bg"]["image"]:
            _delete_unreferenced_image(user, old)
        return user


def _delete_unreferenced_image(user, key):
    """Remove an upload the user's theme no longer uses, unless one of their posts still embeds it."""
    from posts import storage
    from posts.models import Post
    from uploads.models import Upload

    try:
        if f"/media/{key}" in user.about_md or any(f"/media/{key}" in storage.get_body(post) for post in Post.objects.filter(author=user)):
            return
        storage.get_storage().delete(key)
    except storage.StorageError:
        return  # leave the row; the sweeper retries later
    Upload.objects.filter(owner=user, key=key).delete()
