# CI configuration provenance

Action revisions were checked against their official repositories on 2026-10-09:

- [actions/checkout commit](https://github.com/actions/checkout/commit/3d3c42e5aac5ba805825da76410c181273ba90b1)
- [actions/setup-python commit](https://github.com/actions/setup-python/commit/5fda3b95a4ea91299a34e894583c3862153e4b97)

The workflow uses the same external-staging bootstrap and installed-wheel check as local validation. It targets Windows and places generated work under D:\Codex. Hosted run results are available in the repository Actions tab. Local verification and hosted verification are separate records.
