# Browser access for the development host

The development role installs ChatGPT and Google Chrome. It does not copy
browser profiles, account tokens, pairing records, or privacy consent.

1. Sign into ChatGPT on this host with your own account.
2. Open **Settings > Computer Use** and select **Install** beside Google Chrome.
3. Install the official ChatGPT extension and review its permission prompt.
4. Confirm Chrome shows **Manage**, a green indicator, and an enabled toggle.
5. In a chat on this host, test `@Chrome open example.com`.

Keep website approval prompts enabled unless you explicitly choose otherwise.
Chrome sign-in for side chat is separate from desktop app sign-in.
Complete macOS Accessibility or Screen Recording prompts only when required
for your intended workflow. The playbook does not modify the TCC database.

For phone or laptop access, pair this host under **Settings > Connections >
Control this Mac**. Keep the app running. After a VM restart, sign into macOS
before expecting desktop remote access. Automatic macOS login is not enabled.

See the [official browser setup guide](https://learn.chatgpt.com/docs/chrome-extension)
and [remote connection guide](https://learn.chatgpt.com/docs/remote-connections).
