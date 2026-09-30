# Poinsettia installation website

A standalone, frontend-only marketing and download website. It reuses the
Poinsettia logo, favicon, Outfit font, and dark/red theme. It describes
conversation, research/citations, images/audio, files, and the P2/P3/P4 models.

## Files

```text
poinsettia-installation-site/
├── index.html       # Capabilities, models, and installation guide
├── styles.css       # Responsive theme
├── config.js        # Public GitHub repository setting
├── app.js           # Latest release lookup and download link
├── assets/
│   ├── poinsettia-logo.png
│   └── favicon.png
└── .nojekyll
```

There is **no Flask dependency, Python application, database, build step,
package installation, or custom backend** in this folder. Outfit loads from
Google Fonts with system-font fallbacks; the download lookup uses GitHub's
public Releases API. No API key or login is required.

## Preview

You can open `index.html` in a browser. For a local HTTP preview, from the
workspace root:

```sh
python -m http.server 8000 --directory poinsettia-installation-site
```

This optional preview command is just a static file server, not a backend
needed by the published site.

## Publish on GitHub Pages

### In a separate website repository

1. Put the **contents of this folder** at the root of that repository, keeping
   the `assets/` directory and `.nojekyll` file.
2. In **Settings → Pages**, choose **Deploy from a branch**.
3. Select your website branch (usually `main`) and **`/ (root)`**, then save.

### Alongside application source in an existing repository

Put this folder's contents in the repository's root-level `docs/` folder, then
choose that branch and **`/docs`** in Pages settings. GitHub Pages' branch
source does not support selecting an arbitrary folder such as
`poinsettia-installation-site/`; alternatively use an Actions deployment that
uploads this folder as its Pages artifact.

All asset paths are relative, so the site works at a domain root or a GitHub
Pages repository subpath.

## Configure the download

Edit the public `repository` setting in `config.js`:

```js
repository: "jitterbugmon/Poinsettia"
```

It refers to the repository that holds the application releases, which can
differ from the repository hosting this website.

The top **Install latest version** button activates only when the latest
public GitHub release contains a nonempty asset named
`Poinsettia-<version>-Windows-x64-Setup.exe`. Missing assets, failed requests,
and API rate limits show a clear message and leave the release-page link
available. The website cannot execute a downloaded installer; visitors must
open it themselves. It does not verify Authenticode signatures or claim an
installer is signed.

## Scope and safety

This is a separate installation/download frontend, **not** the Poinsettia
chat runtime. It does not implement WebGPU inference or change the approved
no-companion browser-app architecture. The Windows installer described here
is the existing native distribution.

Publish only these static website files. Never include `poinsettia.db`,
`user_files/`, credentials, or private application data. The existing public
application repository's historical data cleanup remains a separate,
unresolved decision; this work makes no remote repository changes.