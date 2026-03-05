"""
Bulk reassign all workspace members to new roles across all workspaces in your organisation.

Usage:
    # List roles to find IDs
    python bulk_update_roles.py --base-url <url> --api-key <key> --list-roles

    # List all users and their current roles
    python bulk_update_roles.py --base-url <url> --api-key <key> --list-users

    # Preview changes
    python bulk_update_roles.py --base-url <url> --api-key <key> --mappings-file mappings.json --dry-run

    # Apply changes
    python bulk_update_roles.py --base-url <url> --api-key <key> --mappings-file mappings.json

mappings.json format:
    {
        "<old-role-id>": "<new-role-id>",
        "<old-role-id>": "<new-role-id>"
    }

Environment variables (alternative to CLI flags):
    LANGSMITH_API_KEY   API key
    LANGSMITH_BASE_URL  Base URL (default: https://api.smith.langchain.com)
"""

import argparse
import json
import os
import sys

import requests


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def get(base_url: str, api_key: str, path: str, workspace_id: str | None = None, **params) -> list | dict:
    headers = {"x-api-key": api_key}
    if workspace_id:
        headers["X-Tenant-Id"] = workspace_id
    resp = requests.get(f"{base_url}{path}", headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()


def patch(base_url: str, api_key: str, path: str, workspace_id: str, body: dict) -> None:
    headers = {"x-api-key": api_key, "X-Tenant-Id": workspace_id}
    resp = requests.patch(f"{base_url}{path}", headers=headers, json=body)
    resp.raise_for_status()


def fetch_org_roles(base_url: str, api_key: str) -> list[dict]:
    return get(base_url, api_key, "/api/v1/orgs/current/roles")


def fetch_all_members(base_url: str, api_key: str, workspace_id: str) -> list[dict]:
    members, offset, limit = [], 0, 100
    while True:
        page = get(
            base_url, api_key,
            "/api/v1/workspaces/current/members/active",
            workspace_id=workspace_id,
            offset=offset,
            limit=limit,
        )
        members.extend(page)
        offset += limit
        if len(page) < limit:
            return members


def build_role_names(roles: list[dict]) -> dict[str, str]:
    return {str(r["id"]): r.get("display_name") or r["name"] for r in roles}


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def list_roles(base_url: str, api_key: str) -> None:
    roles = sorted(
        fetch_org_roles(base_url, api_key),
        key=lambda r: (r.get("access_scope") or "", r["name"], (r.get("display_name") or r["name"]).lower()),
    )
    print(f"  {'ID':<36}  {'SCOPE':<12}  {'DISPLAY NAME':<30}  TYPE")
    print(f"  {'-'*36}  {'-'*12}  {'-'*30}  ----")
    for r in roles:
        print(f"  {r['id']:<36}  {r.get('access_scope') or '—':<12}  {r.get('display_name') or '—':<30}  {r['name']}")


def list_users(base_url: str, api_key: str) -> None:
    role_names = build_role_names(fetch_org_roles(base_url, api_key))
    workspaces = get(base_url, api_key, "/api/v1/workspaces")
    for ws in workspaces:
        ws_id = str(ws["id"])
        members = fetch_all_members(base_url, api_key, ws_id)
        print(f"Workspace: {ws.get('display_name', ws_id)}  ({len(members)} active members)")
        print(f"  {'EMAIL':<40}  {'ORG ROLE':<30}  WORKSPACE ROLE")
        print(f"  {'-'*40}  {'-'*30}  --------------")

        rows = [
            (
                m.get("email", m["id"]),
                m.get("org_role_name") or "—",
                role_names.get(str(m.get("role_id") or ""), "—"),
            )
            for m in members
        ]
        for email, org_role, ws_role in sorted(rows, key=lambda r: (r[2], r[0])):
            print(f"  {email:<40}  {org_role:<30}  {ws_role}")
        print()


def run(base_url: str, api_key: str, role_mapping: dict[str, str], dry_run: bool) -> None:
    roles = fetch_org_roles(base_url, api_key)
    role_names = build_role_names(roles)
    org_admin_role_id = next((str(r["id"]) for r in roles if r.get("name") == "ORGANIZATION_ADMIN"), None)

    def label(role_id: str) -> str:
        return role_names.get(role_id, role_id or "no role")

    workspaces = get(base_url, api_key, "/api/v1/workspaces")
    print(f"Found {len(workspaces)} workspace(s).\n")
    total_updated = 0

    for ws in workspaces:
        ws_id = str(ws["id"])
        members = fetch_all_members(base_url, api_key, ws_id)
        print(f"Workspace: {ws.get('display_name', ws_id)}  ({len(members)} active members)")

        for member in members:
            current_role = str(member.get("role_id") or "")
            new_role = role_mapping.get(current_role)
            email = member.get("email", member["id"])
            is_org_admin = org_admin_role_id and str(member.get("org_role_id") or "") == org_admin_role_id

            if dry_run:
                if is_org_admin and new_role:
                    print(f"  [skipped]      {email}  (org admin: change org role first)")
                elif new_role:
                    print(f"  [would update] {email}  {label(current_role)} → {label(new_role)}")
                else:
                    print(f"  [no mapping]   {email}  ({label(current_role)})")
                continue

            if not new_role:
                continue

            try:
                patch(
                    base_url, api_key,
                    f"/api/v1/workspaces/current/members/{member['id']}",
                    workspace_id=ws_id,
                    body={"role_id": new_role},
                )
                print(f"  Updated {email}: {label(current_role)} → {label(new_role)}")
                total_updated += 1
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 400:
                    print(f"  Skipped {email}: {e.response.json().get('detail', e)}")
                else:
                    raise

        print()

    if not dry_run:
        print(f"Done. {total_updated} member(s) updated.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def load_mappings(path: str) -> dict[str, str]:
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Mappings file not found: {path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {path}: {e}")
        sys.exit(1)
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        print("ERROR: Mappings file must be a JSON object mapping string role IDs to string role IDs.")
        sys.exit(1)
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bulk update LangSmith workspace member roles.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-k", "--api-key", default=os.environ.get("LANGSMITH_API_KEY"),
                        help="LangSmith API key (or set LANGSMITH_API_KEY env var).")
    parser.add_argument("-u", "--base-url", default=os.environ.get("LANGSMITH_BASE_URL", "https://api.smith.langchain.com"),
                        help="LangSmith base URL (default: https://api.smith.langchain.com).")
    parser.add_argument("-m", "--mappings-file", metavar="FILE",
                        help='Path to a JSON file mapping old role IDs to new role IDs: {"<old-id>": "<new-id>", ...}')
    parser.add_argument("-d", "--dry-run", action="store_true", help="Preview changes without applying them.")
    parser.add_argument("-r", "--list-roles", action="store_true", help="Print current org role IDs and exit.")
    parser.add_argument("-l", "--list-users", action="store_true", help="Print all workspace members and their current roles, then exit.")
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: API key required. Pass --api-key or set LANGSMITH_API_KEY.")
        sys.exit(1)

    if args.list_roles:
        list_roles(args.base_url, args.api_key)
    elif args.list_users:
        list_users(args.base_url, args.api_key)
    else:
        if not args.mappings_file:
            print("ERROR: --mappings-file is required.")
            parser.print_help()
            sys.exit(1)
        run(args.base_url, args.api_key, load_mappings(args.mappings_file), dry_run=args.dry_run)
