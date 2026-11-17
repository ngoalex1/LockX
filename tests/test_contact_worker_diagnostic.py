"""Offline operator diagnostics. No browser, HTTP request, relay, or provider is used."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('standalone_contact_worker_diagnostic',ROOT/'scripts/contact_worker.py')
worker=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)
LISTING='https://sfbay.craigslist.org/sby/ele/d/city-item/1234567890.html'
RELAY='private-relay@sale.craigslist.org'


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        self.job=self.directory/'job.json'
        self.job.write_text(json.dumps({'version':1,'nonce':'n'*43,'listing_url':LISTING}))
        self.calls=[]
        calls=self.calls
        class BrowserType:
            async def launch(self,**kwargs):
                calls.append(('launch',kwargs))
                return object()
        class Traffic:
            async def fetch(self,request):
                calls.append(('fetch',request.url))
                return 200,{'cookie':'PRIVATE_COOKIE'},b'PRIVATE_RESPONSE_HTML'
        helper=types.ModuleType('craigslist_contact')
        helper._Traffic=Traffic
        helper.is_craigslist_listing_url=lambda value:value==LISTING
        async def click(locator):calls.append(('click',locator))
        async def visible(page):return RELAY
        async def reveal(page,traffic,url):
            await BrowserType().launch(chromium_sandbox=True,proxy={'server':'http://127.0.0.1:9'})
            await traffic.fetch(types.SimpleNamespace(url=url+'?fingerprint=PRIVATE_QUERY',resource_type='document'))
            await helper._click_one('reply')
            await helper._click_one('email')
            return {'status':'revealed','email':await helper._visible_email(page)}
        async def run(url):return await helper._reveal(None,Traffic(),url)
        helper._click_one,helper._visible_email,helper._reveal=click,visible,reveal
        helper.reveal_craigslist_contact=run
        self.helper,self.browser=helper,BrowserType
        self.originals=(Traffic.fetch,click,visible,reveal,BrowserType.launch)
        api=types.ModuleType('playwright.async_api');api.BrowserType=BrowserType
        self.modules={'craigslist_contact':helper,'playwright.async_api':api}

    def run_diagnostic(self):
        with patch.dict(sys.modules,self.modules),patch.object(worker,'__file__',str(self.directory/'contact_worker.py')):
            return worker.diagnostic(str(self.job))

    def test_trace_reports_safe_timings_and_presence_without_recipient_or_page_data(self):
        value=self.run_diagnostic()
        self.assertEqual(set(value),{'version','nonce','url','status','trace'})
        self.assertEqual(value['status'],'diagnostic')
        self.assertEqual(set(value['trace']),{'result_status','relay_present','elapsed_s','events'})
        self.assertEqual(value['trace']['result_status'],'revealed')
        self.assertTrue(value['trace']['relay_present'])
        self.assertEqual([event['stage'] for event in value['trace']['events']],['browser-launch','fetch','click','click','visible-email','reveal'])
        fetch=next(event for event in value['trace']['events'] if event['stage']=='fetch')
        self.assertEqual(fetch['host'],'sfbay.craigslist.org')
        self.assertEqual(fetch['resource'],'document')
        self.assertEqual(fetch['http_status'],200)
        self.assertEqual(fetch['bytes'],len(b'PRIVATE_RESPONSE_HTML'))
        encoded=json.dumps(value)
        for private in [RELAY,'PRIVATE_COOKIE','PRIVATE_QUERY','PRIVATE_RESPONSE_HTML','fingerprint']:
            self.assertNotIn(private,encoded)
        self.assertLessEqual(len(encoded.encode()),7000)
        self.assertTrue(self.calls[0][1]['chromium_sandbox'])
        self.assertEqual(self.calls[0][1]['proxy']['server'],'http://127.0.0.1:9')
        self.assertEqual((self.helper._Traffic.fetch,self.helper._click_one,self.helper._visible_email,self.helper._reveal,self.browser.launch),self.originals)

    def test_fetch_errors_record_class_only_and_restore_all_methods(self):
        async def failed(traffic,request):raise RuntimeError('PRIVATE_POST_BODY cookie=PRIVATE_COOKIE '+RELAY+' https://host/path?secret=PRIVATE_QUERY')
        self.helper._Traffic.fetch=failed
        result=self.run_diagnostic()
        self.assertEqual(result['trace']['result_status'],'unavailable')
        self.assertFalse(result['trace']['relay_present'])
        fetch=next(event for event in result['trace']['events'] if event['stage']=='fetch')
        self.assertEqual(fetch['error'],'RuntimeError')
        self.assertNotIn('message',fetch)
        self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertNotIn(RELAY,json.dumps(result))
        self.assertIs(self.helper._Traffic.fetch,failed)

    def test_event_and_total_byte_limits_hold_for_repeated_operations(self):
        async def repeated(page,traffic,url):
            for _ in range(100):await self.helper._click_one('email')
            return {'status':'blocked','email':None}
        self.helper._reveal=repeated
        result=self.run_diagnostic()
        self.assertEqual(result['trace']['result_status'],'blocked')
        self.assertFalse(result['trace']['relay_present'])
        self.assertLessEqual(len(result['trace']['events']),32)
        self.assertLessEqual(len(json.dumps(result).encode()),7000)

    def test_click_timeout_checks_only_known_public_dom_flags_without_disclosing_late_relay(self):
        for relay_present,option_present in [(True,False),(False,True)]:
            class Option:
                def filter(option,**kwargs):
                    self.assertEqual(kwargs['has_text'].pattern,r'^\s*email\s*$')
                    return option
                async def count(option):return int(option_present)
            class Page:
                def locator(page,selector):
                    self.assertEqual(selector,'button.reply-option-header')
                    return Option()
            page=Page()
            async def visible(value):
                self.assertIs(value,page)
                return RELAY if relay_present else None
            async def failed_click(locator):raise TimeoutError('Locator.wait_for: Timeout 3000ms exceeded.')
            async def reveal(unused,traffic,url):
                await self.helper._click_one(types.SimpleNamespace(page=page))
            self.helper._visible_email=visible
            self.helper._click_one=failed_click
            self.helper._reveal=reveal
            value=self.run_diagnostic()
            stages=[event['stage'] for event in value['trace']['events']]
            self.assertIn('late-relay-present' if relay_present else 'late-relay-absent',stages)
            self.assertIn('email-option-present' if option_present else 'email-option-absent',stages)
            self.assertNotIn(RELAY,json.dumps(value))
            self.assertEqual(value['trace']['result_status'],'unavailable')

    def test_reply_json_records_identifier_keys_and_known_error_classifications_only(self):
        for code,expected in [('CAPTCHA_REQUIRED','captcha'),('login-required','login'),('rate_limit_exceeded','rate_limit'),('PRIVATE_VALUE','unknown')]:
            async def fetch(traffic,request):
                return 200,{},json.dumps({'error_code':code,'message':'PRIVATE_POST_BODY '+RELAY,'reply':RELAY,'invalid-key PRIVATE':'PRIVATE_VALUE'}).encode()
            async def reveal(page,traffic,url):
                await traffic.fetch(types.SimpleNamespace(url=url+'?private=PRIVATE_QUERY',resource_type='xhr'))
                return {'status':'unavailable','email':None}
            self.helper._Traffic.fetch=fetch
            self.helper._reveal=reveal
            value=self.run_diagnostic()
            event=next(event for event in value['trace']['events'] if event['stage']=='reply-response')
            self.assertEqual(event['resource'],'code_'+expected)
            self.assertEqual(event['error'],'keys_error_code_message_reply')
            encoded=json.dumps(value)
            for private in [RELAY,'PRIVATE_POST_BODY','PRIVATE_VALUE','PRIVATE_QUERY','invalid-key PRIVATE']:
                self.assertNotIn(private,encoded)
            self.assertTrue(all(set(item)<={'stage','elapsed_s','resource','host','http_status','bytes','error','message'} for item in value['trace']['events']))

    def test_large_or_nonobject_json_response_is_not_inspected(self):
        for body in [b'[]',b'{invalid',b'{"message":"'+b'x'*17000+b'"}']:
            async def fetch(traffic,request):return 200,{},body
            async def reveal(page,traffic,url):
                await traffic.fetch(types.SimpleNamespace(url=url,resource_type='fetch'))
                return {'status':'blocked','email':None}
            self.helper._Traffic.fetch=fetch
            self.helper._reveal=reveal
            value=self.run_diagnostic()
            self.assertNotIn('reply-response',[event['stage'] for event in value['trace']['events']])

    def test_only_canonical_script_job_path_is_allowed(self):
        other=self.directory/'other.json';other.write_text(self.job.read_text())
        with patch.object(worker,'__file__',str(self.directory/'contact_worker.py')):
            with self.assertRaises(ValueError):worker.diagnostic(str(other))
            self.job.unlink();self.job.symlink_to(other)
            with self.assertRaises(ValueError):worker.diagnostic(str(self.job))

    def test_error_messages_are_short_and_redact_addresses_urls_queries_and_unknown_bodies(self):
        safe=worker._diagnostic_error(RuntimeError('Page.goto: failure at https://host/path?token=abc '+RELAY))
        self.assertEqual(safe['error'],'RuntimeError')
        self.assertNotIn(RELAY,safe['message']);self.assertNotIn('https:',safe['message'])
        self.assertLessEqual(len(safe['message']),120)
        self.assertEqual(worker._diagnostic_error(ValueError('PRIVATE_POST_BODY'))['message'],'Operation failed')


if __name__=='__main__':
    unittest.main()
