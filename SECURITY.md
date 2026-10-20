# Security

Skill Atlas runs only on your machine. The server binds to `127.0.0.1`, and every API call must
send a token that changes each time the server starts. It writes only `skillOverrides` and
`enabledPlugins` in `settings.json`, the skill locks, and skill folders.

If you find a way for a web page or another user to make the server read or write files, report
it privately through **Security → Report a vulnerability** on GitHub. Do not open a public issue.
