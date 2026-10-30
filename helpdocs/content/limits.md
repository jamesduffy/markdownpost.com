# Limits and rate limits

These tables are built from this server's running configuration, so they match what the server actually enforces. The person who runs a site can change the rate limits and upload limits with settings, so other MarkdownPost sites may differ.

{{limits_table}}

## How rate limits behave

- A limit counts events inside a **sliding window**: "5 per 15 minutes" means no more than 5 in any 15-minute stretch. The count falls as old events age out; you do not wait for a fixed reset time.
- When a page limit is hit, you see "Too many attempts" with a wait time. For agents the reply is HTTP 429 with a `Retry-After` header, or a tool error that names the limit.
- Limits are kept in the database, so they are shared by every server process and survive restarts.
- Failed sign-ins are tracked by the address the request comes from. Behind a proxy, the site must be configured to read the real visitor address; otherwise everyone would share one budget (see [For site owners and admins]({{origin}}/help/site-owners/)).
- The editor's autosave is not rate limited. Agent edits and new posts are, to stop flooding.

## Content limits you may meet

| What | Limit |
| --- | --- |
| Username | letters, numbers, dots, dashes, underscores; starts with a letter or number; reserved names refused |
| Full name, location | 80 characters |
| Bio | 300 characters |
| Site title | 80 characters |
| Tagline | 140 characters |
| About text | 5,000 characters |
| Agent token name | 60 characters |
| Search words | 100 characters |
| Agent `client_id` | 8 to 64 letters, digits, `-`, `_` |
| Image alt text from an agent | up to 200 characters, one line, no square brackets |
| Searchable part of a post | first 20,000 characters |

## If you are blocked

- Wait. The count falls by itself.
- A site admin can clear a block immediately by deleting your entries under "Rate limit events" in the admin.
