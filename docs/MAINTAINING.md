# Repository and release safeguards

The main branch requires a pull request and these GitHub Actions checks: Windows tests, Apple silicon tests, Intel Mac tests, dependency audit, full-history credential scan, Python CodeQL and JavaScript CodeQL. Checks must apply to an up-to-date branch. Administrators are also bound by protection. Force pushes and branch deletion are disabled; merges keep linear history and discussions must be resolved.

No second-person approval is required because a sole maintainer cannot approve their own pull request. This is not permission to skip the automated checks. Use a focused branch and squash-merge a passing pull request. CodeQL findings that represent intended authenticated local destination selection are reviewed and recorded as false positives; actual network/path defects require fixes.

The security policy enables private vulnerability reporting. GitHub secret scanning, push protection, Dependabot alerts and security updates are enabled. Weekly dependency and history scans run alongside push/pull-request checks. Dependency updates are grouped to keep maintenance practical.

Desktop releases are explicitly dispatched from main after those checks pass. All three native build jobs must finish successfully before publication. Download the source archives/manifests alongside the binaries, inspect verification JSONs and checksums, and keep signing/notarization limitations visible. A failed build publishes no partial release.

Repository configuration is live GitHub state, not enforced by this text. Maintainers should inspect the branch-protection and security settings when changing workflows, especially if a required job is renamed or stops running for pull requests.
