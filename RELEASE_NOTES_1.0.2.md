# Guardians of the LANaxy 1.0.2

## Added

- Added an official LANaxy uninstaller with interactive removal options.
- Added support for a complete purge or removal while keeping configuration and runtime data.
- Added public deployment support for `https://lanaxy.de/uninstall.sh`.
- Added release assets and SHA-256 checksum generation for `uninstall.sh`.

## Improved

- The installer, updater and LANLord setup now include the uninstaller in their executable and validation paths.
- Documentation now covers LANaxy removal and the public uninstaller.
- CI now validates that the version documented in `README.md` matches `APP_VERSION`.
- The release workflow performs the same version consistency check before publishing.

## Versioning

From this release onward, the public semantic release line is authoritative. Historical internal test version numbers such as `1.35.x` are not part of the public release sequence.
