#!/opt/nanohub/venv/bin/python3
"""
NanoHUB User Roles Management CLI
=================================

Manage user role overrides in the database.

Usage:
    python3 manage_roles.py list                       # List all role overrides
    python3 manage_roles.py get <username>             # Get role for user
    python3 manage_roles.py set <username> <role>      # Set role (admin, bel-admin, operator, report)
    python3 manage_roles.py set <username> <role> --filter 'bel-%'  # With manifest filter
    python3 manage_roles.py remove <username>          # Remove role override (soft delete)
    python3 manage_roles.py delete <username>          # Permanently delete role override

Examples:
    python3 manage_roles.py set john.doe admin
    python3 manage_roles.py set jane.smith bel-admin --filter 'bel-%'
    python3 manage_roles.py set bob.user operator --notes 'Temporary access for project X'
    python3 manage_roles.py list
"""

import sys
import argparse
from db_utils import user_roles


def cmd_list(args):
    """List all user role overrides."""
    users = user_roles.get_all_users(include_inactive=args.all)

    if not users:
        print("No user role overrides found.")
        return

    print(f"\n{'Username':<25} {'Role':<12} {'Filter':<15} {'Active':<8} {'Source':<20}")
    print("-" * 80)

    for u in users:
        active = "Yes" if u['is_active'] else "No"
        filter_val = u['manifest_filter'] or '-'
        notes = f" ({u['notes'][:30]}...)" if u.get('notes') and len(u['notes']) > 30 else (f" ({u['notes']})" if u.get('notes') else "")
        created_by = u.get('created_by') or 'system'
        print(f"{u['username']:<25} {u['role']:<12} {filter_val:<15} {active:<8} {created_by:<20}{notes}")

    print(f"\nTotal: {len(users)} user(s)")


def cmd_get(args):
    """Get role for a specific user."""
    username = args.username.lower()
    role_info = user_roles.get_user_role(username)

    if role_info:
        print(f"\nUser: {role_info['username']}")
        print(f"Role: {role_info['role']}")
        print(f"Manifest Filter: {role_info['manifest_filter'] or 'None (full access)'}")
        print(f"Active: {'Yes' if role_info['is_active'] else 'No'}")
        print(f"Created: {role_info['created_at']} by {role_info['created_by'] or 'system'}")
        if role_info.get('notes'):
            print(f"Notes: {role_info['notes']}")

        # Show permissions
        perms = user_roles.get_permissions_for_role(role_info['role'])
        print(f"Permissions: {', '.join(perms)}")
    else:
        print(f"No database role override found for '{username}'")
        print("User will use LDAP-derived role.")


def cmd_set(args):
    """Set role for a user."""
    username = args.username.lower()
    role = args.role.lower()

    # Validate role
    if role not in user_roles.ROLES:
        print(f"Error: Invalid role '{role}'")
        print(f"Valid roles: {', '.join(user_roles.ROLES.keys())}")
        sys.exit(1)

    success = user_roles.set_user_role(
        username=username,
        role=role,
        manifest_filter=args.filter,
        created_by=args.by or 'cli',
        notes=args.notes
    )

    if success:
        print(f"Successfully set role for '{username}': {role}")
        if args.filter:
            print(f"  Manifest filter: {args.filter}")
        if args.notes:
            print(f"  Notes: {args.notes}")
    else:
        print(f"Failed to set role for '{username}'")
        sys.exit(1)


def cmd_remove(args):
    """Remove (deactivate) role override for a user."""
    username = args.username.lower()

    success = user_roles.remove_user_role(username)

    if success:
        print(f"Successfully removed role override for '{username}'")
        print("User will now use LDAP-derived role.")
    else:
        print(f"Failed to remove role override for '{username}'")
        sys.exit(1)


def cmd_delete(args):
    """Permanently delete role override for a user."""
    username = args.username.lower()

    if not args.force:
        confirm = input(f"Permanently delete role override for '{username}'? [y/N]: ")
        if confirm.lower() != 'y':
            print("Aborted.")
            return

    success = user_roles.delete_user_role(username)

    if success:
        print(f"Successfully deleted role override for '{username}'")
    else:
        print(f"Failed to delete role override for '{username}'")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='NanoHUB User Roles Management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # List command
    list_parser = subparsers.add_parser('list', help='List all role overrides')
    list_parser.add_argument('-a', '--all', action='store_true', help='Include inactive users')
    list_parser.set_defaults(func=cmd_list)

    # Get command
    get_parser = subparsers.add_parser('get', help='Get role for a user')
    get_parser.add_argument('username', help='Username to look up')
    get_parser.set_defaults(func=cmd_get)

    # Set command
    set_parser = subparsers.add_parser('set', help='Set role for a user')
    set_parser.add_argument('username', help='Username')
    set_parser.add_argument('role', help='Role (admin, bel-admin, operator, report)')
    set_parser.add_argument('--filter', help='Manifest filter (e.g., bel-%%)')
    set_parser.add_argument('--notes', help='Notes about this role assignment')
    set_parser.add_argument('--by', help='Admin username making the change')
    set_parser.set_defaults(func=cmd_set)

    # Remove command
    remove_parser = subparsers.add_parser('remove', help='Remove role override (soft delete)')
    remove_parser.add_argument('username', help='Username')
    remove_parser.set_defaults(func=cmd_remove)

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Permanently delete role override')
    delete_parser.add_argument('username', help='Username')
    delete_parser.add_argument('-f', '--force', action='store_true', help='Skip confirmation')
    delete_parser.set_defaults(func=cmd_delete)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == '__main__':
    main()
