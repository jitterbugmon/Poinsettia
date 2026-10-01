"""Linux-runnable contract tests for Windows release signing/mode gates."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUILDER = (ROOT / "windows_release/tools/build_release.ps1").read_text(
    encoding="utf-8"
)
WORKFLOW = (ROOT / ".github/workflows/windows-release.yml").read_text(
    encoding="utf-8"
)


class WindowsReleaseGuardTests(unittest.TestCase):
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