# LangSmith Bulk Role Update

Bulk reassigns workspace members to new roles across all workspaces in your organisation. Useful when you need to migrate users from one set of roles to another, for example after creating custom roles with a different set of permissions.

## Requirements

```bash
pip install -r requirements.txt
```

## Usage

### 1. Find your role IDs

```bash
python bulk_update_roles.py --base-url <url> --api-key <key> --list-roles
```

This prints all roles in your org with their IDs, scope, display name, and internal type:

```
  ID                                    SCOPE         DISPLAY NAME                    TYPE
  ------------------------------------  ------------  ------------------------------  ----
  ff429cd7-...                          workspace     Admin                           WORKSPACE_ADMIN
  6ff50215-...                          workspace     Admin (No Deployment)           CUSTOM
  ...
```

### 2. Review current user assignments (optional)

```bash
python bulk_update_roles.py --base-url <url> --api-key <key> --list-users
```

### 3. Create a mappings file

Copy `mappings.json` and fill in the role IDs you want to migrate from and to:

```json
{
  "<existing-admin-role-id>":    "<admin-no-deploy-role-id>",
  "<existing-editor-role-id>":   "<editor-no-deploy-role-id>",
  "<existing-readonly-role-id>": "<readonly-no-deploy-role-id>"
}
```

Each key is a role ID to replace; each value is the role ID to assign instead. Any member whose current role isn't in the mapping is left unchanged.

### 4. Preview changes

```bash
python bulk_update_roles.py --base-url <url> --api-key <key> --mappings-file mappings.json --dry-run
```

Output shows what would happen for every member:

```
Workspace: Acme Corp  (12 active members)
  [would update] alice@example.com  Admin → Admin (No Deployment)
  [no mapping]   bob@example.com  (Admin (No Deployment))
  [skipped]      charlie@example.com  (org admin: change org role first)
```

### 5. Apply changes

```bash
python bulk_update_roles.py --base-url <url> --api-key <key> --mappings-file mappings.json
```

### To revert

Swap the keys and values in your mappings file (see `mappings-reverse.json`) and run again.

## Options

| Flag | Description |
|------|-------------|
| `--api-key` | LangSmith API key. Alternatively set `LANGSMITH_API_KEY`. |
| `--base-url` | Base URL (default: `https://api.smith.langchain.com`). Alternatively set `LANGSMITH_BASE_URL`. |
| `--mappings-file` | Path to JSON file mapping old role IDs to new role IDs. |
| `--dry-run` | Preview changes without applying them. |
| `--list-roles` | Print all org roles with IDs and exit. |
| `--list-users` | Print all workspace members and their current roles and exit. |

## Notes

- **Org admins** cannot have their workspace role changed via this script. The API blocks it; their org role must be changed to Organisation User first. They are flagged in both dry-run and live output.
- Changes propagate within a couple of minutes.
- The script pages through members in batches of 100 and processes all workspaces in the org.
