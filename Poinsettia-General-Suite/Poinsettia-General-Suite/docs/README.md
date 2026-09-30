# Poinsettia GitHub Pages homepage

The static download homepage is in this directory. In the repository's **Settings → Pages**, choose **Deploy from a branch**, `main`, and `/docs`. The published address is `https://jitterbugmon.github.io/Poinsettia/` once Pages is enabled.

The **Install latest version** button queries the public GitHub Releases API for the latest release and activates only when that release contains a nonempty `Poinsettia-<version>-Windows-x64-Setup.exe` asset. It does not fall back to an unsigned ZIP or point to a non-existent executable. A downloaded program cannot be started automatically by a website: the visitor runs the installer, which launches Poinsettia after setup.

Before publishing a customer-facing installer, verify its Authenticode signature and test it on a clean Windows machine. The current release workflow does not enforce signing; do not describe an unverified installer as signed. The Windows app currently uses local Ollama, not WebGPU.

Do **not** publish `poinsettia.db`, `user_files/`, secret files, generated environments, or customer data to the public repository. Existing copies in Git history require separate cleanup; removing a file in a new commit does not erase prior copies.