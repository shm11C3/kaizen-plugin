# Third-party dependencies

The root [MIT License](LICENSE) covers this project's original code and documentation.
Dependencies retain their own licenses; the root license does not replace them.

The Discord adapter resolves its dependencies through
[`integrations/discord-mcp/package-lock.json`](integrations/discord-mcp/package-lock.json),
including `mcp-discord` and the Model Context Protocol SDK (MIT), and `discord.js`
(Apache-2.0). The Go observation templates import OpenTelemetry and `otelsql`;
those packages are fetched separately and are not vendored in this repository.

Use the dependency manifests and lockfiles for the exact versions. If distributing
bundles containing dependency code (for example, `node_modules`), retain the
applicable upstream license and NOTICE files.
