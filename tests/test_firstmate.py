import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

SPEC=importlib.util.spec_from_file_location('upstream',Path(__file__).parents[1]/'bin/firstmate.py')
m=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

class UpstreamTests(unittest.TestCase):
    def test_pinned_archive_and_license(self):
        meta=m.verify()
        self.assertEqual(meta['revision'],'427056c4181c41074ad24f051f79919330df0fa5')
        self.assertGreater(meta['files'],800)
    def test_corrupt_archive_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.tar.gz';p.write_bytes(b'bad')
            with self.assertRaises(m.UpstreamError): m.verify(p)
    def test_traversal_and_escaping_links_refused(self):
        for name,link in [('../outside',None),('safe','../../outside')]:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
                archive=Path(d)/'bad.tar'
                with tarfile.open(archive,'w') as t:
                    member=tarfile.TarInfo(name)
                    if link: member.type=tarfile.SYMTYPE;member.linkname=link
                    else: member.size=1
                    t.addfile(member,None if link else io.BytesIO(b'x'))
                with self.assertRaises(m.UpstreamError):m.safe_extract(archive,Path(d)/'output')
                self.assertFalse((Path(d)/'outside').exists())
    def test_existing_destination_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(m.UpstreamError):m.extract(Path(d))
    def test_real_upstream_outcomes_survive_presentation(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'source';home=Path(d)/'home'
            m.extract(source)
            m.outcome(source,home,['append','--task','demo','--verdict','captain','--summary','Review needed'])
            rows=json.loads(m.outcome(source,home,['unread']).strip())
            self.assertEqual(rows['summary'],'Review needed')
            m.outcome(source,home,['mark-read','--through','1'])
            self.assertEqual(m.outcome(source,home,['unread']).strip(),'')
            self.assertEqual(json.loads(m.outcome(source,home,['unprocessed']))['seq'],1)
            m.outcome(source,home,['mark-processed','--through','1'])
            self.assertEqual(m.outcome(source,home,['unprocessed']).strip(),'')
