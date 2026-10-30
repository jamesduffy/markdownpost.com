"""The short guided setup at /welcome/ that new accounts land on after signing up.

Nothing is stored about progress: every step simply edits the same profile and theme fields that Settings edits,
so existing users can open /welcome/ at any time and every step can be skipped with a plain link.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from . import themes
from .forms import OnboardingSiteForm

STEPS = (
    ("onboarding_site", "Name your site"),
    ("onboarding_look", "Choose a look"),
    ("onboarding_agent", "Bring an agent"),
    ("onboarding_done", "Finish"),
)


def _context(step_name, **extra):
    index = next(i for i, (name, _) in enumerate(STEPS) if name == step_name)
    steps = [{"name": name, "label": label, "number": i + 1, "done": i < index, "current": i == index} for i, (name, label) in enumerate(STEPS)]
    return {
        "steps": steps,
        "step": steps[index],
        "total": len(STEPS),
        "next_url": STEPS[index + 1][0] if index + 1 < len(STEPS) else None,
        "back_url": STEPS[index - 1][0] if index else None,
        **extra,
    }


@login_required
def site(request):
    form = OnboardingSiteForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("onboarding_look")
    return render(request, "accounts/onboarding/site.html", _context("onboarding_site", form=form))


@login_required
def look(request):
    current = request.user.theme.get("preset", "") if isinstance(request.user.theme, dict) else ""
    error = ""
    if request.method == "POST":
        if themes.apply_preset(request.user, request.POST.get("preset", "")):
            return redirect("onboarding_agent")
        error = "Pick a look, or skip this step."
    presets = [(key, preset["label"], preset["theme"] | {"preset": key}) for key, preset in themes.PRESETS.items()]
    return render(request, "accounts/onboarding/look.html", _context("onboarding_look", presets=presets, current=current, error=error))


@login_required
def agent(request):
    return render(request, "accounts/onboarding/agent.html", _context("onboarding_agent"))


@login_required
def done(request):
    return render(request, "accounts/onboarding/done.html", _context("onboarding_done"))
