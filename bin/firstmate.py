#!/usr/bin/env python3
"""Verify and isolate the pinned First Mate distribution; never install hooks."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
VENDOR=ROOT/'vendor/firstmate'
class UpstreamError(ValueError): pass

def verify(archive=None):
    archive=Path(archive) if archive else VENDOR/'source.tar.gz'
    meta=json.loads((VENDOR/'manifest.json').read_text())
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=meta['sha256']:
        raise UpstreamError('Upstream archive digest mismatch')
    return meta

def safe_extract(archive,destination):
    destination=Path(destination).absolute()
    if destination.exists(): raise UpstreamError('Destination already exists')
    with tarfile.open(archive) as t:
        members=t.getmembers(); names=set(); links=set()
        for member in members:
            p=PurePosixPath(member.name)
            if p.is_absolute() or '..' in p.parts or not p.parts:
                raise UpstreamError('Unsafe archive path')
            if member.name in names:raise UpstreamError('Duplicate archive path')
            names.add(member.name)
            if not (member.isdir() or member.isfile() or member.issym()):
                raise UpstreamError('Unsupported archive member')
            if member.issym():
                link=PurePosixPath(member.linkname)
                if link.is_absolute():raise UpstreamError('Unsafe archive link')
                resolved=(destination/str(p.parent)/str(link)).resolve()
                if destination not in resolved.parents:raise UpstreamError('Escaping archive link')
                links.add(member.name)
        for member in members:
            if any(str(parent) in links for parent in PurePosixPath(member.name).parents):
                raise UpstreamError('Archive writes through a symlink')
        destination.parent.mkdir(parents=True,exist_ok=True)
        temporary=Path(tempfile.mkdtemp(prefix='.firstmate-',dir=destination.parent))
        try:
            temporary.chmod(0o700)
            for member in members:
                p=temporary/member.name
                if member.isdir():p.mkdir(parents=True,exist_ok=True)
                elif member.isfile():
                    p.parent.mkdir(parents=True,exist_ok=True)
                    with t.extractfile(member) as src,p.open('xb') as dst:shutil.copyfileobj(src,dst)
                    p.chmod(0o700 if member.mode & 0o111 else 0o600)
            for member in members:
                if member.issym():
                    p=temporary/member.name;p.parent.mkdir(parents=True,exist_ok=True);p.symlink_to(member.linkname)
            # Validate the completed graph, not just individual lexical targets.
            for name in links:
                try:
                    resolved = (temporary / name).resolve()
                except (OSError, RuntimeError) as exc:
                    raise UpstreamError('Invalid archive symlink chain') from exc
                if temporary not in resolved.parents:
                    raise UpstreamError('Escaping archive symlink chain')
            # Refuse to replace an existing destination, including an empty directory.
            destination.mkdir(mode=0o700)
            for p in temporary.iterdir():p.rename(destination/p.name)
        finally:shutil.rmtree(temporary)

def extract(destination):
    meta=verify();safe_extract(VENDOR/'source.tar.gz',destination)
    return meta

def outcome(source,home,args):
    """Explicit compatibility pilot over the real upstream outcome command.

    Uses a private operational home. This is not a supervisor or installation.
    """
    if not args or args[0] not in {'append','unread','mark-read','unprocessed','mark-processed','list','lookup','present'}:
        raise UpstreamError('Unsupported outcome operation')
    source=Path(source).resolve();home=Path(home).resolve()
    if source==home or source in home.parents:raise UpstreamError('Operational home must be separate')
    home.mkdir(mode=0o700,parents=True,exist_ok=True)
    env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'HOME':str(home),'FM_HOME':str(home),'FM_ROOT':str(source),'FM_ROOT_OVERRIDE':str(source),'FM_STATE_OVERRIDE':str(home/'state'),'FM_CONFIG_OVERRIDE':str(home/'config')}
    (home/'state').mkdir(mode=0o700,exist_ok=True)
    r=subprocess.run(['bash',str(source/'bin/fm-branch-outcome.sh'),*args],env=env,text=True,capture_output=True,timeout=30)
    if r.returncode:raise UpstreamError('Upstream outcome command failed: '+r.stderr[:1000])
    return r.stdout

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('verify');p=sub.add_parser('extract');p.add_argument('destination')
    args=parser.parse_args()
    try:print(json.dumps(extract(args.destination) if args.command=='extract' else verify(),sort_keys=True))
    except (OSError,UpstreamError,tarfile.TarError) as exc:parser.exit(1,str(exc)+'\n')
if __name__=='__main__':main()
