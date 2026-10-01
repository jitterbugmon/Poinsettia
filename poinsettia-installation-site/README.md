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
├── app.js           # Configures direct GitHub repository links
├── assets/
│   ├── poinsettia-logo.png
│   └── favicon.png
└── .nojekyll
```

There is **no Flask dependency, Python application, database, build step,
package installation, or custom backend** in this folder. Outfit loads from
Google Fonts with system-font fallbacks. The download links go straight to
GitHub Releases and do not require its API, an API key, or a login.

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

The red homepage buttons open the official GitHub Releases page. The guide
describes a clearly labelled unsigned beta Setup.exe if the official release
offers one, without claiming that an asset is currently published. That packaged installer
includes the app's Python runtime. The advanced ZIP/batch alternative remains:
install current stable Python 3.11+ from Python.org, download the Windows ZIP
asset if offered, extract it, and start `start_poinsettia.bat` only if Windows
allows it without bypassing a warning. First run downloads dependencies and
models and requires internet. For the installer, compare its SHA-256 with the
official `SHA256SUMS.txt` before opening it. The guide explains how to use
`Get-FileHash`; a matching hash does not establish that the software is safe.

Keep Windows Smart App Control enabled. The website does not guarantee that
any release or downloaded dependency is malware-free. If Windows blocks a
download or reports an unverified publisher, cancel rather than disabling
protections or choosing “Run anyway.” Only use packages from the official
release page and verify their publisher/checksum when available.

ZIP Unblock only clears the internet-download marker; it does not establish
trust or override Smart App Control. The unsigned installer can face the same
Windows warnings and blocks as the batch launcher. See
`windows_release/GITHUB_RELEASE.md` in the application repository for the
manual unsigned-beta Windows build and optional signed-build prerequisites;
this static website does not create or sign installers.

## Scope and safety

This is a separate installation/download frontend, **not** the Poinsettia
chat runtime. It does not implement WebGPU inference or change the approved
no-companion browser-app architecture. The Windows installer described here
is the existing native distribution.

Publish only these static website files. Never include `poinsettia.db`,
`user_files/`, credentials, or private application data. The existing public
application repository's historical data cleanup remains a separate,
unresolved decision; this work makes no remote repository changes.