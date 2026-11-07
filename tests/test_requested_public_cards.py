import unittest
from scripts import requested_20261104_public_cards as m
class LinkedCards(unittest.TestCase):
 def test_date_identity_and_source_links(self):
  sources=[{'url':'https://www.winticket.jp/keirin/racecard/20261104','links':['https://www.winticket.jp/keirin/aomori/racecard/2026110312/2/1','https://www.winticket.jp/keirin/aomori/racecard/2026110312/2/1','https://bad.invalid/racecard/2026110312/2/1']},{'url':'https://www.winticket.jp/keirin/aomori/racecard/2026110312/2/1','links':['https://www.winticket.jp/keirin/aomori/racecard/2026110312/1/1']}]
  self.assertEqual(m.linked_cards(sources),[('keirin','https://www.winticket.jp/keirin/aomori/racecard/2026110312/2/1')])
 def test_extract_cells_skip_script(self):
  p=m.Visible();p.feed('<h1>2026年11月4日</h1><table><tr><td>1</td><td>名前<br>85.10</td></tr></table><script>secret</script>')
  self.assertEqual(p.rows,[['1','名前\n85.10']]);self.assertNotIn('secret',p.text)
 def test_current_date_required(self):
  self.assertTrue(m.has_date('出走表（2026年11月4日）'));self.assertFalse(m.has_date('2026年11月3日'))
if __name__=='__main__':unittest.main()
