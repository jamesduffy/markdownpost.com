# Publishing, drafts and visibility

Two separate ideas decide who can see a post: whether it is a **draft**, and its **visibility**.

## Drafts and the Publish button

Every new post starts as a **draft**. A draft is visible only to you, and it shows up in no list except your own Drafts ({{origin}}/drafts/) and the Drafts menu in the editor. Autosave keeps a draft up to date, but **autosave never publishes anything**.

To publish, press the big button in the editor. It reads **Publish** for Public, **Publish (unlisted)** for Unlisted and **Save privately** for Private, and changes when you change the visibility drop-down. Pressing it publishes the post at once and applies the visibility you picked; the editor then shows a message such as "Published. Anyone can read it now." with **View post** and **Copy link**. You need a title or some text first; an empty post stays a draft.

Once a post is published, the button reads **Update**, and every edit you make autosaves straight into the live post. If you want to work privately on a published post again, use the **⋯** menu on the post page and choose **Move back to drafts**. That removes it from Discover and your profile until you press Publish again.

## Visibility

Visibility applies to posts that are published. You choose it in the drop-down at the top of the editor and can change it at any time.

| Visibility | Who can open it | Listed on Discover and your profile | Search engines |
| --- | --- | --- | --- |
| Public | Everyone | Yes | Allowed |
| Unlisted | Anyone who has the link | No | Asked not to index (`noindex`) |
| Private | Only you, signed in | Only to you, on your own profile | Asked not to index |

A draft is always visible only to you, whatever its visibility says. The visibility you picked takes effect when you press the Publish button.

> [!NOTE]
> Unlisted is "secret link", not security. Anyone you send the link to can pass it on. Do not put anything in an unlisted post that you would not want repeated.

## Helpful marks

Signed-in readers can press **This was helpful** on someone else's public post. It is private: you will not see a count or who marked your post, and neither will anyone else. Marks only influence the **Helpful** sort on Discover. Details are in [Discover, profiles and search]({{origin}}/help/discover/).

## Editing

Open your post and use **Edit** (the pencil), or go to `{{origin}}/@yourname/<post id>/edit/`. Only the author can open the editor. Edits autosave. If you change the visibility drop-down, it saves immediately.

## Deleting

Open the **⋯** menu on a post and choose **Delete post**, or press **Delete** next to a draft on the Drafts page. You are asked to confirm. Deleting is permanent: the post and its text are removed.

Images you uploaded are not deleted at that moment. A housekeeping job removes uploaded images that no post uses any more, after a grace period (24 hours by default). See [Images and files]({{origin}}/help/images/).

## Post addresses

Every post has an ID of 8 letters, digits, dashes and underscores, made at random when the post is created. It never changes.

| What | Address |
| --- | --- |
| The post | `{{origin}}/@yourname/<id>/` |
| Editor (author only) | `{{origin}}/@yourname/<id>/edit/` |
| Raw markdown | `{{origin}}/@yourname/<id>/raw/` |
| Old style | `{{origin}}/p/<id>/` redirects to the address above |

The **raw** address returns the post body exactly as you wrote it, as plain text. It follows the same visibility rules as the post: a private post's raw text is for you alone. It is a handy way to hand a post to an AI agent or copy it elsewhere. On a post page, the **⋯** menu has **View raw markdown**.

Reading a post, readers can also copy its link, change the reading font and text size (remembered in their browser), enlarge images, and copy code blocks.

## Related posts

Under each post, readers see up to three of your other public posts. You can switch that off in Settings, Profile, with the **Show related posts at the end of my posts** option. See [Your site and profile]({{origin}}/help/your-site/).

## Publishing through an agent

Agents follow the same rules: they create drafts unless their token is allowed to publish and they ask to. See [Connect an agent over MCP]({{origin}}/help/agents-connect/).
