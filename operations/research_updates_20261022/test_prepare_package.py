import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('prepare_package', Path(__file__).with_name('prepare_package.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'public'; self.source.mkdir()
        self.original = b"account = 'synthetic_account'\n"
        span = {'start':11, 'end':28, 'token':'__PRIVATE_VALUE_1__'}
        public = module.public_form(self.original, [span])
        (self.source/'run.py.in').write_bytes(public)
        self.archive = self.root/'example.zip'
        with zipfile.ZipFile(self.archive,'w') as z:
            z.writestr('example/run.py',self.original)
            z.writestr('example/config.json',b'{}')
        self.manifest = dict(archive_sha256=module.digest(self.archive.read_bytes()),
            archive_root='example',files=[dict(path='run.py',published_path='run.py.in',
            sha256=module.digest(self.original),published_sha256=module.digest(public),
            size=len(self.original),redactions=[span])],
            omitted_files=[dict(path='config.json',size=2,sha256=module.digest(b'{}'))])

    def test_restores_original_bytes_and_omitted_configuration(self):
        output=self.root/'restored'
        self.assertEqual(module.prepare(self.manifest,self.archive,self.source,output),2)
        self.assertEqual((output/'run.py').read_bytes(),self.original)
        self.assertEqual((output/'config.json').read_bytes(),b'{}')

    def test_public_source_tamper_is_rejected_before_writes(self):
        (self.source/'run.py.in').write_text('changed')
        with self.assertRaises(ValueError):module.prepare(self.manifest,self.archive,self.source,self.root/'new')
        self.assertFalse((self.root/'new').exists())

    def test_original_archive_tamper_is_rejected(self):
        self.archive.write_bytes(self.archive.read_bytes()+b'changed')
        with self.assertRaises(ValueError):module.verify_archive(self.manifest,self.archive,self.source)

    def test_wrong_redaction_is_rejected(self):
        self.manifest['files'][0]['redactions'][0]['start']=10
        with self.assertRaises(ValueError):module.verify_archive(self.manifest,self.archive,self.source)

    def test_no_existing_destination_overwrite(self):
        output=self.root/'restored';output.mkdir();(output/'keep').write_text('keep')
        with self.assertRaises(ValueError):module.prepare(self.manifest,self.archive,self.source,output)
        self.assertEqual((output/'keep').read_text(),'keep')

    def test_archive_traversal_is_rejected(self):
        with zipfile.ZipFile(self.archive,'a') as z:z.writestr('../escape',b'bad')
        self.manifest['archive_sha256']=module.digest(self.archive.read_bytes())
        with self.assertRaises(ValueError):module.verify_archive(self.manifest,self.archive,self.source)

    def test_symlink_member_is_rejected(self):
        with zipfile.ZipFile(self.archive,'a') as z:
            info=zipfile.ZipInfo('example/link');info.create_system=3
            info.external_attr=0o120777 << 16;z.writestr(info,'run.py')
        self.manifest['archive_sha256']=module.digest(self.archive.read_bytes())
        with self.assertRaises(ValueError):module.verify_archive(self.manifest,self.archive,self.source)

    def test_private_restore_in_public_checkout_is_rejected(self):
        with self.assertRaises(ValueError):
            module.prepare(self.manifest,self.archive,self.source,module.REPO/'private_restore_test')


if __name__ == '__main__':unittest.main()
