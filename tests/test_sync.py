import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from sync import parse_murcia, iso_date, http_time, initial_data

class FederationTests(unittest.TestCase):
    def test_murcia_without_hour_is_not_a_confirmed_appointment(self):
        html='<table><tr><td>10</td><td><h5>UNION MOLINENSE</h5><h5>E.F. MOLINA</h5><h5>22-11-2026</h5></td><td> - </td></tr><tr><td>9</td><td><h5>UNION MOLINENSE</h5><h5>CIEZA</h5><h5>13-11-2026 19:45</h5></td><td>6 - 0</td></tr></table>'
        games=parse_murcia(html,{'id':'iker','team_id':'123'},'https://www.ffrm.es/')
        self.assertEqual(games[0]['status'],'time_pending')
        self.assertIsNone(games[0]['time'])
        self.assertIsNone(games[0]['venue'])
        self.assertEqual(games[1]['score_away'],0)
        self.assertEqual(games[1]['status'],'finished')
    def test_format_failure_does_not_erase_fixtures(self):
        with self.assertRaises(ValueError):parse_murcia('<html>Inicia sesión</html>',{'id':'iker','team_id':'1'},'https://www.ffrm.es/')
    def test_date_and_time_validation(self):
        self.assertEqual(iso_date('22-11-2026'),'2026-11-22')
        self.assertIsNone(iso_date('31-02-2026'))
        self.assertIsNone(http_time('25:00'))
        self.assertEqual(http_time('9:05'),'09:05')
    def test_flight_json_without_evaluation(self):
        import json
        payload='5:'+json.dumps(['$','component',None,{'initialData':{'matches':[{'CODACTA':'42'}]}}])
        html='<script>self.__next_f.push('+json.dumps([1,payload])+')</script>'
        self.assertEqual(initial_data(html)['matches'][0]['CODACTA'],'42')
        with self.assertRaises(ValueError):initial_data('<script>alert(1)</script>')
    def test_valencia_numeric_date_and_zero_score(self):
        from parse_valencia import parse_team
        html='''<a href="../partidos/partido.php?cod_partido=42"><div class="match-card"><div class="m-meta">Viernes 21 noviembre de 2026 · Jornada 9</div><div class="team-row"><span class="team-name">EAF</span><span class="team-goals">0</span></div><div class="team-row"><span class="team-name">Buñol</span><span class="team-goals">1</span></div><div class="match-right">Finalizado</div></div></a>'''
        games=parse_team(html,{'id':'daniel'})
        self.assertEqual(games[0]['date'],'2026-11-21')
        self.assertEqual(games[0]['score_home'],0)
        self.assertEqual(games[0]['status'],'finished')
        with self.assertRaises(ValueError):parse_team('<h1>Portada</h1>',{'id':'daniel'})

if __name__=='__main__':unittest.main()
