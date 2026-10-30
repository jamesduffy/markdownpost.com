# Installing the app and working offline

MarkdownPost is a progressive web app (PWA). That means you can install it from your browser and it behaves like an app: its own icon, its own window, no browser bars. There is nothing to download from an app store.

## Install it

The steps depend on the browser, and menu wording changes from version to version, so look for the install or "add to home screen" option.

- **iPhone or iPad (Safari):** open the Share menu and choose **Add to Home Screen**.
- **Android (Chrome):** open the browser menu and choose **Install app** (or **Add to Home screen**).
- **Desktop Chrome or Edge:** look for the install icon at the right end of the address bar, or find **Install MarkdownPost** in the browser menu.

The installed app opens {{origin}}/ and follows your device's light or dark setting (or the choice you made with the color-theme button in the menu).

## What works offline

| Works without a connection | Needs a connection |
| --- | --- |
| The editor (new posts, and posts you have opened before on this device) | Reading posts and profiles |
| Typing, formatting and checklists | Discover and search |
| Keeping drafts on the device | Uploading images |
| The "You're offline" page, which lists drafts waiting on your device | Settings, sign-in, sign-up |
| | Syncing your writing to the server |

Here is what happens when you write offline:

1. You type. Every change is saved on the device within a fraction of a second. The status reads "Offline · saved on this device".
2. When your connection returns, the editor syncs by itself and the status changes to "Draft saved" or "Saved".
3. If you pressed **Save** while offline, the post finishes publishing once you are back online. The editor tells you: "Saved on this device · it will finish saving when you're back online".

The editor opens offline after you have used it online once on that device. If you try to open a post for the first time while offline, the page says "This post isn't available offline yet. Open it once while you're online and it will be."

## Privacy on shared devices

- Each signed-in person has their own offline copy; one account's cached editor is never shown to another.
- **Sign out** asks you to confirm if drafts on this device have not synced yet, because signing out clears the device's copies. Sync first (reconnect and wait for "Saved"), then sign out.
- Drafts that never synced stay on the device, so the right account can recover them later. If you open the sign-in page and drafts on the device have not synced, a note says so and tells you to sign in to the account that wrote them.

## Updates

The app updates itself. When the site changes, the next time you open it you get the new version. If something looks stale, close and reopen the app, or reload the page.

## Troubleshooting

- **No install option:** not every browser offers installing. Installing also needs the site to be served over HTTPS (or from localhost while developing). If your browser has no install option, you can still use the site normally and write offline in a regular tab.
- **Stuck on an old version:** reload once while online.
- **Offline page instead of a post:** reading posts needs a connection; only the editor is cached.
