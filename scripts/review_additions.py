"""Bounded, read-only official-source review for Antonio's six new Madrid records."""
import json,re
from urllib.parse import urljoin,parse_qs,urlparse,urlencode
from bs4 import BeautifulSoup
from sync import Client,normalized
from official_sources import page,close_browser

def read(client,url):
    try:return BeautifulSoup(page(client,url),'html.parser')
    except Exception as error:
        print(json.dumps({'url':url,'error':str(error)[:160]},ensure_ascii=False),flush=True)
        return None

def roster(client,url,words):
    soup=read(client,url)
    if soup is None:return
    table=next((t for t in soup.select('table') if re.search(r'Jugadores\s*\(\d+\)',t.get_text())),None)
    names=[td.get_text(' ',strip=True) for td in table.select('td')] if table else []
    matches=[n for n in names if any(w in normalized(n) for w in words)]
    print(json.dumps({'roster':url,'matches':matches,'roster_present':table is not None},ensure_ascii=False),flush=True)
    if matches:
        for a in soup.select('a[href*="NFG_VisCompeticiones_Equipo"]'):
            history=read(client,urljoin(url,a['href']))
            if history is not None:
                print(json.dumps({'history':urljoin(url,a['href']),'text':history.get_text(' ',strip=True)[-17000:],'links':[(a.get_text(' ',strip=True),a['href']) for a in history.select('a[href*="NFG_VisCompeticiones_Grupo"]')]},ensure_ascii=False),flush=True)

ff=Client('https://www.ffcm.es')
query={'cod_primaria':'1000119','nueva_ventana':'','Buscar':'1','orden':'','Sch_Clave_Acceso_Club':'4001','Sch_Codigo_Club':'4001','Sch_Codigo_Categoria':'','Sch_provincia':'','Sch_Codigo_Delegacion':'','Sch_Clave_Acceso_Campo':'','Campo':'','Sch_Nombre_Equipo':'','Sch_Categoria_Club':'','Sch_Fecha_Inicio':'','Sch_Fecha_Fin':'','NPcd_PageLines':'50'}
soup=read(ff,ff.base+'/pnfg/NPcd/NFG_LstEquipos?'+urlencode(query))
if soup:
    links=[]
    for a in soup.select('a[href*="NFG_VisEquipos"]'):
        row=a.find_parent('tr');label=row.get_text(' ',strip=True)
        if 'GUADALAJARA' not in normalized(label):continue
        links.append((label,urljoin(ff.base+'/pnfg/NPcd/',a['href'])))
    print(json.dumps({'club_teams':links},ensure_ascii=False),flush=True)
    for label,url in links:
        if 'JUVENIL' in normalized(label):roster(ff,url,['FELIPE','RIOJA','GIANCARLO','ONDO'])
roster(ff,ff.base+'/pnfg/NPcd/NFG_VisEquipos?cod_primaria=1000119&Codigo_Equipo=33164',['HUGO','RUIZ ROJAS'])
cy=Client('https://www.rfcylf.es')
for team in ['12890','16389']:
    roster(cy,cy.base+'/pnfg/NPcd/NFG_VisEquipos?cod_primaria=1000119&Codigo_Equipo='+team,['ANGEL HERNAN','SANZ VARELA'])
close_browser()
