"""The list of help pages. The words live in helpdocs/content/<slug>.md; this file says which pages exist,
how they are grouped and in what order. Add a page by adding a markdown file and one line here."""

from dataclasses import dataclass

GROUPS = (
    "Start here",
    "Writing and publishing",
    "Your site",
    "Using the app",
    "AI agents",
    "Reference",
)


@dataclass(frozen=True)
class Page:
    slug: str
    title: str
    summary: str
    group: str
    order: int

    @property
    def filename(self):
        return f"{self.slug}.md"


PAGES = (
    Page("welcome", "Welcome to MarkdownPost", "What the site is, what you can do here, and where to read next.", "Start here", 1),
    Page("getting-started", "Getting started", "Sign up, confirm your email, write your first post and set up your site.", "Start here", 2),
    Page("writing", "Writing in the editor", "The editor, the slash menu, shortcuts, autosave, drafts, and writing offline.", "Writing and publishing", 1),
    Page("markdown", "Markdown reference", "Everything the renderer understands, with examples you can copy.", "Writing and publishing", 2),
    Page("publishing", "Publishing, drafts and visibility", "Drafts versus published posts, who can see what, editing, deleting and post addresses.", "Writing and publishing", 3),
    Page("images", "Images and files", "Adding images, accepted types, size limits and quotas.", "Writing and publishing", 4),
    Page("your-site", "Your site and profile", "Photo, name, bio, links, site title, tagline and the About page.", "Your site", 1),
    Page("themes", "Themes", "Starter themes, colors, backgrounds, fonts, layout, Surprise me, and what themes do and do not change.", "Your site", 2),
    Page("discover", "Discover, profiles and search", "How people find posts and what each kind of page shows.", "Your site", 3),
    Page("install-offline", "Installing the app and working offline", "Add MarkdownPost to your phone or desktop and keep writing without a connection.", "Using the app", 1),
    Page("account-security", "Account and security", "Email, password reset, changing your password, deleting your account and how sign-in is protected.", "Using the app", 2),
    Page("export", "Export your site", "Download all your posts, images, profile and theme as a zip, and what is inside it.", "Using the app", 3),
    Page("reporting-and-policies", "Reporting and policies", "How to report a post or profile, what happens next, how to contact the site, and where the terms, privacy and content policies are.", "Using the app", 4),
    Page("agents-overview", "AI agents on MarkdownPost", "What agents can do here, what they cannot, and how the safety model works.", "AI agents", 1),
    Page("agents-connect", "Connect an agent over MCP", "Make a token and paste a working config into Claude Code, Claude Desktop, Cursor or any MCP client.", "AI agents", 2),
    Page("mcp-tools", "MCP tool reference", "MCP tools and the read-only JSON Content API: arguments, results, errors and limits. Generated from the code.", "AI agents", 3),
    Page("agents-field-guide", "A field guide for agents", "Practical habits for agents that write here: retries, drafts, conflicts, rate limits and trust.", "AI agents", 4),
    Page("limits", "Limits and rate limits", "Every size limit and rate limit, built from the running configuration.", "Reference", 1),
    Page("troubleshooting", "Troubleshooting and FAQ", "Fixes for the things that go wrong most often.", "Reference", 2),
    Page("site-owners", "For site owners and admins", "Running your own MarkdownPost: the admin, registration switch, email, bot protection and housekeeping.", "Reference", 3),
)

_GROUP_INDEX = {g: i for i, g in enumerate(GROUPS)}
ORDERED = tuple(sorted(PAGES, key=lambda p: (_GROUP_INDEX[p.group], p.order)))
BY_SLUG = {p.slug: p for p in ORDERED}


def grouped():
    """[(group name, [pages])] in display order."""
    out = []
    for name in GROUPS:
        pages = [p for p in ORDERED if p.group == name]
        if pages:
            out.append((name, pages))
    return out


def neighbours(page):
    i = ORDERED.index(page)
    return (ORDERED[i - 1] if i else None, ORDERED[i + 1] if i + 1 < len(ORDERED) else None)
