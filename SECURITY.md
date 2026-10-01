# Security

PenguCost is designed primarily for private LAN/VPN deployments.

## Recommendations

- Put Internet-exposed instances behind HTTPS and an access-control layer.
- Keep Proxmox, Docker and PenguCost updated.
- Back up `/data` or the complete LXC regularly.
- Use a strong administrator password.
- Do not expose port 8080 directly to the public Internet.
- Treat the local data volume as sensitive because it contains financial metadata and the local key material used to decrypt configured AI API keys.

## Multi-user privacy

Expenses, contracts, dashboard calculations, reminder actions and AI analysis payloads are scoped to the authenticated user. The administrator can manage user accounts and global account/category templates. Normal application endpoints do not expose another user's financial records; the only deliberate exception is the explicit administrator full-export/full-restore feature documented below.

Global accounts and categories can be hidden by a member without deleting them for other users. Only an administrator can create or globally delete these shared templates.

## AI

AI profiles are managed only by administrators. Normal users can select enabled profiles for an analysis but do not receive configured base URLs or API-key state from the public profile endpoint. API keys are encrypted at rest using the local PenguCost encryption key.

When an external provider is used, only the authenticated user's explicitly selected financial entries, that user's AI conversation history and that user's Brain context are supplied to the model. Selected entry IDs are revalidated server-side before every AI turn. Ollama or another local endpoint can be used to keep AI traffic local.

AI conversations and Brain memory are stored per user in SQLite. A normal administrator cannot browse another user's conversations through the application UI/API; they are included only in the explicit privileged full-instance backup/restore path.

## Reporting

For a public repository, add your preferred private vulnerability-reporting contact before the first public release.
## Export files

Personal user exports contain that user's private recurring-cost and contract data plus that user's AI conversation history and Brain memory. Administrator full exports are more sensitive: they contain all users' data, password hashes and AI API keys in a restorable form. Store full export JSON files like backups or secrets, do not commit them to Git, and transfer them only over trusted channels.

The normal administrator UI still does not expose another user's cost data. The full export is an explicit privileged backup/restore action and should only be used by a trusted instance administrator.

## Financial data isolation

Income entries, expenses, contracts, dashboard selections, reminders and AI payloads are scoped to the authenticated owner. Administrator privileges do not expose another user's financial entries through normal application views; only the explicit full-instance backup/restore path contains all users' data.
