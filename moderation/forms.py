from django import forms

from .models import ContactMessage, Report

MESSAGE_MAX = 3000
MESSAGE_MIN = 10
NOTE_MAX = 500


class HoneypotMixin:
    """A field real people never see (hidden with CSS, skipped by keyboard and screen readers). Bots fill everything."""

    honeypot_name = "homepage"

    def add_honeypot(self):
        self.fields[self.honeypot_name] = forms.CharField(
            required=False,
            label="Leave this empty",
            widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off", "aria-hidden": "true"}),
        )

    @property
    def tripped(self):
        return bool(self.data.get(self.honeypot_name, "").strip())


class ContactForm(HoneypotMixin, forms.Form):
    name = forms.CharField(
        label="Your name (optional)", max_length=80, required=False, widget=forms.TextInput(attrs={"autocomplete": "name"})
    )
    email = forms.EmailField(
        label="Reply email (optional)",
        required=False,
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
        help_text="Without a reply email we cannot answer you. We only use it to reply to this message.",
    )
    topic = forms.ChoiceField(label="Topic", choices=ContactMessage.Topic.choices, initial=ContactMessage.Topic.GENERAL)
    message = forms.CharField(
        label="Message",
        min_length=MESSAGE_MIN,
        max_length=MESSAGE_MAX,
        widget=forms.Textarea(attrs={"rows": 8, "maxlength": MESSAGE_MAX}),
        help_text=f"Plain text, up to {MESSAGE_MAX:,} characters. Links are not clickable.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_honeypot()


class ReportForm(HoneypotMixin, forms.Form):
    reason = forms.ChoiceField(label="Why are you reporting this?", choices=Report.Reason.choices, widget=forms.RadioSelect)
    note = forms.CharField(
        label="Anything we should know? (optional)",
        required=False,
        max_length=NOTE_MAX,
        widget=forms.Textarea(attrs={"rows": 4, "maxlength": NOTE_MAX}),
        help_text=f"Plain text, up to {NOTE_MAX} characters.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_honeypot()
