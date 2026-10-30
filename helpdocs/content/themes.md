# Themes

A theme controls how your **profile page and your post pages** look: colors, background, fonts and layout. Each account has one theme. Open **Settings** from the menu and choose the **Look** tab, or go to {{origin}}/settings/theme/.

## How to use the theme page

1. Pick a **starter theme**.
2. Change anything you like. The preview on the page updates as you go.
3. Press **Save theme**.

You can also press **Surprise me** to fill the form with a random theme (nothing is saved until you press Save theme), or **Reset to starter theme** to go back to the starter you chose.

If your browser has no JavaScript, pick a starter and use **Apply starter theme**; the other controls still work as a normal form.

## What you can change

{{theme_options}}

**Colors.** Five of them: the page background, cards and panels, text, muted text (dates and small print) and the accent used for links and buttons.

**Background.** A solid color, a gradient (two colors and an angle), a pattern (a second color sets the pattern's ink, and a size from 1 to 3), or your own image (tiled or covering the page). You can make the background stay still while the page scrolls. A background image is an upload: PNG, JPEG, WebP or GIF up to 5 MB, counted in your image storage.

**Fonts.** One for headings and one for body text. They are hosted on this site, so no request goes to any other server when someone reads your page.

**Layout.** Page width, card style, corner roundness, heading style and the shape of your photo.

## Light and dark

The look follows your **background color**: a dark background gives a dark page, a light one gives a light page, whatever the visitor's own light or dark setting. Diagrams on your pages are drawn to match.

## Readability rules

A theme that is hard to read cannot be saved.

{{theme_contrast_rules}}

The page tells you which color is the problem. Random themes are built to pass.

## What a theme does and does not change

A theme applies to:

- your profile page (`/@you/`),
- your post pages (`/@you/<id>/`),
- your About text.

It does **not** change Discover, Settings, the editor, the sign-in pages, the menu button or this help. Those always look the same, which keeps the menu trustworthy and stops a page from imitating the site's own controls. There is deliberately no custom CSS.

There is one theme per account. Posts use their author's theme; you cannot give an individual post a different one.

## Plain view for visitors

Anyone reading a themed page can open the menu and choose **Plain view** to drop the author's theme and see the standard look. It is remembered in that browser. Choose **Show author's theme** to switch back.

## If you never set a theme

Every account gets a look derived from its username: one of the starter themes with a slightly shifted accent color. So untouched sites already differ from each other. The theme is stored only after you save one.

## Agents and themes

Agents can read and set themes with the `list_themes`, `get_theme` and `set_theme` tools, under the same rules. See [MCP tool reference]({{origin}}/help/mcp-tools/).
