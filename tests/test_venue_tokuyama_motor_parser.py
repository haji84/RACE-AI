import unittest
from race_ai.core import SourceError
from race_ai.venue_tokuyama_motor_parser import parse_motor_allocation

URL="https://www.boatrace-tokuyama.jp/modules/raceinfo/?kind=2&page=index_timerank"
ROW="<tr><td>1</td><td>4515</td><td>A2</td><td>藤田　浩人</td><td>15</td><td>37.5%</td><td>21</td><td>27.7%</td><td>6.78</td></tr>"


class TokuyamaMotorParserTests(unittest.TestCase):
    def test_published_column_shape(self):
        result=parse_motor_allocation("<table>"+ROW+"</table>",source_url=URL)
        self.assertEqual(result[0]["racer_registration_id"],"4515")
        self.assertEqual(result[0]["motor_no"],15)
        self.assertEqual(result[0]["name"],"藤田浩人")

    def test_duplicate_racer_rejected(self):
        with self.assertRaises(SourceError):
            parse_motor_allocation("<table>"+ROW+ROW+"</table>",source_url=URL)

    def test_wrong_source_rejected(self):
        with self.assertRaises(SourceError):
            parse_motor_allocation("<table>"+ROW+"</table>",source_url="https://example.com/")
