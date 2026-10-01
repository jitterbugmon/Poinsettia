"""Linux-runnable contract tests for Windows release signing/mode gates."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_release"))
BUILDER = (ROOT / "windows_release/tools/build_release.ps1").read_text(
    encoding="utf-8"
)
WORKFLOW = (ROOT / ".github/workflows/windows-release.yml").read_text(
    encoding="utf-8"
)


class WindowsReleaseGuardTests(unittest.TestCase):
    def test_pyinstaller_collects_imports_for_compiled_site_runtime(self):
        self.assertIn("--hidden-import sqlite3", BUILDER)
        self.assertIn("--hidden-import _sqlite3", BUILDER)
        self.assertIn("--hidden-import bs4", BUILDER)
        self.assertIn("--hidden-import werkzeug.security", BUILDER)
        requirements = (ROOT / "windows_release/requirements.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("beautifulsoup4>=", requirements)

    def test_windows_startup_uses_existing_account_consent_instead_of_duplicate_gate(self):
        shell_html = (ROOT / "windows_release/web/desktop_shell.html").read_text(
            encoding="utf-8"
        )
        shell_js = (ROOT / "windows_release/web/desktop_shell.js").read_text(
            encoding="utf-8"
        )
        shell_backend = (
            ROOT / "windows_release/poinsettia_windows/desktop_shell.py"
        ).read_text(encoding="utf-8")
        website = (ROOT / "templates/index.html").read_text(encoding="utf-8")

        self.assertNotIn('id="legal-gate"', shell_html)
        self.assertNotIn('id="accept-button"', shell_html)
        self.assertIn('message.type !== "poinsettia-account-consent"', shell_js)
        self.assertIn("event.origin !== new URL(state.siteUrl).origin", shell_js)
        self.assertIn('fetch("/api/account-consent"', shell_js)
        self.assertIn('@app.post("/api/account-consent")', shell_backend)
        self.assertIn("window.parent.postMessage({", website)
        self.assertIn("eulaVersion: user.eula_version", website)
        self.assertIn("privacyVersion: user.privacy_version", website)

    def test_completed_model_progress_disappears_after_three_seconds(self):
        shell_js = (ROOT / "windows_release/web/desktop_shell.js").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'data.phase === "ready" && percent === 100 && !state.hideTimer',
            shell_js,
        )
        self.assertIn('classList.add("hidden")', shell_js)
        self.assertIn("}, 3000);", shell_js)

    def test_local_model_setup_waits_for_account_consent(self):
        from poinsettia_windows.desktop_shell import create_shell_app

        class StubConsent:
            accepted_value = False

            def accepted(self):
                return self.accepted_value

            def accept(self):
                self.accepted_value = True

        class StubOllama:
            started = False

            def start(self):
                self.started = True

            def snapshot(self):
                return {"phase": "not_started"}

        consent = StubConsent()
        ollama = StubOllama()
        with patch(
            "poinsettia_windows.desktop_shell.ConsentStore",
            return_value=consent,
        ):
            app = create_shell_app("http://127.0.0.1:43123", ollama)

        client = app.test_client()
        state = client.get("/api/state").get_json()
        self.assertEqual(state["site_url"], "http://127.0.0.1:43123/chat")
        self.assertNotIn("consent_accepted", state)
        self.assertEqual(client.post("/api/bootstrap/start").status_code, 423)
        self.assertFalse(ollama.started)

        rejected = client.post(
            "/api/account-consent",
            headers={"Origin": "https://untrusted.example"},
        )
        self.assertEqual(rejected.status_code, 403)
        self.assertFalse(consent.accepted())

        accepted = client.post(
            "/api/account-consent",
            headers={"Origin": "http://localhost"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(accepted.get_json()["consent_accepted"])
        self.assertFalse(ollama.started)

        self.assertEqual(client.post("/api/bootstrap/start").status_code, 200)
        self.assertTrue(ollama.started)

    def test_builder_verifies_authenticode_and_expected_signer(self):
        self.assertIn("function Assert-ReleaseSignature", BUILDER)
        self.assertIn(
            "Get-AuthenticodeSignature -FilePath $Path",
            BUILDER,
        )
        self.assertIn(
            "$signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid",
            BUILDER,
        )
        self.assertIn(
            "$actualThumbprint -ne $expectedThumbprint",
            BUILDER,
        )
        self.assertIn("Assert-ReleaseSignature -Path $Path", BUILDER)
        self.assertIn("Sign-ReleaseFile -Path $MainExecutable", BUILDER)
        self.assertIn(
            "Sign-ReleaseFile -Path $InstallerExecutable.FullName",
            BUILDER,
        )

    def test_required_signing_rejects_missing_thumbprint(self):
        self.assertIn(
            'if ($RequireSignature -and !$SigningCertificateThumbprint)',
            BUILDER,
        )
        self.assertIn(
            'throw "Set POINSETTIA_SIGNING_CERTIFICATE_THUMBPRINT before using -RequireSignature."',
            BUILDER,
        )

    def test_workflow_offers_unsigned_beta_and_signed_manual_modes(self):
        self.assertIn("workflow_dispatch:", WORKFLOW)
        self.assertIn("installer_mode:", WORKFLOW)
        self.assertIn("default: unsigned-beta", WORKFLOW)
        self.assertIn("- unsigned-beta", WORKFLOW)
        self.assertIn("- signed", WORKFLOW)
        self.assertIn("POINSETTIA_INSTALLER_MODE: ", WORKFLOW)
        self.assertIn(
            "${{ github.event.inputs.installer_mode || 'unsigned-beta' }}",
            WORKFLOW,
        )

    def test_unsigned_beta_clears_thumbprint_only_for_non_tag_builds(self):
        self.assertIn(
            '$isUnsignedBeta = !$isTagBuild -and $installerMode -eq "unsigned-beta"',
            WORKFLOW,
        )
        self.assertIn(
            "if ($isUnsignedBeta) {",
            WORKFLOW,
        )
        self.assertIn(
            '$env:POINSETTIA_SIGNING_CERTIFICATE_THUMBPRINT = ""',
            WORKFLOW,
        )
        self.assertIn(
            "$requireSignature = $isTagBuild -or $installerMode -eq \"signed\"",
            WORKFLOW,
        )

    def test_tag_and_manual_signed_builds_require_and_verify_signatures(self):
        self.assertIn(
            "POINSETTIA_SIGNING_CERTIFICATE_THUMBPRINT: "
            "${{ vars.POINSETTIA_SIGNING_CERTIFICATE_THUMBPRINT }}",
            WORKFLOW,
        )
        self.assertIn(
            "if: startsWith(github.ref, 'refs/tags/') || "
            "github.event.inputs.installer_mode == 'signed'",
            WORKFLOW,
        )
        self.assertIn(
            "POINSETTIA_RELEASE_REF_NAME: ${{ github.ref_name }}",
            WORKFLOW,
        )
        self.assertIn(
            "POINSETTIA_RELEASE_REF_TYPE: ${{ github.ref_type }}",
            WORKFLOW,
        )
        self.assertIn("$buildParameters = @{", WORKFLOW)
        self.assertIn("PackageVersion = $version", WORKFLOW)
        self.assertIn("CreateInstaller = $true", WORKFLOW)
        self.assertIn("RequireSignature = $requireSignature", WORKFLOW)
        self.assertIn(
            ".\\windows_release\\tools\\build_release.ps1 @buildParameters",
            WORKFLOW,
        )
        self.assertNotIn("$buildArgs = @(", WORKFLOW)
        self.assertNotIn('@("-PackageVersion"', WORKFLOW)
        build_start = WORKFLOW.index("- name: Build installer")
        verify_start = WORKFLOW.index("- name: Verify signed installer signature")
        upload_start = WORKFLOW.index("- name: Upload installer artifact")
        publish_start = WORKFLOW.index("- name: Publish GitHub Release")
        build_block = WORKFLOW[build_start:verify_start]
        build_script = build_block.split("run: |", 1)[1]
        self.assertNotIn("${{ github.ref_name }}", build_script)
        self.assertNotIn("${{ github.ref_type }}", build_script)
        self.assertLess(verify_start, upload_start)
        self.assertLess(verify_start, publish_start)
        self.assertIn(
            "$signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid",
            WORKFLOW,
        )
        self.assertIn("$actualThumbprint -ne $expectedThumbprint", WORKFLOW)
        self.assertIn("name: poinsettia-windows-installer-", WORKFLOW)
        self.assertIn("'unsigned-beta'", WORKFLOW)
        self.assertIn("Set-Content windows_release\\build\\installer\\SHA256SUMS.txt", WORKFLOW)

    def test_manual_builds_never_publish_and_tag_release_is_push_only(self):
        release_step = WORKFLOW.split("- name: Publish GitHub Release", 1)[1]
        self.assertIn(
            "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')",
            release_step,
        )
        self.assertNotIn("github.event_name == 'workflow_dispatch'", release_step)


if __name__ == "__main__":
    unittest.main()