# Changelog

## [0.2.0](https://github.com/ravensorb/traefik-certificate-exporter/compare/v0.1.3...v0.2.0) (2026-09-01)


### Features

* **ci:** standard docker release tagging (semver + major.minor + major + sha + beta/latest) ([1c2453d](https://github.com/ravensorb/traefik-certificate-exporter/commit/1c2453dc5ea2f1040402f30bab212bbd50b6f651))
* **hooks:** support a configurable post-export command ([fd881d1](https://github.com/ravensorb/traefik-certificate-exporter/commit/fd881d120fa68e2370e74f3a9e9c2980356726f5))


### Bug Fixes

* **ci:** decouple build-container from build-package -- PyPI publish isn't configured yet, container builds shouldn't block on it ([e8e47f4](https://github.com/ravensorb/traefik-certificate-exporter/commit/e8e47f41c9ea00d5ab3f43cf9024b3a24a0b4835))
* **ci:** fix broken local act build (wrong cwd, missing platform mapping, no image name default) ([67fe6c2](https://github.com/ravensorb/traefik-certificate-exporter/commit/67fe6c243bd27fb7880dd95a865efe58155293ee))
* **ci:** package path/registry defaults and OCI source label ([eb68bc0](https://github.com/ravensorb/traefik-certificate-exporter/commit/eb68bc0f77d823e07eabca7d8d0f2070c3472e8a))
* **ci:** scope sha tag to branch builds, prefix it under dev- ([3613da8](https://github.com/ravensorb/traefik-certificate-exporter/commit/3613da8f76e60940bf237c43225882b60adcbf3c))
* **ci:** stop duplicate Authorization header breaking package publish ([ef1ca34](https://github.com/ravensorb/traefik-certificate-exporter/commit/ef1ca34b0471ad26a6402d99e3088ff5f22045b1))
* **config:** fix domain include/exclude across all config surfaces, add PKCS12 passphrase flag ([3d824f3](https://github.com/ravensorb/traefik-certificate-exporter/commit/3d824f34abd0489a67ab451e6ff9727bf1025ecb))
* **core:** redact secrets, fail loudly on bad paths, fix ACME export bugs ([8b7edd5](https://github.com/ravensorb/traefik-certificate-exporter/commit/8b7edd5769d5f8f2ba21330183de6ac33ee23fc2))
* **docker:** seed config.yaml on first boot, emit structured JSON file logs ([4de45d7](https://github.com/ravensorb/traefik-certificate-exporter/commit/4de45d70e90707c5e9f34ddd52e3cce4d6842227))
* revert bot-corrupted version, stop build-package running on every push ([ce61e05](https://github.com/ravensorb/traefik-certificate-exporter/commit/ce61e05e01f71bd9a4ae6c79857f3c0e8eff7d81))


### Reverts

* **ci:** restore build-container's needs: build-package (validation done) ([f2f82c8](https://github.com/ravensorb/traefik-certificate-exporter/commit/f2f82c8972e96655c66132d3b928e63b5fadc2db))


### Documentation

* add BMad planning artifacts, engineering guidelines, and PM state tracking ([c165db5](https://github.com/ravensorb/traefik-certificate-exporter/commit/c165db58ca960b46a0f8be58382a9d6076e55557))
* add security disclosure and contribution governance files ([a065155](https://github.com/ravensorb/traefik-certificate-exporter/commit/a0651558d2f2666244d4daaf09bff11b92ff8af6))
* **ci:** restore delivery pipeline planning ([5b0f5d3](https://github.com/ravensorb/traefik-certificate-exporter/commit/5b0f5d38eb09f87f2b890e99c955e039a2cc87bd))
* **review:** end-to-end architecture review after Epics 1-6; fix 2 permissions findings ([312eed7](https://github.com/ravensorb/traefik-certificate-exporter/commit/312eed79d0fcdf034845c5a4910542c83ffc22bc))
