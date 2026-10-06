"""Retain the upstream public identity without hiding new private content."""
import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('public_identity_scan',ROOT/'scripts/privacy_scan.py')
scanner=importlib.util.module_from_spec(spec);spec.loader.exec_module(scanner)


class PublicIdentityTests(unittest.TestCase):
    def test_historical_scanner_known_public_identity_only(self):
        known=next(iter(scanner.PUBLIC_COMMIT_EMAILS))
        self.assertEqual(scanner.findings(known,'scripts/privacy_scan.py'),[])
        self.assertIn('email',scanner.findings(known,'unrelated-file.txt'))

    def test_private_email_in_same_file_is_still_detected(self):
        value=next(iter(scanner.PUBLIC_COMMIT_EMAILS))+b' someone'+b'@'+b'invalid.test'
        self.assertIn('email',scanner.findings(value,'scripts/privacy_scan.py'))


if __name__=='__main__':unittest.main()
