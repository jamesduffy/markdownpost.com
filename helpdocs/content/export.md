# Export your site

Your posts are yours. You can download all of them, with your images, profile and theme, as one zip file at any time.

## How to get it

Open Settings, Account ({{origin}}/settings/account/) and press **Download my data**. The zip is built on the spot and your browser saves it as `markdownpost-<username>.zip`.

- It includes **every post you wrote**: published, unlisted, private and drafts.
- It never includes anyone else's posts or data. It also leaves out your email address, password and agent tokens.
- Exports are limited to a few a day and to a maximum size; see [Limits and rate limits]({{origin}}/help/limits/). If your site is over the size limit you get a clear message, and the person who runs the site can build the export for you from the command line.

## What is inside

```
markdownpost-<username>.zip
  README.txt          a short description of the files
  manifest.json       the index: format, schema version, every post and image
  profile.json        profile text, links, site title, tagline, About text, theme
  posts/<id>.md       one file per post
  images/<name>       the images you uploaded
  avatar.webp         your profile photo, if you have one
```

### Posts

Each post is `posts/<id>.md`, where `<id>` is the post's address id (the last part of its link), so the name never changes. The file starts with YAML front matter and then your markdown, exactly as written:

```
---
title: "My post"
id: "a1B2c3D4"
visibility: public
draft: false
created: "2026-10-01T09:30:00Z"
updated: "2026-10-02T18:05:12Z"
---

The body of the post.
```

- `visibility` is `private`, `unlisted` or `public`.
- `draft` is `true` or `false`. A draft is visible only to you, whatever its visibility says.
- `title`, `id`, `created` and `updated` are quoted text. Dates are UTC.
- Images you uploaded are linked as `../images/<name>` (the live site uses `/media/images/<name>`). Links to images elsewhere on the web are left alone.

### manifest.json

```
{
  "format": "markdownpost-export",
  "schema_version": 1,
  "generated": "2026-10-30T12:00:00Z",
  "username": "you",
  "profile": "profile.json",
  "posts": [{"id": "...", "file": "posts/....md", "title": "...", "visibility": "public",
             "draft": false, "created": "...", "updated": "..."}],
  "images": [{"file": "images/....png", "size": 1234, "uploaded": "..."}],
  "avatar": "avatar.webp",
  "missing_images": []
}
```

`schema_version` goes up only when the layout changes in a way that breaks older readers. New optional fields can be added without changing it. `missing_images` lists any recorded image whose file could not be found in storage.

### profile.json

Your `username`, `full_name`, `location`, `bio`, `links` (website, github, linkedin, bluesky, mastodon, threads), `site_title`, `tagline`, `about_md`, `show_related_posts`, `theme` (the same settings you see in Settings, Look) and `avatar`.

## For site operators

```sh
docker compose exec web python manage.py export_account <username> -o /tmp/username.zip
```

The command writes the same zip with no size, time or rate limit. The web button is limited by `EXPORT_RATE_LIMIT`, `EXPORT_MAX_BYTES` and `EXPORT_MAX_SECONDS`.
