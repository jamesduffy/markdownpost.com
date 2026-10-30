# Writing in the editor

The editor is a single page with a title and a body. You write in plain markdown, and it is styled as you type: headings get big, `**bold**` is bold, links look like links, and images appear under the line that holds them. The markdown characters stay visible but dimmed, so what you see is what is stored.

Start a post at {{origin}}/new/, or open an existing one with **Edit** on the post page.

## The basics

- The **title** is its own field above the body. Do not repeat it as a `#` heading at the top of the body.
- Press **Enter** in the title, or **Arrow Down** at its end, to jump into the body. Press **Arrow Up** on the first body line, or **Backspace** in an empty body, to go back to the title.
- Click empty space anywhere on the page to put the cursor at the end of the text.
- Under the title is the **tag** box. Type a topic and press **Enter** or a comma to add it as a chip; click the **×** on a chip (or press Backspace in the empty box) to remove it. See [Tags](#tags) below.
- The drop-down at the top sets **who can see the post** (Public, Unlisted, Private). It applies when the post is published. Changing it saves immediately.
- The back arrow leaves the editor without publishing: it goes to your Drafts for a draft, and back to the post for a published one. **My site** (hidden on narrow screens, where it is in the Drafts menu instead) opens your profile, and **?** opens this help.
- The big button on the right publishes a draft. It reads **Publish** for Public, **Publish (unlisted)** for Unlisted and **Save privately** for Private, and changes as you change the drop-down. On a post that is already published it reads **Update** (see below).

## Tags

A post can have up to **5 tags**, topics such as `python` or `machine-learning`. Tags are saved with the post (autosave included, and offline like the text). They make the post easier to find: each tag on a public post links to a tag page at `{{origin}}/tags/<tag>/`, and Discover can be narrowed to a tag.

- A tag is 2 to 30 characters: letters a-z, numbers and single hyphens. Capital letters are lowercased and spaces become hyphens, so `#Machine Learning` becomes `machine-learning`. Accented and non-Latin letters are not accepted, which keeps tag addresses readable and look-alike tricks out.
- Adding the same tag twice does nothing. A sixth tag is refused with a message, and a few names that could pass for the site's staff (such as `admin`) are reserved.
- Tags are public with the post. On a draft, private or unlisted post they are visible to whoever can open the post but do not appear on tag pages or in the tag list.

## Formatting without remembering syntax

**Select text** and a small toolbar appears above it: bold, italic, strikethrough, heading, quote, bulleted list, checklist, link, inline code and image. On phones and tablets (narrow screens or touch input) the toolbar is docked just above the keyboard instead, and has a **+** button on its left for inserting blocks.

On wide screens a **+** button appears in the margin beside an empty line. It opens the same block menu as the slash key.

## The slash menu

Type `/` at the start of a line. A menu opens; keep typing to narrow it (`/tab` finds Table), use the arrow keys, and press Enter to choose. Press Escape to close the menu; if you had typed only the `/`, it is removed too.

| Type | Inserts |
| --- | --- |
| `/h1`, `/h2`, `/h3` | Headings |
| `/bullets`, `/numbered`, `/todo` | Bulleted list, numbered list, checklist |
| `/quote` | Quote |
| `/code` | Code block (add a language after the opening fence, such as `python`) |
| `/divider` | Horizontal rule |
| `/table` | A small table to fill in |
| `/note`, `/tip`, `/important`, `/warning`, `/caution` | Callout boxes |
| `/math` | A math block |
| `/diagram` | A Mermaid diagram |
| `/details` | A collapsible section |
| `/image` | Opens the file picker to upload an image |

## Keyboard shortcuts

On a Mac use ⌘ where this page says Ctrl.

| Keys | Does |
| --- | --- |
| Ctrl+B | Bold the selection (or toggle it off) |
| Ctrl+I | Italic |
| Ctrl+Alt+1, 2, 3 | Turn the line into a heading 1, 2 or 3 (press again to turn it off) |
| Ctrl+S | Sync the draft to the server now (does not publish) |
| Ctrl+Z, Ctrl+Shift+Z | Undo, redo |
| Tab, Shift+Tab | Indent or outdent, but only inside a list (so Tab never traps keyboard focus in ordinary text) |
| Enter on an empty `>` line | Leaves a quote |
| Enter on an empty list item | Ends the list |

Other small helpers:

- **Paste a link over selected text** and the selection becomes a link: `[the text](the address)`.
- **Click a checkbox** in a checklist to tick or untick it.

## Autosave and drafts

You never have to press Publish to keep your work: autosave keeps it as a draft.

- Every change is stored **on your device** within a fraction of a second.
- About a second after you stop typing, the text is saved to the **server**. The status next to the back arrow tells you what is happening: "Draft · editing…", "Saving…", "Draft, autosaved" (a draft only you can see) or "Published, changes saved".
- Ctrl+S saves right away. Switching tabs or closing the page saves too.
- A new post is created on the server the first time there is something to save, and the address in the browser changes to `/@you/<id>/edit/`. If a connection drops during that first save, a retry reuses the same internal key, so you do not end up with two copies.

**New posts are drafts, and autosave never publishes them.** A draft is visible only to you and appears in no list except your own Drafts. To publish, press **Publish** (or **Publish (unlisted)**, or **Save privately** if the drop-down says Private): the post becomes live with the visibility you chose and a message appears at the top of the editor, for example "Published. Anyone can read it now." with **View post** and **Copy link**. If the post is already published, the button says **Update**, which takes you to the post; your edits are already live because they autosave into the published post.

Your drafts are in the **Drafts** menu at the top of the editor and on the Drafts page ({{origin}}/drafts/). To take a published post back to drafts, use the **⋯** menu on the post page and choose **Move back to drafts**.

## Editing in two places at once

If you edit the same post in two tabs or on two devices, the second to save sees a banner: "This post was changed on another device or tab since you opened it." Choose **Keep my version** or **Use the other version**. Nothing is overwritten silently.

If the post is deleted while you have it open, the editor keeps your text and offers **Keep as a new draft** or **Discard**.

## Images

Paste an image from the clipboard, drop a file onto the page, press the image button, or type `/image`. The image uploads and a markdown image line is inserted. See [Images and files]({{origin}}/help/images/) for types and limits.

## Writing offline

The editor keeps working without a connection.

- Your text is stored on the device as you type. The status reads "Offline · kept on this device".
- When the connection returns, the post syncs by itself.
- The editor opens offline once you have used it online on that device. A post you opened while online can be reopened offline, and you can start a new one.
- Drafts that exist only on your device show up in the Drafts menu and, when the network is down, on the "You're offline" page.
- If you are signed out when the connection returns, the status says "Signed out · kept on this device. Log in again to sync." Sign in as the same account and it finishes saving.
- Logging out asks for confirmation if drafts on this device have not synced, because logging out clears the device's copies.

Details of installing the site and what else works offline: [Installing the app and working offline]({{origin}}/help/install-offline/).

## Limits

A title can be 200 characters. A body can be 500,000 bytes of text (a very long book chapter). A post needs a title or some text before it can be published. See [Limits and rate limits]({{origin}}/help/limits/).
