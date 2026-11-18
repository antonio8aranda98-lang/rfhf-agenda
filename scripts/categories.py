"""Keep the player's age group separate from the team they play for."""
import re
import unicodedata

ORDER = {'infantil':0,'cadete':1,'juvenil':2,'senior':3}
DURATION = {'infantil':70,'cadete':80,'juvenil':90,'senior':90}


def team_category(value):
    value = unicodedata.normalize('NFKD', value).encode('ascii','ignore').decode().upper()
    if 'INFANTIL' in value or re.search(r'\b(?:U|SUB\s*)1[34]\b',value):return 'infantil'
    if 'CADETE' in value or re.search(r'\b(?:U|SUB\s*)1[56]\b',value):return 'cadete'
    if 'JUVENIL' in value or re.search(r'\b(?:U|SUB\s*)1[789]\b',value):return 'juvenil'
    return 'senior'


def verify_category(expected, actual):
    if expected and expected not in ORDER:
        raise ValueError('Categoría de edad no válida')
    if expected and ORDER[expected] > ORDER[actual]:
        raise ValueError('La categoría por año indicada es '+expected+', pero el equipo enlazado es '+actual+'. Revisa el año o el enlace antes de activar el alta.')
    return DURATION[actual]
