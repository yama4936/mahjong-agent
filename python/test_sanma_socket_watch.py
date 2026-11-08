import unittest
from unittest.mock import Mock, patch
from sanma_socket_watch import game_page, watch

class WatchTest(unittest.TestCase):
 def test_unique_game_page_only(self):
  browser=Mock();page=Mock();page.url='https://game.mahjongsoul.com/';page.is_closed.return_value=False
  other=Mock();other.url='https://elsewhere.invalid/';other.is_closed.return_value=False
  browser.contexts=[Mock(pages=[page,other])];self.assertIs(game_page(browser),page)
  browser.contexts=[Mock(pages=[page,page])]
  with self.assertRaises(RuntimeError):game_page(browser)
 def test_watch_stops_and_detaches_without_navigation_or_click(self):
  page=Mock();page.url="https://game.mahjongsoul.com/";page.is_closed.return_value=False;finished=iter((False,True));log=Mock();audit=Mock();audit.logging_failed=False
  with patch('sanma_socket_watch.SocketAudit',return_value=audit):watch(page,log,stop=lambda:next(finished))
  audit.snapshot.assert_called_once_with('watch_stopping');audit.close.assert_called_once()
  page.goto.assert_not_called();page.reload.assert_not_called();page.mouse.click.assert_not_called();page.close.assert_not_called()

 def test_logging_failure_is_external_error_and_detaches(self):
  page=Mock();page.url='https://game.mahjongsoul.com/';page.is_closed.return_value=False
  audit=Mock();audit.logging_failed=True
  with patch('sanma_socket_watch.SocketAudit',return_value=audit), self.assertRaisesRegex(RuntimeError,'logging failed'):
   watch(page,Mock())
  audit.close.assert_called_once();page.mouse.click.assert_not_called()
 def test_navigation_to_other_host_stops(self):
  page=Mock();page.url='https://example.invalid/';page.is_closed.return_value=False
  audit=Mock();audit.logging_failed=False
  with patch('sanma_socket_watch.SocketAudit',return_value=audit), self.assertRaisesRegex(RuntimeError,'navigated away'):
   watch(page,Mock())
  audit.close.assert_called_once();page.mouse.click.assert_not_called()
