"""Trusted local administration. Run `python -m scripts.manage_local_identity --help`."""
import argparse
import getpass
import json
from src.daycover import auth


def main():
    parser=argparse.ArgumentParser(description='Manage local simulation identities; never official identity verification.')
    commands=parser.add_subparsers(dest='command',required=True)
    create=commands.add_parser('create');create.add_argument('alias');create.add_argument('role',choices=auth.ROLES)
    grant=commands.add_parser('grant');grant.add_argument('principal_id');grant.add_argument('merchant_id');grant.add_argument('--revoke',action='store_true')
    service=commands.add_parser('service-token');service.add_argument('principal_id');service.add_argument('--scope',action='append',required=True);service.add_argument('--ttl',type=int,default=3600);service.add_argument('--rotate',action='store_true')
    disable=commands.add_parser('disable');disable.add_argument('principal_id')
    args=parser.parse_args()
    if args.command=='create':
        password=None if args.role=='service' else getpass.getpass('Local password (12–128 characters): ')
        print(auth.provision(args.alias,args.role,password))
    elif args.command=='grant':
        auth.set_grant(args.principal_id,args.merchant_id,not args.revoke);print('Grant updated.')
    elif args.command=='disable':
        auth.disable(args.principal_id);print('Principal and credentials disabled.')
    else:
        # Intentional one-time output for administrator delivery; do not save to handoff/logs.
        print(json.dumps(auth.issue_service(args.principal_id,args.scope,args.ttl,args.rotate)))


if __name__=='__main__':
    main()
