#!/usr/bin/env python3
import getpass
import os
import shutil
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
TOKEN_FILE = ROOT / 'bot-token'
NODE = os.environ.get('DISCORD_MCP_NODE') or shutil.which('node')
SERVER = ROOT / 'server.mjs'

if sys.argv[1:] == ['--configure']:
    if not sys.stdin.isatty():
        sys.exit('Run --configure in your own interactive Terminal so the token stays hidden.')
    if any((directory / '.git').exists() for directory in (ROOT, *ROOT.parents)):
        sys.exit('Install outside the Git checkout before saving a token; see team/docs/DISCORD_SETUP.md.')
    token = getpass.getpass('Discord Bot Token (hidden): ').strip()
    if not token or any(c.isspace() for c in token):
        sys.exit('A non-empty Bot token without whitespace is required.')
    fd, temporary = tempfile.mkstemp(prefix='.bot-token-', dir=ROOT)
    try:
        with os.fdopen(fd, 'w') as output:
            output.write(token)
        os.replace(temporary, TOKEN_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('Bot token saved locally with mode 600. Value was not displayed.')
    sys.exit(0)

if sys.argv[1:]:
    sys.exit('Usage: launch.py [--configure]')
if not NODE or not Path(NODE).is_file():
    sys.exit('Node.js 24 is required. Set DISCORD_MCP_NODE to its absolute executable path.')
if not TOKEN_FILE.is_file():
    sys.exit('Discord Bot token is missing. Run this launcher with Python and --configure in your own Terminal.')
token = TOKEN_FILE.read_text().strip()
if not token:
    sys.exit('Discord Bot token is empty. Run launch.py --configure again in your own Terminal.')
environment = dict(os.environ)
environment['DISCORD_TOKEN'] = token
environment['DISCORD_MCP_ROOT'] = str(ROOT)
os.chdir(ROOT)
os.execve(NODE, [NODE, str(SERVER)], environment)
